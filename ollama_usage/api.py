"""Fetch Ollama Cloud usage from the official ollama.com API endpoints.

Authenticated with an ollama.com API key (https://ollama.com/settings/keys).
Two documented endpoints are combined:

- ``/api/balance`` (https://docs.ollama.com/api/balance): the included credits of
  the plan for the current period (balance, allowance, ``period.until`` = when they
  refill) and the purchased credits balance; ``included.session`` / ``.weekly`` with
  ``remaining_percent`` and ``resets_at`` on legacy plans. It gives the quota.
- ``/api/usage`` (https://docs.ollama.com/api/cloud-usage): requests and value in
  USD over the last 30 days, grouped by model. It gives ``spend`` and the per-model
  breakdown.

The plan name comes from ``/api/me`` (undocumented, best effort): it is called once
and cached in memory for 24 hours (1 hour after a failure), and ``plan`` is None
when it can't be read. Only its ``Plan`` field is kept; the rest of the response
(e-mail, name...) is neither stored nor logged.

Since 2026-10-07 ``/api/usage`` alone reports no quota; when ``/api/balance`` can't
be read either, :func:`get_usage_with_fallback` reads the percentage from the dashboard.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import urllib.error
import urllib.request

from ollama_usage.exceptions import AuthError, NetworkError, OllamaUsageError, ParseError
from ollama_usage.scraper import _SSL_CONTEXT, _TIMEOUT, PERIOD_KEYS

logger = logging.getLogger(__name__)

_USAGE_API_URL = "https://ollama.com/api/usage"
# 30 days: the reporting window closest to the monthly quota period (24h / 7d / 30d).
_USAGE_QUERY_URL = _USAGE_API_URL + "?range=30d&group_by=model"
_BALANCE_API_URL = "https://ollama.com/api/balance"
_ME_API_URL = "https://ollama.com/api/me"  # undocumented, POST only
_PLAN_TTL = 24 * 3600     # seconds a plan name is reused
_PLAN_RETRY = 3600        # seconds before retrying after a failure
# sha256(api key) -> (monotonic expiry, plan name or None)
_plan_cache: dict[str, tuple[float, str | None]] = {}
_API_KEY_ENV = "OLLAMA_API_KEY"


def get_api_key_env() -> str | None:
    """Return the API key from the OLLAMA_API_KEY environment variable, if set."""
    value = os.environ.get(_API_KEY_ENV, "").strip()
    return value or None


def _fetch_json(api_key: str, url: str = _USAGE_API_URL, method: str = "GET") -> dict:
    """Call an API endpoint with the API key and return the decoded JSON body."""
    logger.debug("Fetching %s (api key: ***)", url)
    req = urllib.request.Request(
        url,
        data=b"" if method == "POST" else None,
        method=method,
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
        raise NetworkError(f"HTTP error {e.code} reaching {url}") from e
    except urllib.error.URLError as e:
        raise NetworkError(f"Failed to reach {url}: {e}") from e

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ParseError(f"API returned invalid JSON ({url}): {e}") from e
    if not isinstance(payload, dict):
        raise ParseError(f"API returned an unexpected payload (not a JSON object) at {url}.")
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
            "cost_usd": None,
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


def _to_float(value) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _parse_groups(payload: dict) -> list[dict]:
    """Per-model usage from ``totals.groups`` (``group_by=model``), ranked by cost."""
    totals = payload.get("totals")
    groups = totals.get("groups") if isinstance(totals, dict) else None
    if not isinstance(groups, list):
        return []
    models = []
    for group in groups:
        if not isinstance(group, dict) or not group.get("model"):
            continue
        models.append({
            "model": str(group["model"]),
            "requests": _to_int(group.get("request_count")),
            "share_pct": None,
            "color": None,
            "cost_usd": _to_float(group.get("usage_usd")),
        })
    total = _to_float(totals.get("usage_usd")) or sum(m["cost_usd"] or 0.0 for m in models)
    if total and total > 0:  # legacy-plan requests have no cost: no share then
        for m in models:
            m["share_pct"] = round((m["cost_usd"] or 0.0) * 100.0 / total, 1)
    return models


def _period_until(raw) -> str | None:
    period = raw.get("period") if isinstance(raw, dict) else None
    return period.get("until") if isinstance(period, dict) else None


def parse_balance_response(payload: dict) -> dict:
    """Convert an /api/balance JSON payload into quota periods and the credits balance.

    Returns ``{"session", "weekly", "monthly", "credits_balance"}``. On credit-based
    plans the monthly ``used_pct`` is the share of the included credits spent and
    ``resets_at`` is when they refill (``included.period.until``); a plan without
    included credits has no monthly quota. Legacy plans report session / weekly.
    """
    included = payload.get("included")
    purchased = payload.get("purchased")
    if not isinstance(included, dict) and not isinstance(purchased, dict):
        raise ParseError("Balance API response has neither 'included' nor 'purchased'.")
    included = included if isinstance(included, dict) else {}

    periods: dict[str, dict | None] = {key: None for key in PERIOD_KEYS}
    for key in ("session", "weekly"):
        raw = included.get(key)
        remaining = _to_float(raw.get("remaining_percent")) if isinstance(raw, dict) else None
        if remaining is not None:
            periods[key] = {
                "used_pct": round(min(max(100.0 - remaining, 0.0), 100.0), 1),
                "resets_at": raw.get("resets_at"),
                "models": [],
            }

    allowance = _to_float(included.get("allowance_usd"))
    balance = _to_float(included.get("balance_usd"))
    if allowance and allowance > 0 and balance is not None:
        used = (allowance - balance) * 100.0 / allowance
        periods["monthly"] = {
            "used_pct": round(min(max(used, 0.0), 100.0), 1),
            "resets_at": _period_until(included),
            "models": [],
        }

    credits = _to_float(purchased.get("balance_usd")) if isinstance(purchased, dict) else None
    return {**periods, "credits_balance": credits}


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
    models = _parse_groups(payload)
    if models:
        data["models"] = models  # attached to the monthly quota by get_usage_api()
    logger.debug(
        "Parsed API: %s",
        ", ".join(f"{k}={data[k]['used_pct']}%" for k in PERIOD_KEYS if data[k]) or "no limits",
    )
    return data


def _get_plan(api_key: str) -> str | None:
    """Plan name from /api/me ("free", "pro"...), cached per key; None if unavailable."""
    cache_key = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    now = time.monotonic()
    cached = _plan_cache.get(cache_key)
    if cached is not None and cached[0] > now:
        return cached[1]

    plan = None
    try:
        raw = _fetch_json(api_key, _ME_API_URL, method="POST").get("Plan")
    except OllamaUsageError as e:
        # Never log the body: it holds the account's e-mail and name.
        logger.debug("Plan unavailable from %s (%s)", _ME_API_URL, type(e).__name__)
    else:
        if isinstance(raw, str) and raw.strip():
            plan = " ".join(raw.split()).lower()
    _plan_cache[cache_key] = (now + (_PLAN_TTL if plan else _PLAN_RETRY), plan)
    return plan


def _empty_api_data() -> dict:
    return {"plan": None, **{key: None for key in PERIOD_KEYS},
            "credits_balance": None, "spend": None, "source": "api"}


def _merge_balance(data: dict, balance: dict) -> None:
    """Put the quota from /api/balance into the /api/usage result (in place)."""
    models = data.get("models", [])
    for key in PERIOD_KEYS:
        period = balance.get(key)
        if period is None:
            continue
        previous = data.get(key)
        if previous and previous.get("models"):
            period["models"] = previous["models"]
        elif key == "monthly":
            period["models"] = models
        data[key] = period
    if balance.get("credits_balance") is not None:
        data["credits_balance"] = balance["credits_balance"]


def get_usage_api(api_key: str) -> dict:
    """Fetch and return Ollama Cloud usage using the official API and an API key.

    The quota comes from /api/balance, the spend and per-model breakdown from
    /api/usage. If one of them can't be read the other one is still returned; an
    invalid key (AuthError) or both failing raises. The plan name comes from the
    cached /api/me call and is None when it can't be read.
    """
    errors: list[Exception] = []

    def _try(url, parse):
        try:
            return parse(_fetch_json(api_key, url))
        except AuthError:
            raise
        except (NetworkError, ParseError) as e:
            logger.debug("Could not read %s: %s", url, e)
            errors.append(e)
            return None

    data = _try(_USAGE_QUERY_URL, parse_api_response)
    balance = _try(_BALANCE_API_URL, parse_balance_response)
    if data is None and balance is None:
        raise errors[0]
    data = data or _empty_api_data()
    if balance is not None:
        _merge_balance(data, balance)
    data.pop("models", None)
    data["plan"] = _get_plan(api_key)
    return data


def get_usage_with_fallback(api_key: str, cookie: str | None = None) -> dict:
    """Usage from the API, completed from the dashboard when the API has no quota.

    The API alone no longer gives a percentage (see the module docstring). When it
    returns none and a session cookie is available — the one passed in, or the one
    found in a browser — the dashboard supplies the quota and the API's spend is
    kept (the month's spend from the web report is used when the API has none).
    Without any cookie the API-only result is returned unchanged.
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
    logger.debug("API reported no quota — reading it from the dashboard")
    web = get_usage(cookie)
    web["spend"] = data["spend"] or web.get("spend")
    return web
