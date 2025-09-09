import json
import logging
import os
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


def _load_file(file) -> str:
    ext = os.path.splitext(file)

    with open(file, "r") as fp:
        if ext[1] == ".json":
            content = json.load(fp)
        elif ext[1] in [".yaml", ".yml"]:
            content = yaml.safe_load(fp)
        else:
            raise SystemExit(f"Unsupported file format: {file}")

    return content


def validate_file_content(file: str) -> dict:
    """
    validate the file content with Pydantic models
    """
    _, ext = os.path.splitext(file)
    if ext not in [".yaml", ".yml", ".json"]:
        raise ValueError("Unsupported file type")

    logging.info(
        "Validating the contents of %s file with Pydantic models",
        file,
    )

    content = _load_file(file)
    print(content)
    try:
        env_setup_model = EnvSetup(**content)
        validated_content = env_setup_model.model_dump()
        print("\tvalidated_content: ", validated_content, "vc_end")
    except ValidationError as e:
        logging.error("Validation failed for %s:\n%s", file, e)
        raise

    logging.debug("\tthe contents of %s file as following", file)
    logging.debug(validated_content)

    return validated_content
