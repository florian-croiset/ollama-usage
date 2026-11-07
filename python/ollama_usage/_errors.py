"""Exceptions raised by `Client`."""

from __future__ import annotations


class OllamaUsageError(Exception):
    """Base class for the errors this package raises."""


class AuthError(OllamaUsageError):
    """The API key is missing or was rejected, or the account is suspended."""


class RateLimitedError(OllamaUsageError):
    """ollama.com rate-limited the key.

    The API allows 10 requests per minute per user, shared by every key and device.

    Attributes:
        retry_after: Seconds ollama.com asked to wait, or ``None`` if it did not say.
    """

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class NetworkError(OllamaUsageError):
    """Neither endpoint could be reached."""


class ApiError(OllamaUsageError):
    """Both endpoints answered with an error or an unreadable response."""


def from_native(kind: str, message: str, retry_after: float | None) -> OllamaUsageError:
    """Builds the exception for a failure reported by the native module."""
    if kind == "auth":
        return AuthError(message)
    if kind == "rate_limited":
        return RateLimitedError(message, retry_after)
    if kind == "network":
        return NetworkError(message)
    return ApiError(message)
