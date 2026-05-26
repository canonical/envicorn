import logging
import os
import re
import tempfile
from pathlib import Path
from shlex import quote
from urllib.parse import urlsplit

from libs.operator.common import run_command
from libs.common import _find_env_pattern, _get_env


_PPA_URL_PATTERN = re.compile(
    r"^ppa:([a-z0-9][a-z0-9.+\-]*)/([a-z0-9][a-z0-9.+\-]*)$"
)


def install_debian(session, debian_data):
    _cmd = "sudo DEBIAN_FRONTEND=noninteractive apt install -y {pkg}".format(
        pkg=quote(debian_data["name"])
    )
    if debian_data.get("revision"):
        _cmd += f"={quote(debian_data['revision'])}"

    logging.info("install %s debian package", debian_data["name"])
    session.launch_ssh_command(_cmd)


def add_apt_source(session, ppa_data):
    """
    Add a single APT source using Deb822 format with optional authentication and GPG signing.

    IMPORTANT: This function uses Deb822 format instead of add-apt-repository because:
    - For PRIVATE PPAs, add-apt-repository requires --login argument which cannot pass
      credentials securely through command line
    - Deb822 format allows secure credential handling via /etc/apt/auth.conf.d/
    - Deb822 is the modern, recommended format for APT sources in Ubuntu 22.04+

    Source definitions are written to /etc/apt/sources.list.d/<ppa_name>.sources.

    URL formats supported:
    - Public PPA shorthand: ppa:team/ppa-name (e.g., ppa:ubuntu/ubuntu-server)
      → Auto-detected as public, no auth needed, converted to Deb822 with defaults
    - Private PPA full URL: https://private-ppa.launchpadcontent.net/team/name/ubuntu
      → Auto-detected as private, requires auth_user + auth_token_var
      → Converted to Deb822 with defaults (types: deb, components: main)
    - Explicit Deb822 fields: uris, suites, components, etc.
      → For advanced users who need fine-grained control
      → Can override auto-detected defaults

    Auto-detection & defaults:
    - Suites must be provided by user input
    - Types defaults to "deb"
    - Components defaults to "main"
    - All can be overridden by explicit YAML fields

    GPG key configuration: When fingerprint and key_server are provided,
    the GPG public key is fetched from the server, exported to /etc/apt/trusted.gpg.d/,
    and the Signed-By field in Deb822 is automatically configured.

    Credentials are specified directly in YAML:
    - ppa_name: (required) identifier for source/auth config naming
    - ppa_url: (optional) either 'ppa:team/name' or full HTTPS URL
    - types: (optional) Deb822 Types field, default "deb"
    - uris: (optional) Deb822 URIs field (overrides auto-derived from ppa_url)
    - suites: (optional) Deb822 Suites field (default: auto-detected from remote)
    - components: (optional) Deb822 Components field, default "main"
    - architectures: (optional) Deb822 Architectures field
    - signed_by: (optional) Deb822 Signed-By field (auto-set if fingerprint provided)
    - trusted: (optional) Deb822 Trusted field
    - enabled: (optional) Deb822 Enabled field
    - auth_user: (optional) username for private repo authentication
    - auth_token_var: (optional) env var name containing authentication token
    - fingerprint: (optional) GPG key fingerprint to verify packages
    - key_server: (optional) GPG key server URL, default "keyserver.ubuntu.com"

    Example YAML (public PPA, minimal):
        action: add_apt_source
        ppa_url: ppa:ubuntu/ubuntu-server
        ppa_name: ubuntu-server
        suites: noble

    Example YAML (private HTTPS URL with auth and GPG):
        action: add_apt_source
        uris: https://private-ppa.launchpadcontent.net/team/gstreamer/ubuntu
        ppa_name: leuven-gstreamer
        suites: noble
        auth_user: your-username
        auth_token_var: PPA_TOKEN
        fingerprint: XXXXXXXXXXXXXXXXXXXXXXXXXXXXX
        key_server: keyserver.ubuntu.com
    """
    ppa_url = ppa_data.get("ppa_url")
    ppa_name = ppa_data.get("ppa_name")
    suites = ppa_data.get("suites")
    deb822_overrides = _extract_deb822_fields(ppa_data)

    if not ppa_name:
        raise ValueError("ppa_name is required")
    if not ppa_url and not deb822_overrides:
        raise ValueError("Either ppa_url or deb822 fields are required")

    auth_user = ppa_data.get("auth_user")
    auth_token_key = ppa_data.get("auth_token")

    auth_token = None
    if auth_user and auth_token_key:
        if _find_env_pattern(auth_token_key):
            auth_token = _get_env(_find_env_pattern(auth_token_key))
            if not auth_token:
                logging.warning(
                    "Environment variable '%s' not found for %s",
                    auth_token_key,
                    ppa_name,
                )
        else:
            auth_token = auth_token_key.strip()

    if ppa_url:
        deb822_payload = _build_deb822_from_ppa_url(ppa_url, suites)
        if deb822_overrides:
            deb822_payload.update(deb822_overrides)
    else:
        deb822_payload = deb822_overrides

    # Setup GPG key if fingerprint is provided
    fingerprint = ppa_data.get("fingerprint")
    if _find_env_pattern(fingerprint):
            fingerprint = _get_env(fingerprint)
    key_server = ppa_data.get("key_server") or "keyserver.ubuntu.com"
    if fingerprint:
        gpg_key_path = _setup_gpg_key_via_scp(
            session, ppa_name, fingerprint, key_server
        )
        if gpg_key_path:
            deb822_payload["signed_by"] = gpg_key_path
        else:
            logging.error(
                "Failed to setup GPG key for %s with fingerprint", ppa_name,
            )
            logging.error("aborting source configuration ...")
            raise RuntimeError(
                f"Failed to configure required GPG key for apt source '{ppa_name}'"
            )

    if auth_user and auth_token_key:
        # Auto-derive auth_machine from uris if not explicitly provided
        auth_machine = ppa_data.get("auth_machine")
        if not auth_machine:
            auth_machine = _derive_auth_machine_from_uris(deb822_payload)
        auth_setup = _setup_apt_auth_via_scp(
            session, ppa_name, auth_machine, auth_user, auth_token
        )
        if not auth_setup:
            logging.warning(
                "Failed to setup auth for %s, continuing without auth",
                ppa_name,
            )
    elif auth_user or auth_token_key:
        logging.debug(
            "Auth credentials incomplete for %s (missing user or token)",
            ppa_name,
        )
    else:
        logging.debug(
            "No credentials configured for %s (optional for public PPAs)",
            ppa_name,
        )

    source_setup = _setup_deb822_source_via_scp(
        session, ppa_name, _render_deb822_source(deb822_payload)
    )
    if not source_setup:
        raise ValueError(f"Failed to configure deb822 source for {ppa_name}")

    if not _validate_apt_source_with_update(session, ppa_name):
        raise ValueError(
            (
                "APT source configured but validation "
                f"via apt update failed for {ppa_name}"
            )
        )

    logging.info("Configured Deb822 APT source: %s", ppa_name)


