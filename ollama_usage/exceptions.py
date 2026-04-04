"""Custom exceptions for ollama-usage."""


class OllamaUsageError(Exception):
    """Base exception for ollama-usage."""


class AuthError(OllamaUsageError):
    """Raised when the session cookie is invalid or expired."""


class ParseError(OllamaUsageError):
    """Raised when the HTML structure is unexpected or incomplete."""


class NetworkError(OllamaUsageError):
    """Raised when a network request fails."""


class BrowserNotFoundError(OllamaUsageError):
    """Raised when a browser profile or cookie store cannot be located."""


class UnsupportedOSError(OllamaUsageError):
    """Raised when the current OS is not supported for a given browser."""