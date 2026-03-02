import logging
import time

from test_env_setup_util.libs.exceptions import SshCommandError


def install_debian(session, debian_data):
    retry_on_failure = debian_data.get("retry_on_failure", False)
    retry_count = (
        debian_data.get("retry_count", 3) if retry_on_failure else None
    )
    retry_delay = (
        debian_data.get("retry_delay", 5) if retry_on_failure else None
    )

    _cmd = f"sudo DEBIAN_FRONTEND=noninteractive apt install -y {debian_data['name']}"
    if debian_data.get("revision"):
        _cmd += f"={debian_data['revision']}"

    if retry_on_failure:
        for attempt in range(retry_count):
            update_exit_code, _, _ = session.launch_ssh_command(
                "sudo apt update", continue_on_error=True
            )
            if update_exit_code == 0:
                break
            logging.warning(
                "Attempt %d: 'sudo apt update' failed with exit code %d",
                attempt + 1,
                update_exit_code,
            )
            if attempt < retry_count - 1:
                time.sleep(retry_delay)
        else:
            raise SshCommandError(
                "Failed to update package list after retries"
            )

        for attempt in range(retry_count):
            install_exit_code, _, _ = session.launch_ssh_command(
                _cmd, continue_on_error=True
            )
            if install_exit_code == 0:
                break
            logging.warning(
                "Attempt %d: '%s' failed with exit code %d",
                attempt + 1,
                _cmd,
                install_exit_code,
            )
            if attempt < retry_count - 1:
                time.sleep(retry_delay)
        else:
            raise SshCommandError(
                f"Failed to install debian package '{debian_data['name']}' after {retry_count} retries"
            )
    else:
        session.launch_ssh_command("sudo apt update")
        session.launch_ssh_command(_cmd)
