import logging
import os
import subprocess
import tempfile
from pathlib import Path


def ssh_command(session, data):
    session.launch_ssh_command(
        data["command"],
        continue_on_error=data.get("continue_on_error", False),
    )


def scp_command(session, data):
    session.launch_scp_upload(data["source"], data["destination"])


def _gen_file_and_scp(contents, filename, session):
    with tempfile.NamedTemporaryFile(delete=False) as fp:
        fp.write(contents)
        fp.close()
        session.launch_scp_upload(fp.name, filename)
    Path(fp.name).unlink()


def create_system_service(session, data):
    logging.info("Creating the %s service", data["service_name"])

    # create script file if needed
    script_file = data.get("script_file")
    script_file_dest = data.get("script_file_dest")
    if script_file:
        _gen_file_and_scp(
            data["script_raw"].encode("utf-8"), script_file, session
        )

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


def git_clone(data):
    """Clone a git repository locally.

    Expected keys in `data`:
      - repo: git repository URL
      - ref: optional branch/tag/commit
      - depth: optional shallow depth
      - subpath: optional subpath inside repo to copy
      - post_commands: optional command to run on remote after copy
    """
    repo = data["repo"]
    ref = data.get("ref")
    depth = data.get("depth")
    subpath = data.get("subpath")

    # create a temporary directory and clone repo into it
    tmpdir = tempfile.mkdtemp(prefix="git_clone_")
    try:
        clone_cmd = ["git", "clone", repo, tmpdir]
        if depth:
            clone_cmd = ["git", "clone", "--depth", str(depth), repo, tmpdir]

        logging.info("Cloning repo %s into %s", repo, tmpdir)
        subprocess.check_call(clone_cmd)

        if ref:
            logging.info("Checking out %s", ref)
            subprocess.check_call(["git", "-C", tmpdir, "checkout", ref])

        source_path = Path(tmpdir)
        if subpath:
            source_path = source_path.joinpath(subpath)

        if not source_path.exists():
            raise FileNotFoundError(f"{source_path} does not exist in repo")

    except subprocess.CalledProcessError as e:
        logging.error("Git operation failed: %s", str(e))
        raise
