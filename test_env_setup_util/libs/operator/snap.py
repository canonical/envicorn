import logging
import re

from libs.exceptions import SnapCommandError


def install_snap(session, snap_data):
    check_snap_utility(session)

    name = snap_data["name"]
    revision = snap_data.get("revision")
    track = snap_data.get("track")
    risk = snap_data.get("risk")
    branch = snap_data.get("branch")

    ret = 0
    installed_rev, installed_tracks = get_snap_info(session, name)
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

        ret, _, _ = session.launch_ssh_command(_cmd)

    if snap_data.get("post_commands") and ret == 0:
        command = snap_data["post_commands"]
        ret, _, _ = session.launch_ssh_command(command)
        if ret != 0:
            raise SnapCommandError(command)


def get_snap_info(session, name):

    command = f"snap info {name}"
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
