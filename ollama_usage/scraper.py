"""Fetch and parse Ollama Cloud usage from ollama.com/settings."""

from __future__ import annotations

import logging
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from ollama_usage.exceptions import AuthError, NetworkError, ParseError

logger = logging.getLogger(__name__)

_SETTINGS_URL = "https://ollama.com/settings"
_TIMEOUT = 10  # seconds
_SSL_CONTEXT = ssl.create_default_context()


@dataclass
class ModelUsage:
    model: str
    requests: int
    share_pct: float   # share of the meter fill (sums to ~100%)
    color: str = "#888888"


@dataclass
class PeriodUsage:
    used_pct: float
    resets_at: str
    models: list[ModelUsage] = field(default_factory=list)


# session/weekly: legacy Pro/Max subscriptions; monthly: credit-based plans (since 2026-08-31).
PERIOD_KEYS = ("session", "weekly", "monthly")


@dataclass
class UsageData:
    plan: str
    session: PeriodUsage | None = None
    weekly: PeriodUsage | None = None
    monthly: PeriodUsage | None = None
    credits_balance: float | None = None  # USD

    def to_dict(self) -> dict:
        def _period(p: PeriodUsage | None) -> dict | None:
            if p is None:
                return None
            return {
                "used_pct": p.used_pct,
                "resets_at": p.resets_at,
                "models": [
                    {
                        "model": m.model,
                        "requests": m.requests,
                        "share_pct": m.share_pct,
                        "color": m.color,
                    }
                    for m in p.models
                ],
            }

        return {
            "plan": self.plan,
            "session": _period(self.session),
            "weekly": _period(self.weekly),
            "monthly": _period(self.monthly),
            "credits_balance": self.credits_balance,
            "spend": None,  # API only
            "source": "web",
        }


def iter_periods(data: dict) -> list[tuple[str, dict]]:
    """Return the (key, period) pairs present in a usage dict, in display order."""
    return [(key, data[key]) for key in PERIOD_KEYS if data.get(key)]


def _fetch_html(cookie: str) -> str:
    """Fetch the settings page HTML using the provided session cookie."""
    logger.debug("Fetching %s (cookie: ***)", _SETTINGS_URL)
    req = urllib.request.Request(
        _SETTINGS_URL,
        headers={
            "Cookie": f"__Secure-session={cookie}",
            "User-Agent": "Mozilla/5.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_SSL_CONTEXT) as response:
            raw = response.read()
            try:
                html = raw.decode("utf-8")
            except UnicodeDecodeError as e:
                raise ParseError(f"Response is not valid UTF-8: {e}") from e
            logger.debug("Response received (%d chars)", len(html))
            return html
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise AuthError(
                f"Access denied (HTTP {e.code}) — cookie is invalid or expired."
            ) from e
        raise NetworkError(f"HTTP error {e.code} reaching {_SETTINGS_URL}") from e
    except urllib.error.URLError as e:
        raise NetworkError(f"Failed to reach {_SETTINGS_URL}: {e}") from e


def _check_auth(html: str) -> None:
    """Raise AuthError if the page redirected to login."""
    logger.debug("Checking auth...")
    if "/login" in html or "sign in" in html.lower():
        logger.debug("Auth check failed — redirected to login")
        raise AuthError("Cookie is invalid or expired — please refresh it.")
    logger.debug("Auth check passed")


def _extract_plan(html: str) -> str:
    match = re.search(r'capitalize[^>]*>\s*(\w[\w -]*?)\s*</', html)
    if not match:
        raise ParseError("Could not extract plan from HTML.")
    return match.group(1).lower()


# e.g. aria-label="Free usage 12.5% used" (or Session / Weekly / Pro / Max...)
_METER_ARIA_RE = re.compile(
    r'aria-label="([A-Za-z][\w -]*?)\s+usage\s+([\d.]+)%\s*used"',
    re.IGNORECASE,
)
# Fallback: <span>Free usage</span> <span>12.5% used</span>
_METER_TEXT_RE = re.compile(
    r'>\s*([A-Za-z][\w -]*?)\s+usage\s*</span\s*>\s*<span[^>]*>\s*([\d.]+)%\s*used',
    re.IGNORECASE,
)
_RESET_TIME_RE = re.compile(r'data-time="([^"]+)"')
_CREDITS_RE = re.compile(
    r'id="extra-usage-balance"[^>]*>\s*(-?)\s*\$\s*(-?[\d,]+(?:\.\d+)?)'
)


def _period_key(label: str) -> str:
    """Map a meter label to a period key ('Free', 'Pro', 'Max'... → monthly)."""
    label = label.strip().lower()
    if label == "session":
        return "session"
    if label == "weekly":
        return "weekly"
    return "monthly"


def _extract_periods(html: str) -> dict[str, PeriodUsage]:
    """Split the page by meter and extract the %, reset date and breakdown of each one."""
    matches = list(_METER_ARIA_RE.finditer(html)) or list(_METER_TEXT_RE.finditer(html))
    if not matches:
        raise ParseError("Could not find any usage percentages (expected '<plan> usage N% used').")

    periods: dict[str, PeriodUsage] = {}
    for i, match in enumerate(matches):
        label, pct = match.group(1), match.group(2)
        key = _period_key(label)
        if key in periods:
            continue
        end = matches[i + 1].start() if i + 1 < len(matches) else len(html)
        chunk = html[match.end():end]
        reset = _RESET_TIME_RE.search(chunk)
        if not reset:
            raise ParseError(f"Could not find reset timestamp for '{label} usage'.")
        periods[key] = PeriodUsage(
            used_pct=float(pct),
            resets_at=reset.group(1),
            models=_parse_fill_models(chunk[:reset.start()]),
        )
    return periods


def _extract_credits_balance(html: str) -> float | None:
    match = _CREDITS_RE.search(html)
    if not match:
        return None
    sign, amount = match.groups()
    return float(sign + amount.replace(",", ""))


def _parse_fill_models(fill_html: str) -> list[ModelUsage]:
    """Extract ModelUsage entries from an HTML fragment (fill segments)."""
    entries = re.findall(
        r'style="width:\s*([\d.]+)%;\s*background:\s*(#[0-9a-fA-F]{6})[^"]*"'
        r'[^>]*data-model="([^"]+)"[^>]*data-requests="(\d+)"',
        fill_html,
    )
    return [
        ModelUsage(model=model, requests=int(reqs), share_pct=float(share), color=color)
        for share, color, model, reqs in entries
    ]


def parse_html(html: str) -> dict:
    """Parse the settings page HTML and return a usage dict.

    Periods absent from the page (e.g. session/weekly on credit-based plans,
    monthly on legacy Pro/Max subscriptions) are returned as None.
    """
    _check_auth(html)
    logger.debug("Parsing HTML...")
    plan = _extract_plan(html)
    periods = _extract_periods(html)
    credits_balance = _extract_credits_balance(html)
    logger.debug(
        "Parsed: plan=%s periods=%s credits=%s",
        plan,
        ", ".join(f"{k}={p.used_pct:.1f}% ({len(p.models)} models)" for k, p in periods.items()),
        credits_balance,
    )
    return UsageData(plan=plan, credits_balance=credits_balance, **periods).to_dict()


def get_usage(cookie: str) -> dict:
    """Fetch and return Ollama Cloud usage for the given session cookie."""
    html = _fetch_html(cookie)
    return parse_html(html)