def _build_deb822_from_ppa(ppa_url, suites):
    match = _PPA_URL_PATTERN.fullmatch(ppa_url or "")
    if not match:
        raise ValueError(
            f"Invalid ppa_url {ppa_url!r}; expected format ppa:team/name"
        )
    if not suites:
        raise ValueError("suites is required when ppa_url is provided")

    team_name, archive_name = match.groups()

    return {
        "types": "deb",
        "uris": (
            "https://ppa.launchpadcontent.net/"
            f"{team_name}/{archive_name}/ubuntu"
        ),
        "suites": suites,
        "components": "main",
    }


def _build_deb822_from_https_url(ppa_url, suites):
    """
    Build deb822 payload from a full HTTPS URL for private PPAs.

    URL format: https://private-ppa.launchpadcontent.net/team/name/ubuntu
    Extracts host, path; suites must be provided by user input.
    """
    if not suites:
        raise ValueError("suites is required when ppa_url is provided")

    return {
        "types": "deb",
        "uris": ppa_url,
        "suites": suites,
        "components": "main",
    }


def _build_deb822_from_ppa_url(ppa_url, suites):
    """
    Route ppa_url to appropriate builder based on type.

    - ppa:team/name format → _build_deb822_from_ppa()
    - https://... format → _build_deb822_from_https_url()
    """
    if ppa_url.startswith("https://"):
        return _build_deb822_from_https_url(ppa_url, suites)
    return _build_deb822_from_ppa(ppa_url, suites)


