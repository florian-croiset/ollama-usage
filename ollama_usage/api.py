"""Fetch Ollama Cloud usage from the official ollama.com/api/usage endpoint.

Authenticated with an ollama.com API key (https://ollama.com/settings/keys).
Unlike the settings page, the API does not expose the plan name, reset dates,
per-model share of the meter or the usage credits balance — those fields are
returned as None.

Since 2026-10-07 the endpoint no longer reports a quota percentage at all: it
returns the spend over the last days (``range``, ``totals``, ``buckets``). The
periods of the usage dict are then None and only ``spend`` is filled; use
:func:`get_usage_with_fallback` to get the percentage from the settings page.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

from ollama_usage.exceptions import AuthError, NetworkError, ParseError
from ollama_usage.scraper import _SSL_CONTEXT, _TIMEOUT, PERIOD_KEYS

logger = logging.getLogger(__name__)

_USAGE_API_URL = "https://ollama.com/api/usage"
_API_KEY_ENV = "OLLAMA_API_KEY"


def get_api_key_env() -> str | None:
    """Return the API key from the OLLAMA_API_KEY environment variable, if set."""
    value = os.environ.get(_API_KEY_ENV, "").strip()
    return value or None


def _fetch_json(api_key: str) -> dict:
    """GET /api/usage with the API key and return the decoded JSON body."""
    logger.debug("Fetching %s (api key: ***)", _USAGE_API_URL)
    req = urllib.request.Request(
        _USAGE_API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "ollama-usage",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_SSL_CONTEXT) as response:
            raw = response.read()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise AuthError(
                f"Access denied (HTTP {e.code}) — API key is invalid or revoked."
            ) from e
        raise NetworkError(f"HTTP error {e.code} reaching {_USAGE_API_URL}") from e
    except urllib.error.URLError as e:
        raise NetworkError(f"Failed to reach {_USAGE_API_URL}: {e}") from e

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ParseError(f"Usage API returned invalid JSON: {e}") from e
    if not isinstance(payload, dict):
        raise ParseError("Usage API returned an unexpected payload (not a JSON object).")
    return payload


def _parse_models(raw) -> list[dict]:
    """Accept both the list form [{"name", "request_count"}] and the dict form {name: {...}}."""
    if isinstance(raw, dict):
        items = [{"name": name, **(info if isinstance(info, dict) else {})} for name, info in raw.items()]
    elif isinstance(raw, list):
        items = [item for item in raw if isinstance(item, dict)]
    else:
        return []
    return [
        {
            "model": str(item.get("name", "")),
            "requests": int(item.get("request_count") or 0),
            "share_pct": None,
            "color": None,
        }
        for item in items
        if item.get("name")
    ]


def _parse_period(raw) -> dict | None:
    if not isinstance(raw, dict) or "usage" not in raw:
        return None
    try:
        fraction = float(raw["usage"])
    except (TypeError, ValueError) as e:
        raise ParseError(f"Invalid usage fraction in API response: {raw['usage']!r}") from e
    return {
        "used_pct": round(fraction * 100, 1),
        "resets_at": None,
        "models": _parse_models(raw.get("models")),
    }


def _parse_spend(raw) -> dict | None:
    if not isinstance(raw, dict) or raw.get("cost") is None:
        return None
    try:
        cost = float(raw["cost"])
    except (TypeError, ValueError):
        return None
    period = raw.get("period")
    if not isinstance(period, dict):
        period = {}
    return {
        "cost_usd": cost,
        "period": period.get("type"),
        "starting_at": period.get("starting_at"),
        "ending_at": period.get("ending_at"),
    }


def _parse_totals_spend(payload: dict) -> dict | None:
    """Spend from the time-series layout: totals.usage_usd over [from, until]."""
    totals = payload.get("totals")
    if not isinstance(totals, dict) or totals.get("usage_usd") is None:
        return None
    try:
        cost = float(totals["usage_usd"])
    except (TypeError, ValueError):
        return None
    return {
        "cost_usd": cost,
        "period": payload.get("range"),
        "starting_at": payload.get("from"),
        "ending_at": payload.get("until"),
    }


def parse_api_response(payload: dict) -> dict:
    """Convert an /api/usage JSON payload into the usage dict returned by get_usage()."""
    limits = payload.get("limits")
    if not isinstance(limits, dict):
        if not isinstance(payload.get("totals"), dict):
            raise ParseError("Usage API response has no 'limits' object.")
        limits = {}  # time-series layout: spend only, no quota percentage
    data = {
        "plan": None,
        **{key: _parse_period(limits.get(key)) for key in PERIOD_KEYS},
        "credits_balance": None,
        "spend": _parse_spend(payload.get("activity")) or _parse_totals_spend(payload),
        "source": "api",
    }
    logger.debug(
        "Parsed API: %s",
        ", ".join(f"{k}={data[k]['used_pct']}%" for k in PERIOD_KEYS if data[k]) or "no limits",
    )
    return data


def get_usage_api(api_key: str) -> dict:
    """Fetch and return Ollama Cloud usage using the official API and an API key."""
    return parse_api_response(_fetch_json(api_key))


def get_usage_with_fallback(api_key: str, cookie: str | None = None) -> dict:
    """Usage from the API, completed from the settings page when the API has no quota.

    The API alone no longer gives a percentage (see the module docstring). When it
    returns none and a session cookie is available — the one passed in, or the one
    found in a browser — the settings page supplies the quota and the API's spend
    is kept. Without any cookie the API-only result is returned unchanged.
    """
    from ollama_usage.cookie import get_cookie_auto, get_cookie_env
    from ollama_usage.exceptions import OllamaUsageError
    from ollama_usage.scraper import get_usage, iter_periods

    data = get_usage_api(api_key)
    if iter_periods(data):
        return data
    if not cookie:
        try:
            cookie = get_cookie_env() or get_cookie_auto()
        except OllamaUsageError:
            logger.debug("No session cookie available to complete the API result")
            return data
    logger.debug("API reported no quota — reading it from the settings page")
    web = get_usage(cookie)
    web["spend"] = data["spend"]
    return web
