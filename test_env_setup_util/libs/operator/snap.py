import logging
import re
import time

from test_env_setup_util.libs.exceptions import SnapCommandError


def install_snap(session, snap_data):
    check_snap_utility(session)

    name = snap_data["name"]
    revision = snap_data.get("revision")
    track = snap_data.get("track")
    risk = snap_data.get("risk")
    branch = snap_data.get("branch")

    retry_on_failure = snap_data.get("retry_on_failure", False)
    retry_count = snap_data.get("retry_count", 3) if retry_on_failure else None
    retry_delay = snap_data.get("retry_delay", 5) if retry_on_failure else None

    ret = 0
    installed_rev, installed_tracks = get_snap_info(
        session, name, retry_on_failure, retry_count, retry_delay
    )
    if revision == installed_rev.strip("()"):
        logging.info("%s snap has been installed with the same revision", name)
    elif f"{track}/{risk}" in installed_tracks:
        logging.info(
            "%s snap has been installed with the same track and risk", name
        )
    else:
        if installed_rev:
            _cmd = f"sudo snap refresh {name}"
        else:
            _cmd = f"sudo snap install {name}"

        if revision:
            _cmd += f" --revision={revision}"
        else:
            _cmd += f" --channel={track}/{risk}"
            if branch:
                _cmd += f"/{branch}"

        if snap_data.get("mode"):
            _cmd += f" --{snap_data['mode']}"

        if retry_on_failure:
            for attempt in range(retry_count):
                ret, _, _ = session.launch_ssh_command(
                    _cmd, continue_on_error=True
                )
                if ret == 0:
                    break
                if attempt < retry_count - 1:
                    time.sleep(retry_delay)
                else:
                    raise SnapCommandError(
                        f"Failed to install snap {name} after {retry_count} retries"
                    )
        else:
            ret, _, _ = session.launch_ssh_command(_cmd)

    if snap_data.get("post_commands") and ret == 0:
        command = snap_data["post_commands"]
        ret, _, _ = session.launch_ssh_command(command)
        if ret != 0:
            raise SnapCommandError(command)


def get_snap_info(
    session, name, retry_on_failure=False, retry_count=3, retry_delay=5
):

    command = f"snap info {name}"
    if retry_on_failure:
        for attempt in range(retry_count):
            ret, stdout, _ = session.launch_ssh_command(
                command, continue_on_error=True
            )
            if ret == 0:
                break
            if attempt < retry_count - 1:
                time.sleep(retry_delay)
            else:
                raise SnapCommandError(
                    f"Failed to get snap info for {name} after {retry_count} retries"
                )
    else:
        ret, stdout, _ = session.launch_ssh_command(command)
    if ret != 0:
        raise SnapCommandError(command)

    rev, tracks = parse_snap_info(stdout)
    return rev, tracks


def parse_snap_info(data):
    tracks = []
    match = re.search(
        r"installed:[ ]+([a-zA-Z\.0-9-])+[ ]+ (\([0-9]+\))", data
    )
    installed_rev = match.group(2).strip("()") if match else ""

    if installed_rev and installed_rev[0] != "x":
        match = re.findall(rf"  ([\w -\.\/:]*)\({installed_rev}\) ", data)
        tracks = [m.split(":")[0].strip() for m in match if ":" in m]

    return installed_rev, tracks


def check_snap_utility(session):

    command = "which snap"
    ret, _, _ = session.launch_ssh_command(command)
    if ret != 0:
        raise SnapCommandError(command)
