import logging
import os
import tempfile
from pathlib import Path
from shlex import quote


def install_debian(session, debian_data):
    _cmd = "sudo DEBIAN_FRONTEND=noninteractive apt install -y {pkg}".format(
        pkg=quote(debian_data['name'])
    )
    if debian_data.get("revision"):
        _cmd += f"={quote(debian_data['revision'])}"

    logging.info("install %s debian package", debian_data["name"])
    session.launch_ssh_command(_cmd)


def add_apt_source(session, ppa_data):
    """
    Add a single APT source (PPA) with optional authentication.
    
    Auth config is created locally and copied to remote via SCP.
    This is more secure than passing tokens through shell commands.
    
    Credentials are specified directly in YAML:
    - auth_user: username for authentication
    - auth_token_var: name of environment variable containing the token
    
    The auth_machine field (optional) specifies the target hostname.
    If not provided, defaults to "launchpad.net" for Launchpad PPAs.
    
    Example YAML (with authentication):
        action: add_apt_source
        ppa_url: ppa:leuven-team/leuven-gstreamer
        auth_user: your-username
        auth_token_var: PPA1_TOKEN
        auth_machine: launchpad.net
        
    Example YAML (public PPA, no auth):
        action: add_apt_source
        ppa_url: ppa:public-team/public-ppa
    """
    ppa_url = ppa_data.get("ppa_url")

    if not ppa_url:
        raise ValueError("ppa_url is required")

    auth_user = ppa_data.get("auth_user")
    auth_token_var = ppa_data.get("auth_token_var")

    auth_token = None
    if auth_user and auth_token_var:
        auth_token = os.environ.get(auth_token_var, "").strip()
        if not auth_token:
            logging.warning(
                "Environment variable '%s' not found for %s",
                auth_token_var,
                ppa_url,
            )

    cmd = f"sudo add-apt-repository {quote(ppa_url)} -y"
    if auth_user and auth_token:
        auth_machine = ppa_data.get("auth_machine", "launchpad.net")
        auth_setup = _setup_apt_auth_via_scp(
            session, ppa_url, auth_machine, auth_user, auth_token
        )
        if not auth_setup:
            logging.warning(
                "Failed to setup auth for %s, continuing without auth",
                ppa_url,
            )
    else:
        if auth_user or auth_token_var:
            logging.debug(
                "Auth credentials incomplete for %s (missing user or token)",
                ppa_url,
            )
        else:
            logging.debug(
                "No credentials configured for %s (optional for public PPAs)",
                ppa_url,
            )

    logging.info("Adding APT source: %s", ppa_url)
    session.launch_ssh_command(cmd)


def _extract_ppa_id(ppa_url: str) -> str:
    """
    Extract PPA identifier from ppa_url.
    E.g., "ppa:leuven-team/leuven-gstreamer" => "leuven_gstreamer"
    """
    if ppa_url.startswith("ppa:"):
        ppa_url = ppa_url[4:]
    ppa_id = ppa_url.split("/")[-1]
    return ppa_id.replace("-", "_")


def _setup_apt_auth_via_scp(session, ppa_url, auth_machine, username, token):
    """
    Configure APT authentication by creating a file locally and copying via SCP.
    This is more secure than passing tokens through shell commands.
    
    Uses netrc-like format per man apt_auth.conf(5)
    Format: machine [protocol://]hostname[:port][/path]
    """
    ppa_id = _extract_ppa_id(ppa_url)
    auth_conf_filename = f"launchpad-{ppa_id}"
    remote_auth_conf = f"/etc/apt/auth.conf.d/{auth_conf_filename}"

    auth_content = f"machine {auth_machine} login {username} password {token}\n"

    try:
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".conf"
        ) as fp:
            fp.write(auth_content)
            temp_file = fp.name

        logging.info(
            "Copying auth config for %s to %s", ppa_url, remote_auth_conf
        )
        session.launch_scp_upload(temp_file, auth_conf_filename)

        auth_conf_filename = quote(auth_conf_filename)
        remote_auth_conf = quote(remote_auth_conf)

        session.launch_ssh_command(
            f"sudo mv {auth_conf_filename} {remote_auth_conf}"
        )
        session.launch_ssh_command(f"sudo chmod 600 {remote_auth_conf}")

        logging.info(
            "APT authentication configured for %s (machine: %s)",
            ppa_url,
            auth_machine,
        )
        return True

    except Exception as e:
        logging.error(
            "Failed to setup APT auth for %s: %s", ppa_url, str(e)
        )
        return False

    finally:
        if "temp_file" in locals():
            try:
                Path(temp_file).unlink()
                logging.debug("Cleaned up temporary auth config file")
            except Exception as e:
                logging.warning("Failed to cleanup temp file: %s", str(e))

