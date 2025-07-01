import logging


def install_debian(session, debian_data):
    session.launch_ssh_command("sudo apt update")
    # Install debian package
    _cmd = f"sudo apt install {debian_data['name']} -y"
    if debian_data.get("revision"):
        _cmd += f"={debian_data['rivision']}"

    logging.info("install %s debian package", debian_data["name"])
    session.launch_ssh_command(_cmd)
