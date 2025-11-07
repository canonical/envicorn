import logging
import paramiko

from contextlib import contextmanager
from test_env_setup_util.libs.exceptions import SshCommandError
from pathlib import Path
from scp import SCPClient, SCPException


class RemoteSshSession:
    def __init__(self, ip, username, password, private_key_file=None):
        self._ip = ip
        self._username = username
        self._password = password
        self._key_file = private_key_file

    def _init_client_session(self):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            self._ip,
            username=self._username,
            password=self._password,
            key_filename=self._key_file,
        )
        return client

    def authentication_verification(self):
        with self._create_client() as client:
            client.invoke_shell()

    @contextmanager
    def _create_client(self):
        client = None
        try:
            client = self._init_client_session()
            yield client
        finally:
            if client is not None:
                client.close()

    def launch_ssh_command(
        self, command, accepted_exit_codes=[0], continue_on_error=False
    ):
        exit_code = None
        log_stdout = log_stderr = ""

        if not continue_on_error:
            exec_command = "set -ex\n" + command
        else:
            exec_command = "set -x\n" + command

        with self._create_client() as client:
            _, stdout, stderr = client.exec_command(exec_command)
            log_stdout = stdout.read().decode("utf8")
            log_stderr = stderr.read().decode("utf8")
            exit_code = stdout.channel.recv_exit_status()
            logging.info("## command output:")
            logging.info("$ %s", exec_command)
            logging.info("> response: \n%s", log_stdout)
            logging.info("> exit code: %s", exit_code)

            if continue_on_error:
                logging.info("> %s", log_stderr)
            else:
                if exit_code not in accepted_exit_codes:
                    logging.error("> %s", log_stderr)
                    raise SshCommandError(command)

        return exit_code, log_stdout, log_stderr

    def launch_scp_upload(self, src, dest):
        source_path = Path(src)
        if not source_path.exists():
            raise FileNotFoundError(f"{source_path} is not available")

        try:
            with self._create_client() as client:
                with SCPClient(client.get_transport()) as scp:
                    # support uploading files or whole directories
                    if source_path.is_dir():
                        scp.put(src, dest, recursive=True)
                    else:
                        scp.put(src, dest)
        except SCPException as e:
            logging.error("SCP transfer failed: %s", str(e))
            raise