def _extract_deb822_fields(ppa_data):
    field_keys = [
        "types",
        "uris",
        "suites",
        "components",
        "architectures",
        "signed_by",
        "trusted",
        "enabled",
    ]
    payload = {
        key: ppa_data.get(key)
        for key in field_keys
        if ppa_data.get(key) is not None
    }
    return payload or None


def _derive_auth_machine_from_uris(deb822_payload):
    """
    Auto-derive auth_machine from the first URI in deb822_payload.

    Format: machine [protocol://]hostname[:port][/path]
    Example: private-ppa.launchpadcontent.net/leuven-team/leuven-gstreamer/ubuntu/

    Args:
        deb822_payload: dict with 'uris' key containing repo URIs

    Returns:
        machine entry for apt_auth.conf(5) format
    """
    uris = deb822_payload.get("uris") if deb822_payload else None
    if isinstance(uris, list) and uris:
        uri = uris[0]
    elif isinstance(uris, str):
        uri = uris
    else:
        return "launchpad.net"

    parsed = urlsplit(uri)
    host = parsed.netloc
    path = parsed.path or "/"
    if not host:
        return "launchpad.net"
    if not path.endswith("/"):
        path += "/"
    return f"{host}{path}"


def _render_deb822_source(deb822_payload):
    field_map = [
        ("types", "Types"),
        ("uris", "URIs"),
        ("suites", "Suites"),
        ("components", "Components"),
        ("architectures", "Architectures"),
        ("signed_by", "Signed-By"),
        ("trusted", "Trusted"),
        ("enabled", "Enabled"),
    ]

    required_fields = {"types", "uris", "suites", "components"}
    lines = []
    for key, deb822_key in field_map:
        value = deb822_payload.get(key)
        if value is None:
            if key in required_fields:
                raise ValueError(f"deb822.{key} is required")
            continue

        if isinstance(value, list):
            serialized = " ".join(
                str(v).strip() for v in value if str(v).strip()
            )
        elif isinstance(value, bool):
            serialized = "yes" if value else "no"
        else:
            serialized = str(value).strip()

        if not serialized:
            raise ValueError(f"deb822.{key} cannot be empty")

        lines.append(f"{deb822_key}: {serialized}")

    return "\n".join(lines) + "\n"


def _setup_deb822_source_via_scp(session, ppa_name, deb822_content):
    source_filename = f"{_sanitize_source_name(ppa_name)}.sources"
    remote_source_path = f"/etc/apt/sources.list.d/{source_filename}"

    try:
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".sources"
        ) as fp:
            fp.write(deb822_content)
            temp_file = fp.name

        logging.info(
            "Copying Deb822 source for %s to %s",
            ppa_name,
            remote_source_path,
        )
        session.launch_scp_upload(temp_file, source_filename)

        quoted_source_filename = quote(source_filename)
        quoted_remote_source_path = quote(remote_source_path)
        session.launch_ssh_command(
            f"sudo mv {quoted_source_filename} {quoted_remote_source_path}"
        )
        session.launch_ssh_command(
            f"sudo chmod 644 {quoted_remote_source_path}"
        )
        return True
    except Exception as e:
        logging.error(
            "Failed to setup Deb822 source for %s: %s", ppa_name, str(e)
        )
        return False
    finally:
        if "temp_file" in locals():
            try:
                Path(temp_file).unlink()
            except Exception as e:
                logging.warning("Failed to cleanup temp file: %s", str(e))


