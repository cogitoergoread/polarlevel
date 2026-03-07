"""CLI process exit codes."""

from enum import IntEnum


class ExitCode(IntEnum):
    """Standardized process exit codes for the CLI."""

    SUCCESS = 0
    UNEXPECTED_ERROR = 1
    INVALID_ARGUMENTS = 2
    AUTHENTICATION_FAILURE = 3
    API_FAILURE = 4
    OUTPUT_FAILURE = 5
