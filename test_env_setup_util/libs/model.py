import re

from pydantic import (
    BaseModel,
    model_validator,
    field_validator,
    Discriminator,
    Tag,
)
from typing import Annotated, Literal, Union

# PPA URLs can be either:
# 1. Public Launchpad shorthand: ppa:team/ppa-name
# 2. Full URL for private PPAs: https://private-ppa.launchpadcontent.net/team/name/ubuntu
_LAUNCHPAD_PPA_PATTERN = re.compile(
    r"^ppa:[a-z0-9][a-z0-9.+\-]*/[a-z0-9][a-z0-9.+\-]*$"
)
_HTTPS_URL_PATTERN = re.compile(r"^https://[a-zA-Z0-9.\-/]+$")


class BaseAction(BaseModel):
    """Base model for all actions, used for discriminated union."""

    ignore_error: bool = False
    bypass_condition: str | None = None


def _ensure_non_empty_str(value: str, field_name: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} cannot be empty string")
    return stripped


def _normalize_str_or_list(
    value: str | list[str], field_name: str
) -> str | list[str]:
    if isinstance(value, str):
        return _ensure_non_empty_str(value, field_name)
    if isinstance(value, list):
        if not value:
            raise ValueError(f"{field_name} cannot be an empty list")
        normalized = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError(f"{field_name} list items must be strings")
            normalized.append(_ensure_non_empty_str(item, field_name))
        return normalized
    raise ValueError(f"{field_name} must be a string or list of strings")


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
    ppa_url: str | None = None
    ppa_name: str
    types: str | list[str] = "deb"
    uris: str | list[str] | None = None
    suites: str | list[str] | None = None
    components: str | list[str] = "main"
    architectures: str | list[str] | None = None
    signed_by: str | None = None
    trusted: bool | None = None
    enabled: bool | None = None
    auth_machine: str | None = None
    auth_user: str | None = None
    auth_token_var: str | None = None
    key_server: str | None = None
    fingerprint: str | None = None

    @field_validator("ppa_name")
    def check_ppa_name(cls, ppa_name: str):
        return _ensure_non_empty_str(ppa_name, "ppa_name")

    @field_validator("ppa_url")
    def check_ppa_url(cls, ppa_url: str | None):
        if ppa_url is None:
            return ppa_url
        is_launchpad = _LAUNCHPAD_PPA_PATTERN.fullmatch(ppa_url)
        is_https_url = _HTTPS_URL_PATTERN.fullmatch(ppa_url)
        if not (is_launchpad or is_https_url):
            raise ValueError(
                f"Invalid PPA URL: {ppa_url!r}. "
                "Use either 'ppa:team/ppa-name' (public) or "
                "'https://private-ppa.launchpadcontent.net/team/name/ubuntu' (private)"
            )
        return ppa_url

    @field_validator("types", mode="before")
    def check_types(cls, types):
        return _normalize_str_or_list(types, "types")

    @field_validator("uris", "suites", mode="before")
    def check_optional_required_str_or_list(cls, value, info):
        if value is None:
            return value
        return _normalize_str_or_list(value, info.field_name)

    @field_validator("components", "architectures", mode="before")
    def check_optional_str_or_list(cls, value, info):
        if value is None:
            return value
        return _normalize_str_or_list(value, info.field_name)

    @field_validator("signed_by")
    def check_signed_by(cls, signed_by: str | None):
        if signed_by is None:
            return signed_by
        return _ensure_non_empty_str(signed_by, "signed_by")

    @field_validator("auth_machine")
    def check_auth_machine(cls, auth_machine: str | None):
        if auth_machine is None:
            return auth_machine
        return _ensure_non_empty_str(auth_machine, "auth_machine")

    @field_validator("auth_user")
    def check_auth_user(cls, auth_user: str | None):
        if auth_user is None:
            return auth_user
        return _ensure_non_empty_str(auth_user, "auth_user")

    @field_validator("auth_token_var")
    def check_auth_token_var(cls, auth_token_var: str | None):
        if auth_token_var is None:
            return auth_token_var
        return _ensure_non_empty_str(auth_token_var, "auth_token_var")

    @field_validator("key_server")
    def check_key_server(cls, key_server: str | None):
        if key_server is None:
            return key_server
        return _ensure_non_empty_str(key_server, "key_server")

    @field_validator("fingerprint")
    def check_fingerprint(cls, fingerprint: str | None):
        if fingerprint is None:
            return fingerprint
        normalized = _ensure_non_empty_str(fingerprint, "fingerprint")
        # Fingerprints are hex strings, remove common formatting
        normalized = normalized.replace(" ", "").replace(":", "").upper()
        if not all(c in "0123456789ABCDEF" for c in normalized):
            raise ValueError("fingerprint must be a valid hex string")
        if len(normalized) not in (40, 64):
            raise ValueError(
                "fingerprint must be a full 40- or 64-character hex fingerprint"
            )
        return normalized

    @model_validator(mode="after")
    def check_auth_consistency(self):
        has_flat_deb822 = bool(self.uris and self.suites)

        if not self.ppa_url and not has_flat_deb822:
            raise ValueError("Provide either ppa_url or both uris and suites")

        if self.ppa_url and has_flat_deb822:
            raise ValueError(
                "ppa_url cannot be used together with uris/suites"
            )

        if self.ppa_url and not self.suites:
            raise ValueError("suites is required when ppa_url is provided")

        has_user = bool(self.auth_user)
        has_token_var = bool(self.auth_token_var)

        if has_user != has_token_var:
            raise ValueError(
                "Both auth_user and auth_token_var must be provided together"
            )

        has_key_server = bool(self.key_server)
        has_fingerprint = bool(self.fingerprint)

        if has_key_server and not has_fingerprint:
            raise ValueError(
                "fingerprint must be provided when key_server is set"
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
