import enum

class SnapCommandError(Exception):
    def __init__(self, command):
        super().__init__(f"failed to executed '{command}'")


class SshCommandError(Exception):
    def __init__(self, command):
        super().__init__(f"failed to executed '{command}'")


class ExitCode(enum.IntEnum):
    Success = 0
    SSH_AUTH_Failed = 10
    SSH_AUTH_REQUIRED_PASSWORD_PASSPHRASE = 11
    SSH_AUTH_INVALID_USERNAME_PASSWORD = 12
    Action_Failed = 20
