import json
import logging
import os
import re
import yaml
from pathlib import Path
from pydantic import ValidationError

from test_env_setup_util.libs.model import EnvSetup


def _check_file(file):
    # expand var first if there's a env variable been defined
    file = os.path.expandvars(file)
    file = os.path.abspath(file)
    if Path(file).exists():
        return file
    else:
        raise FileNotFoundError("the {} does not exist".format(file))


def _load_file(file: Path) -> str:
    ext = file.suffix

    with open(file, "r") as fp:
        if ext == ".json":
            content = json.load(fp)
        elif ext in [".yaml", ".yml"]:
            content = yaml.safe_load(fp)
        else:
            raise SystemExit(f"Unsupported file format: {file}")

    return content


def _find_env_pattern(string: str) -> str:
    _match = re.search(r"^\$([a-zA-Z0-9_]+)$", string)
    if _match:
        return _match.group(1)    
    _match = re.search(r"^\$\{([a-zA-Z0-9_]+)\}$", string)
    if _match:
        return _match.group(1)


def _update_env(variables: dict) -> None:
    for key, value in variables.items():
        _env_key = _find_env_pattern(value)
        if _env_key:
            variables[key] = os.getenv(_env_key, "") 


def validate_file_content(file: Path) -> dict:
    """
    validate the file content with Pydantic models
    """
    if file.suffix not in [".yaml", ".yml", ".json"]:
        raise ValueError("Unsupported file type")

    logging.info(
        "Validating the contents of %s file with Pydantic models",
        file,
    )

    content = _load_file(file)
    try:
        env_setup_model = EnvSetup.model_validate(content)
        if "global_templates" in str(file.parent):
            for action in env_setup_model.actions:
                if action.bypass_condition:
                    raise KeyError(
                        "bypass_condition is not allowed in global_templates"
                    )
        validated_content = env_setup_model.model_dump()
    except ValidationError as e:
        logging.error("Validation failed for %s:\n%s", file, e)
        raise

    logging.debug("\tthe contents of %s file as following", file)
    logging.debug(validated_content)

    return validated_content
