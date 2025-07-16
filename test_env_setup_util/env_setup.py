#!/usr/bin/env python3
import argparse
import glob
import jinja2
import logging
import os
import paramiko
import sys
import paramiko.ssh_exception
import yaml

from test_env_setup_util.libs.common import validate_file_content, _check_file, _load_file
from test_env_setup_util.libs.exceptions import ExitCode
from test_env_setup_util.libs.operator.common import (
    ssh_command,
    scp_command,
    create_system_service,
)
from test_env_setup_util.libs.operator.debian import install_debian
from test_env_setup_util.libs.operator.snap import install_snap
from test_env_setup_util.libs.ssh_handler import RemoteSshSession
from pathlib import Path


SCHEMA_PATH = os.environ.get(
    "TEST_ENV_SETUP_UTIL", os.path.join(os.path.dirname(__file__), "schema")
)

ENV_SETUP_SCHEMA = os.path.join(SCHEMA_PATH, "env_setup_schema.json")


def _str_presenter(dumper, data):
    """
    Preserve multiline strings when dumping yaml.
    https://github.com/yaml/pyyaml/issues/240
    """
    if "\n" in data:
        # Remove trailing spaces messing out the output.
        block = "\n".join([line.rstrip() for line in data.splitlines()])
        if data.endswith("\n"):
            block += "\n"
        return dumper.represent_scalar(
            "tag:yaml.org,2002:str", block, style="|"
        )
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


yaml.add_representer(str, _str_presenter)
yaml.representer.SafeRepresenter.add_representer(str, _str_presenter)


class SetupOperator:
    def __init__(self, root_path, root_yaml, session, variables={}):
        self._ssh_session = session
        self._root_path = root_path
        self._root_yaml = root_yaml
        self._variables = variables

    def _create_service(self, data):
        """
        create system service file
        """
        create_system_service(self._ssh_session, data)

    def _ssh_command(self, data):
        ssh_command(self._ssh_session, data)

    def _install_snap(self, data):
        """Install required snap packages listed in configuration files

        Args:
            data (dict): snap data including name, track, risk and revision
        """
        logging.info("# Trying to install %s snap", data["name"])
        install_snap(self._ssh_session, data)

    def _install_debian(self, data):
        """
        Install required debian packages listed in configuration files
        """
        logging.info("Trying to install %s debian package", data["name"])
        install_debian(self._ssh_session, data)

    def _scp_command(self, data):
        logging.info(
            "Upload %s file to %s:%s",
            data["source"],
            self._ssh_session._ip,
            data["destination"],
        )
        scp_command(self._ssh_session, data)

    def _lookup_template_file(self, file):
        # expand var first if there's a env variable been defined
        file = os.path.expandvars(file)
        if Path(file).is_absolute():
            return file

        # looking for file from base directory
        pattern = os.path.join(self._root_path, "**", file)
        logging.debug("looking pattern string is %s", pattern)
        files = glob.glob(pattern, recursive=True)
        if files:
            return files[0]

        # looking for file from global_templates directory
        lookup_path = self._root_path
        while lookup_path:
            pattern = os.path.join(lookup_path, "global_templates", file)
            logging.debug("looking pattern string is %s", pattern)
            files = glob.glob(pattern, recursive=True)
            if files:
                return files[0]
            if lookup_path == "/":
                break
            lookup_path = os.path.dirname(lookup_path)

    def _load_template_file(self, file):
        template_file = self._lookup_template_file(file)
        if template_file is None:
            raise FileNotFoundError(f"{file} is not available")

        return self._load_env_setup_file(_check_file(template_file))

    def _load_env_setup_file(self, yaml_file):
        contents = validate_file_content(yaml_file, ENV_SETUP_SCHEMA)
        actions = []
        action_sources = []

        for action in contents["actions"]:
            if action["action"] == "load_template":
                _act, _src = self._load_template_file(action["name"])
                action_sources.extend(_src)
                actions.extend(_act)
            else:
                action_sources.append(yaml_file)
                actions.append(action)

        return actions, action_sources

    def _replace_variables(self, contents):
        """
        convert actions to yaml contents and replace variables
        """
        yaml_contents = yaml.dump(contents)
        logging.info("\n##### original yaml contents #####")
        logging.info(yaml_contents)
        env = jinja2.Environment()
        renderer = env.from_string(yaml_contents)
        content = renderer.render(self._variables)
        logging.info("\n#### updated yaml contents ####")
        logging.info(content)

        new_contents = yaml.safe_load(content)
        return new_contents

    def run(self):
        exit_code = ExitCode.Success
        results = {}
        actions, actions_sources = self._load_env_setup_file(self._root_yaml)
        actions = self._replace_variables(actions)

        for idx, action in enumerate(actions, start=1):
            try:
                header = f"\n{'='*30}"
                logging.info(header)
                logging.info(" Action %d : %s", idx, action["action"])
                logging.info(" source file: %s", actions_sources[idx - 1])
                logging.info("=" * 30)
                getattr(self, f"_{action['action']}")(action)
                results[idx] = "Success"
            except Exception as err:
                logging.error(err)
                results[idx] = "Failed"
                exit_code = ExitCode.Action_Failed
                break

        logging.info("\n\n#### Summary ####")
        for idx, result in results.items():
            logging.info("Action %d: %s", idx, result)

        return exit_code


