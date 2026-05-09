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


class AddAptSourceAction(BaseAction):
    action: Literal["add_apt_source"]
    ppa_url: str
    auth_machine: str | None = None
    auth_user: str | None = None
    auth_token_var: str | None = None

    @field_validator("ppa_url")
    def check_ppa_url(cls, ppa_url: str):
        if not ppa_url or not ppa_url.startswith("ppa:"):
            raise ValueError(
                f"Invalid PPA URL: {ppa_url} (must start with 'ppa:')"
            )
        return ppa_url

    @field_validator("auth_machine")
    def check_auth_machine(cls, auth_machine: str | None):
        if auth_machine and not auth_machine.strip():
            raise ValueError("auth_machine cannot be empty string")
        return auth_machine

    @field_validator("auth_user")
    def check_auth_user(cls, auth_user: str | None):
        if auth_user and not auth_user.strip():
            raise ValueError("auth_user cannot be empty string")
        return auth_user

    @field_validator("auth_token_var")
    def check_auth_token_var(cls, auth_token_var: str | None):
        if auth_token_var and not auth_token_var.strip():
            raise ValueError("auth_token_var cannot be empty string")
        return auth_token_var

    @model_validator(mode="after")
    def check_auth_consistency(self):
        has_user = bool(self.auth_user)
        has_token_var = bool(self.auth_token_var)

        if has_user != has_token_var:
            raise ValueError(
                "Both auth_user and auth_token_var must be provided together"
            )
        return self


AnyAction = Union[
    InstallSnapAction,
    InstallDebianAction,
    SshCommandAction,
    ScpCommandAction,
    CreateSystemServiceAction,
    LoadTemplateAction,
    AddAptSourceAction,
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
        Annotated[AddAptSourceAction, Tag("add_apt_source")],
    ],
    Discriminator(find_tag),
]


class EnvSetup(BaseModel):
    actions: list[ActionUnion]
