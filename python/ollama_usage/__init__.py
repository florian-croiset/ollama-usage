"""Read your Ollama Cloud quota, credits and per-model usage from the official API.

Example:
    >>> import os
    >>> from ollama_usage import Client
    >>> report = Client(os.environ["OLLAMA_API_KEY"]).fetch()
    >>> report.windows.monthly.used_pct
    12.5

A fetch fails only when the key is rejected, when ollama.com rate-limits it, or
when both documented endpoints fail. If only one of them answers, the report is
partial: the missing part is ``None`` and ``report.warnings`` says why.
"""

from ._client import Client
from ._errors import ApiError, AuthError, NetworkError, OllamaUsageError, RateLimitedError
from ._ollama_usage import SCHEMA_VERSION, __version__
from ._report import (
    Credits,
    IncludedCredits,
    ModelUsage,
    OtherUsage,
    Range,
    Report,
    ReportWarning,
    Usage,
    Window,
    Windows,
)

__all__ = [
    "SCHEMA_VERSION",
    "ApiError",
    "AuthError",
    "Client",
    "Credits",
    "IncludedCredits",
    "ModelUsage",
    "NetworkError",
    "OllamaUsageError",
    "OtherUsage",
    "Range",
    "RateLimitedError",
    "Report",
    "ReportWarning",
    "Usage",
    "Window",
    "Windows",
    "__version__",
]