def register_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "This is a scripts help you setup test environment, "
            "such as install snap package and debian package "
            "and create a system service"
        )
    )
    sub_parser = parser.add_subparsers(dest="mode", required=True)
    setup_parser = sub_parser.add_parser("setup")
    setup_parser.add_argument(
        "-f", "--file", type=str, required=True, help="configuration file"
    )
    setup_parser.add_argument("-v", "--variables-file", type=str, default=None)
    setup_parser.add_argument(
        "--remote-ip", type=str, required=True, help="the IP address of DUT"
    )
    setup_parser.add_argument(
        "--username", type=str, required=True, help="username for login to DUT"
    )
    setup_parser.add_argument(
        "--password",
        type=str,
        default=None,
        help="password for login to DUT",
    )
    setup_parser.add_argument(
        "--private-key-file", type=str, help="SSH private key file"
    )

    validate_parser = sub_parser.add_parser("validate")
    validate_parser.add_argument(
        "-f", "--file", type=str, required=True, help="configuration file"
    )
    parser.add_argument("--debug", action="store_true", default=False)

    return parser.parse_args()


def main() -> None:
    args = register_arguments()

    if args.debug:
        log_format = (
            "[%(filename)s_%(funcName)s - %(levelname)s] - %(message)s"
        )
        level = logging.DEBUG
    else:
        log_format = "%(message)s"
        level = logging.INFO

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter(log_format))
    logger.addHandler(console_handler)

    file_handler = logging.FileHandler("test_env_setup_debug.log")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(funcName)s [%(levelname)s] - %(message)s")
    )
    logger.addHandler(file_handler)

    env_setup_file = _check_file(args.file)
    path = os.path.dirname(env_setup_file)
    root_path = path if path else os.getcwd()

    variables = {}
    if args.variables_file:
        conf_file = _check_file(args.variables_file)
        variables = _load_file(conf_file)

    if args.mode == "setup":
        try:
            session = RemoteSshSession(
                args.remote_ip,
                args.username,
                args.password,
                args.private_key_file,
            )
            session.authentication_verification()
            operator = SetupOperator(
                root_path, env_setup_file, session, variables
            )
            sys.exit(operator.run())
        except paramiko.ssh_exception.PasswordRequiredException as err:
            logging.error("# password and passphrase is needed")
            sys.exit(ExitCode.SSH_AUTH_REQUIRED_PASSWORD_PASSPHRASE)
        except paramiko.ssh_exception.AuthenticationException as err:
            logging.error("# Username or Password is incorrect")
            sys.exit(ExitCode.SSH_AUTH_INVALID_USERNAME_PASSWORD)


if __name__ == "__main__":
    main()
