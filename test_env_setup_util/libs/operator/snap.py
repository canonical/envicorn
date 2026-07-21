import logging
import re

from shlex import quote
from test_env_setup_util.libs.exceptions import SnapCommandError


def get_store_id_from_device(session):
    """
    Retrieve the store ID from the device's snap model assertion.
    This is useful for private stores where authentication is required.

    Args:
        session: SSH session to remote machine

    Returns:
        str or None: Store ID if found, None otherwise
    """
    command = "snap model --assertion"
    ret, stdout, _ = session.launch_ssh_command(command)

    if ret != 0:
        logging.debug("Failed to get snap model assertion, no custom store ID available")
        return None

    # Parse the store field from the assertion
    # Format: "store: <store-id>"
    match = re.search(r'^store:\s+(\S+)', stdout, re.MULTILINE)
    if match:
        store_id = match.group(1)
        logging.info("Detected store ID from device: %s", store_id)
        return store_id

    logging.debug("No store ID found in snap model assertion")
    return None


def _install_snap_via_download(session, snap_data, store_id=None):
    """
    Install a snap using the download-ack-install flow.
    This method works for both public and private snaps.

    Steps:
    1. Download snap with authentication (if provided)
    2. Acknowledge the snap assertion (validates authenticity)
    3. Install from local file with specified mode
    4. Clean up downloaded files

    Args:
        session: SSH session to remote machine
        snap_data: Dict containing snap installation parameters
        store_id: Optional store ID (will be auto-detected if not provided)

    Returns:
        int: Return code (0 for success)
    """
    name = snap_data["name"]
    revision = snap_data.get("revision")
    track = snap_data.get("track")
    risk = snap_data.get("risk")
    branch = snap_data.get("branch")
    store_auth = snap_data.get("store_auth")
    mode = snap_data.get("mode")

    # Auto-detect store ID if not provided
    if store_id is None:
        store_id = get_store_id_from_device(session)

    # Build environment variables for authentication
    env_vars = ""
    if store_id:
        env_vars += f"UBUNTU_STORE_ID={quote(store_id)} "
    if store_auth:
        env_vars += f"UBUNTU_STORE_AUTH={quote(store_auth)} "

    # Build channel or revision specification
    if revision:
        channel_spec = f"--revision={quote(revision)}"
    else:
        channel = f"{track}/{risk}"
        if branch:
            channel += f"/{branch}"
        channel_spec = f"--channel={quote(channel)}"

    # Use a unique basename to avoid conflicts
    basename = f"{name}-download"

    try:
        # Step 1: Download the snap with authentication
        download_cmd = f"{env_vars}snap download {quote(name)} {channel_spec} --basename={quote(basename)}"
        logging.info("Downloading snap with authentication")
        ret, _, stderr = session.launch_ssh_command(download_cmd)
        if ret != 0:
            raise SnapCommandError(f"Failed to download snap {name}: {stderr}")

        # Step 2: Acknowledge the snap assertion
        ack_cmd = f"sudo snap ack {quote(basename)}.assert"
        logging.info("Acknowledging snap assertion")
        ret, _, stderr = session.launch_ssh_command(ack_cmd)
        if ret != 0:
            raise SnapCommandError(f"Failed to acknowledge snap assertion: {stderr}")

        # Step 3: Install from local file
        install_cmd = f"sudo snap install {quote(basename)}.snap"
        if mode:
            install_cmd += f" --{mode}"

        logging.info("Installing snap from local file")
        ret, _, stderr = session.launch_ssh_command(install_cmd)
        if ret != 0:
            raise SnapCommandError(f"Failed to install snap from file: {stderr}")

        return 0

    finally:
        # Step 4: Clean up downloaded files
        cleanup_cmd = f"rm -f {quote(basename)}.snap {quote(basename)}.assert"
        logging.debug("Cleaning up downloaded files")
        session.launch_ssh_command(cleanup_cmd)


def _install_snap_directly(session, snap_data):
    """
    Install a snap using the direct install/refresh command.
    This is the traditional method for public snaps.

    Args:
        session: SSH session to remote machine
        snap_data: Dict containing snap installation parameters

    Returns:
        int: Return code from the installation command
    """
    name = snap_data["name"]
    revision = snap_data.get("revision")
    track = snap_data.get("track")
    risk = snap_data.get("risk")
    branch = snap_data.get("branch")

    installed_rev, installed_tracks = get_snap_info(session, name)

    # Check if snap is already installed with the same revision or channel
    if revision == installed_rev.strip("()"):
        logging.info("%s snap has been installed with the same revision", name)
        return 0
    elif f"{track}/{risk}" in installed_tracks:
        logging.info(
            "%s snap has been installed with the same track and risk", name
        )
        return 0

    # Build install/refresh command
    if installed_rev:
        _cmd = f"sudo snap refresh {quote(name)}"
    else:
        _cmd = f"sudo snap install {quote(name)}"

    if revision:
        _cmd += f" --revision={quote(revision)}"
    else:
        _arg = f"{track}/{risk}"
        if branch:
            _arg += f"/{branch}"
        _cmd += f" --channel={quote(_arg)}"

    if snap_data.get("mode"):
        _cmd += f" --{snap_data['mode']}"

    ret, _, _ = session.launch_ssh_command(_cmd)
    return ret


def install_snap(session, snap_data):
    """
    Install a snap package on the remote system.

    Automatically detects whether to use the download-ack-install flow
    (for private snaps with authentication) or direct installation
    (for public snaps).

    Args:
        session: SSH session to remote machine
        snap_data: Dict containing snap installation parameters including:
            - name: Snap package name (required)
            - track: Snap track (default: "latest")
            - risk: Snap risk level (default: "stable")
            - branch: Snap branch (optional)
            - revision: Specific revision (optional)
            - mode: Installation mode (classic/devmode/dangerous)
            - store_auth: Base64 encoded store credentials (optional)
            - store_id: Custom store ID (optional, auto-detected if not provided)
            - post_commands: Commands to run after installation (optional)
    """
    check_snap_utility(session)

    name = snap_data["name"]
    store_auth = snap_data.get("store_auth")
    store_id = snap_data.get("store_id")

    # Determine installation method based on authentication requirements
    if store_auth or store_id:
        # Use download-ack-install flow for private/authenticated snaps
        logging.info("Installing %s snap using authenticated download method", name)
        ret = _install_snap_via_download(session, snap_data, store_id)
    else:
        # Use direct install for public snaps
        logging.info("Installing %s snap using direct method", name)
        ret = _install_snap_directly(session, snap_data)

    # Execute post-installation commands if specified
    if snap_data.get("post_commands") and ret == 0:
        command = snap_data["post_commands"]
        ret, _, _ = session.launch_ssh_command(command)
        if ret != 0:
            raise SnapCommandError(command)


def get_snap_info(session, name):

    command = f"snap info {quote(name)}"
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
