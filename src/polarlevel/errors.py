"""Custom error types used by polarlevel."""

from .exit_codes import ExitCode


class PolarLevelError(Exception):
    """Base application error that carries an exit code."""

    exit_code = ExitCode.UNEXPECTED_ERROR


class InvalidArgumentsError(PolarLevelError):
    """Raised when CLI argument combinations are invalid."""

    exit_code = ExitCode.INVALID_ARGUMENTS


class AuthenticationError(PolarLevelError):
    """Raised when required auth configuration is missing or invalid."""

    exit_code = ExitCode.AUTHENTICATION_FAILURE


class ApiError(PolarLevelError):
    """Raised for API/network failures after retry logic."""

    exit_code = ExitCode.API_FAILURE


class OutputWriteError(PolarLevelError):
    """Raised when serialization or output file writing fails."""

    exit_code = ExitCode.OUTPUT_FAILURE
