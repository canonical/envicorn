import logging
import os
import paramiko
import tempfile
import time

import paramiko.ssh_exception

from libs.common import _check_file


def ssh_command(session, data):
    session.launch_ssh_command(
        data["command"],
        continue_on_error=data.get("continue_on_error", False),
    )


def scp_command(session, data):
    session.launch_scp_upload(data["source"], data["destination"])


def _gen_file_and_scp(contents, filename, session):
    with tempfile.NamedTemporaryFile(delete_on_close=False) as fp:
        fp.write(contents)
        fp.close()
        session.launch_scp_upload(fp.name, filename)


def create_system_service(session, data):
    logging.info("Creating the %s service", data["service_name"])

    # create script file if needed
    script_file = data.get("script_file")
    script_file_dest = data.get("script_file_dest")
    if script_file:
        _gen_file_and_scp(
            data["script_raw"].encode("utf-8"), script_file, session
        )
        with tempfile.NamedTemporaryFile(delete_on_close=False) as fp:
            fp.write(data["script_raw"].encode("utf-8"))
            fp.close()
            session.launch_scp_upload(fp.name, script_file)

        session.launch_ssh_command(f"chmod 755 {script_file}")
        if script_file_dest:
            session.launch_ssh_command(
                f"sudo mv {script_file} {script_file_dest}"
            )

    # Create service file
    service_file = data["service_name"]
    service_file_dest = os.path.join(
        data["service_file_dest"], data["service_name"]
    )
    _gen_file_and_scp(
        data["service_raw"].encode("utf-8"), service_file, session
    )

    session.launch_ssh_command(f"chmod 644 {service_file}")
    session.launch_ssh_command(f"sudo mv {service_file} {service_file_dest}")

    # Check service
    session.launch_ssh_command("sudo systemctl daemon-reload")
    session.launch_ssh_command(f"sudo systemctl enable {data['service_name']}")
    session.launch_ssh_command(f"sudo systemctl start {data['service_name']}")
    session.launch_ssh_command(
        f"sudo systemctl status {data['service_name']}",
        [0, 3],
    )

    if data.get("post_commands"):
        session.launch_ssh_command(data["post_commands"])
