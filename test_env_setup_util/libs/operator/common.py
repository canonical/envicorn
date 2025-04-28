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


def create_system_service(session, data):
    logging.info("Creating the %s service", data["service_name"])

    script_file = None
    if data.get("script_file"):
        script_file = _check_file(data.get("script_file"))
        if data.get("script_file_dest") is None:
            logging.error("script_file_dest not defined")
            return
        target_file = os.path.join(
            data["script_file_dest"],
            os.path.basename(script_file),
        )
        # SCP file to DUT
        session.launch_scp_upload(script_file, target_file)
        session.launch_ssh_command(f"chmod 755 {target_file}")

    # Create service file
    service_file = data["service_name"]
    service_file_dest = os.path.join(
        data["service_file_dest"], data["service_name"]
    )
    with tempfile.NamedTemporaryFile(delete_on_close=False) as fp:
        fp.write(data["service_raw"].encode("utf-8"))
        fp.close()
        session.launch_scp_upload(fp.name, service_file)

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

    if data["post_commands"]:
        session.launch_ssh_command(data["post_commands"])
