#!/usr/bin/env python3
import argparse
import ast
import glob
import jinja2
import logging
import os
import paramiko
import sys
import paramiko.ssh_exception
import yaml

from pydantic import ValidationError
from test_env_setup_util.libs.common import (
    validate_file_content,
    _check_file,
    _load_file,
)
from test_env_setup_util.libs.exceptions import ExitCode
from test_env_setup_util.libs.model import EnvSetup
from test_env_setup_util.libs.operator.common import (
    ssh_command,
    scp_command,
    create_system_service,
)
from test_env_setup_util.libs.operator.debian import install_debian
from test_env_setup_util.libs.operator.snap import install_snap
from test_env_setup_util.libs.ssh_handler import RemoteSshSession
from pathlib import Path


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
    def __init__(self, root_path, root_yaml, session=None, variables={}, dump_file=None):
        self._ssh_session = session
        self._root_path = root_path
        self._root_yaml = root_yaml
        self._variables = variables
        self._dump_file = dump_file

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
        contents = validate_file_content(Path(yaml_file))
        actions = []
        action_sources = []
        bypass_actions = []

        for action in contents["actions"]:
            new_action = self._replace_variables(action)
            if new_action.get("bypass_condition"):
                try:
                    if ast.literal_eval(new_action["bypass_condition"]):
                        bypass_actions.append(new_action)
                        continue
                except Exception:
                    continue

            if new_action["action"] == "load_template":
                _act, _src, _bypass = self._load_template_file(action["name"])
                action_sources.extend(_src)
                actions.extend(_act)
                bypass_actions.extend(_bypass)
            else:
                action_sources.append(yaml_file)
                actions.append(action)

        return actions, action_sources, bypass_actions

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

    def dump(self):
        raw_actions, _, _ = self._load_env_setup_file(
            self._root_yaml
        )
        rendered_actions = self._replace_variables(raw_actions)
        dump_file = self._dump_file if self._dump_file else "dump.yaml"
        logging.info("Dumping final yaml to %s", dump_file)
        with open(dump_file, "w") as f:
            yaml.dump({"actions": rendered_actions}, f)
        return ExitCode.Success

    def run(self):
        exit_code = ExitCode.Success
        results = {}
        raw_actions, actions_src, bypass_actions = self._load_env_setup_file(
            self._root_yaml
        )

        rendered_actions = self._replace_variables(raw_actions)
        try:
            # Re-validate after replacing variables to ensure correctness
            updated_actions = {"actions": rendered_actions}
            validated_data = EnvSetup.model_validate(updated_actions)
            actions = validated_data.actions
        except ValidationError as e:
            logging.error(
                "Validation failed after replacing variables:\n%s", e
            )
            return ExitCode.Action_Failed

        for idx, action_model in enumerate(actions, start=1):
            try:
                header = f"\n{'='*30}"
                logging.info(header)
                logging.info(" Action %d : %s", idx, action_model.action)
                logging.info(" source file: %s", actions_src[idx - 1])
                logging.info("=" * 30)
                getattr(self, f"_{action_model.action}")(
                    action_model.model_dump()
                )
                results[idx] = "Success"
            except Exception as err:
                logging.error(err)
                results[idx] = "Failed"
                if action_model.ignore_error:
                    continue
                exit_code = ExitCode.Action_Failed
                break

        logging.info("\n\n#### Summary ####")
        for idx, result in results.items():
            logging.info("Action %d: %s", idx, result)

        for action in bypass_actions:
            logging.info(
                "%s action been excluded. details: %s",
                action["action"],
                action,
            )

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

    dump_parser = sub_parser.add_parser("dump")
    dump_parser.add_argument(
        "-f", "--file", type=str, required=True, help="configuration file"
    )
    dump_parser.add_argument("-v", "--variables-file", type=str, default=None)
    dump_parser.add_argument(
        "-o", "--output", type=str, default=None, help="output file"
    )

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

    if args.mode == "setup":
        variables = {}
        if args.variables_file:
            conf_file = _check_file(args.variables_file)
            variables = _load_file(Path(conf_file))

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
    elif args.mode == "dump":
        variables = {}
        if args.variables_file:
            conf_file = _check_file(args.variables_file)
            variables = _load_file(Path(conf_file))

        operator = SetupOperator(
            root_path, env_setup_file, session=None, variables=variables, dump_file=args.output
        )
        sys.exit(operator.dump())
    elif args.mode == "validate":
        validate_file_content(Path(env_setup_file))
        logging.info("Validation successful for %s", env_setup_file)
        sys.exit(ExitCode.Success)


if __name__ == "__main__":
    main()
