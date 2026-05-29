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
    share_pct: float   # % relatif occupé dans le fill (somme = ~100%)
    color: str = "#888888"  # couleur hex du segment (issue du HTML)


@dataclass
class PeriodUsage:
    used_pct: float
    resets_at: str
    models: list[ModelUsage] = field(default_factory=list)


@dataclass
class UsageData:
    plan: str
    session: PeriodUsage
    weekly: PeriodUsage

    def to_dict(self) -> dict:
        def _period(p: PeriodUsage) -> dict:
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
        }


# --- HTTP ---

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


# --- Parsing ---

def _extract_plan(html: str) -> str:
    match = re.search(r'capitalize[^>]*>\s*(\w+)\s*</', html)
    if not match:
        raise ParseError("Could not extract plan from HTML.")
    return match.group(1).lower()


def _extract_percentages(html: str) -> tuple[float, float]:
    # Cible les aria-label des divs track : unique par période, insensible au
    # formatage multi-ligne des <span> et aux doublons introduits par le nouveau HTML.
    matches = re.findall(
        r'aria-label="(?:Session|Weekly) usage\s+([\d.]+)%\s*used"',
        html,
    )
    if len(matches) < 2:
        # Fallback sur les <span class="text-sm..."> (ancien HTML sans aria-label)
        matches = re.findall(
            r'<span[^>]*class="text-sm[^"]*"[^>]*>\s*([\d.]+)%\s*used[\s\S]*?</span',
            html,
        )
    if len(matches) < 2:
        raise ParseError(f"Expected 2 usage percentages, found {len(matches)}.")
    return float(matches[0]), float(matches[1])


def _extract_reset_times(html: str) -> tuple[str, str]:
    matches = re.findall(r'data-time="([^"]+)"', html)
    if len(matches) < 2:
        raise ParseError(f"Expected 2 reset timestamps, found {len(matches)}.")
    return matches[0], matches[1]


def _parse_fill_models(fill_html: str) -> list[ModelUsage]:
    """Extrait les ModelUsage depuis le contenu d'un div usage-meter__fill."""
    entries = re.findall(
        r'style="width:\s*([\d.]+)%;\s*background:\s*(#[0-9a-fA-F]{6})[^"]*"'
        r'[^>]*data-model="([^"]+)"[^>]*data-requests="(\d+)"',
        fill_html,
    )
    return [
        ModelUsage(model=model, requests=int(reqs), share_pct=float(share), color=color)
        for share, color, model, reqs in entries
    ]


def _extract_models_per_period(html: str) -> tuple[list[ModelUsage], list[ModelUsage]]:
    """Retourne (session_models, weekly_models) en splitant sur 'Weekly usage'."""
    parts = html.split("Weekly usage", 1)
    session_html = parts[0]
    weekly_html = parts[1] if len(parts) > 1 else ""

    def _models_from(fragment: str) -> list[ModelUsage]:
        entries = re.findall(
            r'style="width:\s*([\d.]+)%;\s*background:\s*(#[0-9a-fA-F]{6})[^"]*"'
            r'[^>]*data-model="([^"]+)"[^>]*data-requests="(\d+)"',
            fragment,
        )
        return [
            ModelUsage(model=model, requests=int(reqs), share_pct=float(share), color=color)
            for share, color, model, reqs in entries
        ]
    return _models_from(session_html), _models_from(weekly_html)


def parse_html(html: str) -> dict:
    """Parse the settings page HTML and return a usage dict."""
    _check_auth(html)
    plan = _extract_plan(html)
    session_pct, weekly_pct = _extract_percentages(html)
    session_time, weekly_time = _extract_reset_times(html)
    session_models, weekly_models = _extract_models_per_period(html)
    logger.debug("Parsing HTML...")
    logger.debug(
        "Parsed: plan=%s session=%.1f%% (%d models) weekly=%.1f%% (%d models)",
        plan, session_pct, len(session_models), weekly_pct, len(weekly_models),
    )
    return UsageData(
        plan=plan,
        session=PeriodUsage(used_pct=session_pct, resets_at=session_time, models=session_models),
        weekly=PeriodUsage(used_pct=weekly_pct, resets_at=weekly_time, models=weekly_models),
    ).to_dict()


# --- Public API ---

def get_usage(cookie: str) -> dict:
    """Fetch and return Ollama Cloud usage for the given session cookie."""
    html = _fetch_html(cookie)
    return parse_html(html)