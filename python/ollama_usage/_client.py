"""The client."""

from __future__ import annotations

import json

from ._errors import AuthError, from_native
from ._ollama_usage import Client as NativeClient
from ._ollama_usage import FetchError
from ._report import Range, Report

_KEYS_URL = "https://ollama.com/settings/keys"


class Client:
    """A client for one API key.

    Building one does no I/O. Each `fetch` makes two requests, plus a third to
    ``/api/me`` the first time and then once a day, so reuse the client when
    polling: the API allows 10 requests per minute per user.

    Args:
        api_key: A key from https://ollama.com/settings/keys.
        timeout: Seconds after which each request gives up.

    Raises:
        AuthError: If ``api_key`` is empty.
        ValueError: If ``timeout`` is not a positive number.
    """

    __slots__ = ("_native",)

    def __init__(self, api_key: str, *, timeout: float = 10.0) -> None:
        key = api_key.strip()
        if not key:
            raise AuthError(f"an API key is required: create one at {_KEYS_URL}")
        self._native = NativeClient(key, timeout)

    def fetch(self, range: Range = "30d") -> Report:
        """Fetches the quota, the credits, the usage over ``range`` and the plan name.

        The GIL is released while waiting for ollama.com.

        Args:
            range: Period covered by the usage: ``"24h"``, ``"7d"`` or ``"30d"``.

        Returns:
            The report, possibly partial; see `Report.is_partial`.

        Raises:
            AuthError: If the key is rejected.
            RateLimitedError: If ollama.com rate-limits the key.
            NetworkError: If neither endpoint can be reached.
            ApiError: If both endpoints fail otherwise.
            ValueError: If ``range`` is not one of the accepted values.
        """
        try:
            payload = self._native.fetch_json(range)
        except FetchError as error:
            raise from_native(*error.args) from None
        return Report.from_dict(json.loads(payload))

    def __repr__(self) -> str:
        return "Client(api_key=<redacted>)"