def _validate_apt_source_with_update(session, ppa_name):
    """
    Validate a newly added Deb822 source by running apt update only for that source.

    This avoids false failures caused by unrelated repository issues.
    """
    source_filename = f"{_sanitize_source_name(ppa_name)}.sources"
    target_source = quote(f"sources.list.d/{source_filename}")
    cmd = (
        "sudo DEBIAN_FRONTEND=noninteractive apt-get update "
        f"-o Dir::Etc::sourcelist={target_source} "
        "-o Dir::Etc::sourceparts='-' "
        "-o APT::Get::List-Cleanup='0'"
    )

    try:
        logging.info(
            "Validating apt source for %s via targeted apt update", ppa_name
        )
        session.launch_ssh_command(cmd)
        return True
    except Exception as e:
        logging.error(
            "APT source validation failed for %s: %s", ppa_name, str(e)
        )
        return False


def _sanitize_source_name(name):
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip(".-")
    if not normalized:
        raise ValueError("ppa_name must include at least one safe character")
    return normalized


def _setup_gpg_key_via_scp(session, ppa_name, fingerprint, key_server):
    """
    Fetch GPG public key from keyserver and export to remote system.

    The key is fetched on the remote system using gpg --keyserver,
    exported to /etc/apt/trusted.gpg.d/, and path is returned for Signed-By field.

    Args:
        session: SSH session object
        ppa_name: PPA identifier for key file naming
        fingerprint: GPG key fingerprint (hex string, normalized)
        key_server: GPG key server URL

    Returns:
        Path to exported key file on remote system, or None if failed
    """
    try:
        key_file = f"{_sanitize_source_name(ppa_name)}.asc"
        remote_key_path = f"/etc/apt/trusted.gpg.d/{key_file}"

        # Fetch key from keyserver on remote system
        logging.info(
            "Fetching GPG key %s from %s for %s",
            fingerprint,
            key_server,
            ppa_name,
        )
        run_command(
            f"gpg --keyserver {quote(key_server)} --recv-keys {quote(fingerprint)}"
        )

        # Export key to temporary file
        logging.info("Exporting GPG key to %s", key_file)
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".sources"
        ) as fp:
            key_file = fp.name
            run_command(
                f"gpg --export --armor {quote(fingerprint)} > {key_file}"
            )

        # Move to trusted.gpg.d with proper permissions
        session.launch_scp_upload(key_file, key_file)
        Path(key_file).unlink()
        session.launch_ssh_command(
            f"sudo mv {quote(key_file)} {quote(remote_key_path)}"
        )
        session.launch_ssh_command(f"sudo chmod 644 {quote(remote_key_path)}")

        logging.info(
            "GPG key configured at %s (fingerprint: %s)",
            remote_key_path,
            fingerprint,
        )
        return remote_key_path

    except Exception as e:
        logging.error("Failed to setup GPG key for %s: %s", ppa_name, str(e))
        return None


def _setup_apt_auth_via_scp(session, ppa_name, auth_machine, username, token):
    """
    Configure APT authentication by creating a file locally and copying via SCP.
    This is more secure than passing tokens through shell commands.

    Uses netrc-like format per man apt_auth.conf(5).
    The auth_machine should be the full path for apt authentication.

    Format: machine [protocol://]hostname[:port][/path]
    Example: private-ppa.launchpadcontent.net/leuven-team/leuven-gstreamer/ubuntu/

    Args:
        session: SSH session object
        ppa_name: PPA identifier (e.g., "leuven-gstreamer") - used for config file naming
        auth_machine: full machine path for authentication (hostname + optional path)
        username: username for authentication
        token: authentication token/password
    """
    auth_conf_filename = f"{_sanitize_source_name(ppa_name)}.conf"
    remote_auth_conf = f"/etc/apt/auth.conf.d/{auth_conf_filename}"

    auth_content = (
        f"machine {auth_machine} login {username} password {token}\n"
    )

    try:
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".conf"
        ) as fp:
            fp.write(auth_content)
            temp_file = fp.name

        logging.info(
            "Copying auth config for %s to %s", ppa_name, remote_auth_conf
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
            ppa_name,
            auth_machine,
        )
        return True

    except Exception as e:
        logging.error("Failed to setup APT auth for %s: %s", ppa_name, str(e))
        return False

    finally:
        if "temp_file" in locals():
            try:
                Path(temp_file).unlink()
                logging.debug("Cleaned up temporary auth config file")
            except Exception as e:
                logging.warning("Failed to cleanup temp file: %s", str(e))
