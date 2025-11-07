from pydantic import (
    BaseModel,
    model_validator,
    field_validator,
    Discriminator,
    Tag,
)
from typing import Annotated, Literal, Union


class BaseAction(BaseModel):
    """Base model for all actions, used for discriminated union."""

    ignore_error: bool = False
    bypass_condition: str | None = None


class InstallSnapAction(BaseAction):
    action: Literal["install_snap"]
    name: str
    track: str = "latest"
    risk: str = "stable"
    branch: str | None = None
    revision: str | None = None
    mode: str = ""
    post_commands: str | None = None

    @field_validator("mode")
    def check_mode(cls, mode: str):
        if mode not in ["classic", "devmode", "dangerous", ""]:
            raise ValueError("mode must be one of classic, devmode, dangerous")
        return mode

    @field_validator("revision")
    def check_revision(cls, revision: str):
        if revision and not revision.isdigit():
            raise ValueError("revision must be a digit")
        return revision

    @field_validator("risk")
    def check_risk(cls, risk: str):
        if risk not in ["stable", "candidate", "beta", "edge"]:
            raise ValueError(
                "risk must be one of 'stable', 'candidate', 'beta', 'edge'"
            )
        return risk

    @model_validator(mode="after")
    def check_branch_risk_dependency(self):
        if self.branch and not self.risk:
            raise ValueError("'risk' must be provided with 'branch'")
        return self


class InstallDebianAction(BaseAction):
    action: Literal["install_debian"]
    name: str
    repo: str | None = None
    revision: str | None = None


class SshCommandAction(BaseAction):
    action: Literal["ssh_command"]
    command: str
    continue_on_error: bool = False


class ScpCommandAction(BaseAction):
    action: Literal["scp_command"]
    source: str
    destination: str


class CreateSystemServiceAction(BaseAction):
    action: Literal["create_service"]
    service_name: str
    service_raw: str
    service_file_dest: str = "/etc/systemd/system"
    script_raw: str | None = None
    script_file: str | None = None
    script_file_dest: str | None = None
    post_commands: str | None = None

    @model_validator(mode="after")
    def check_script_file_dependency(self):
        if self.script_file and not self.script_raw:
            raise ValueError(
                "'script_raw' must be provided with 'script_file'"
            )
        return self


class LoadTemplateAction(BaseAction):
    action: Literal["load_template"]
    name: str


class GitCloneAction(BaseAction):
    action: Literal["git_clone"]
    repo: str
    # branch, tag or commit-ish
    ref: str | None = None
    # shallow clone depth
    depth: int | None = None
    # optional subpath inside the repo to copy (defaults to repo root)
    subpath: str | None = None
    # optional command to run on remote after copy
    post_commands: str | None = None


AnyAction = Union[
    InstallSnapAction,
    InstallDebianAction,
    SshCommandAction,
    ScpCommandAction,
    CreateSystemServiceAction,
    LoadTemplateAction,
    GitCloneAction,
]


def find_tag(payload):
    if isinstance(payload, dict):
        return payload.get("action")
    return getattr(payload, "action", None)


ActionUnion = Annotated[
    Union[
        Annotated[InstallSnapAction, Tag("install_snap")],
        Annotated[InstallDebianAction, Tag("install_debian")],
        Annotated[SshCommandAction, Tag("ssh_command")],
        Annotated[ScpCommandAction, Tag("scp_command")],
        Annotated[CreateSystemServiceAction, Tag("create_service")],
        Annotated[LoadTemplateAction, Tag("load_template")],
        Annotated[GitCloneAction, Tag("git_clone")],
    ],
    Discriminator(find_tag),
]


class EnvSetup(BaseModel):
    actions: list[ActionUnion]
