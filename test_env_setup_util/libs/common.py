import json
import logging
import os
import yaml

from jsonschema import validate
from pathlib import Path


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


def validate_file_content(file: str, schema_file: str) -> dict:
    """
    validate the file content with env_setup_schema and service_schema files
    """
    _, ext = os.path.splitext(file)
    if ext not in [".yaml", ".yml", ".json"]:
        raise ValueError("Unsupported file type")

    logging.info(
        "Validate the contents of %s file with %s schema",
        file,
        schema_file,
    )

    content = _load_file(file)
    with open(schema_file, "r") as fp:
        schema_content = json.load(fp)
    validate(content, schema_content)

    logging.debug("the contents of %s file as following", file)
    logging.debug(content)

    return content
