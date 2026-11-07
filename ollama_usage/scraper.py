"""Fetch and parse Ollama Cloud usage from the ollama.com web pages.

Since 2026-11 the quota is shown on ``ollama.com/dashboard`` ("Free usage: N% left",
usage credits balance) without any reset date, and the settings page only holds a
cost report. That report (per-model requests and cost of the current month)
is loaded separately from ``/settings/usage/report`` and fills the per-model breakdown
and ``spend``. The previous page layout (one meter per period with its reset date) is
still recognised.
"""

from __future__ import annotations

import html as html_lib
import logging
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from ollama_usage.exceptions import AuthError, NetworkError, OllamaUsageError, ParseError

logger = logging.getLogger(__name__)

_DASHBOARD_URL = "https://ollama.com/dashboard"
_REPORT_URL = "https://ollama.com/settings/usage/report?scope=self"
_TIMEOUT = 10  # seconds
_SSL_CONTEXT = ssl.create_default_context()
_DEFAULT_COLOR = "#888888"


@dataclass
class ModelUsage:
    model: str
    requests: int
    share_pct: float | None  # share of the meter fill / of the month's cost (sums to ~100%)
    color: str = _DEFAULT_COLOR
    cost_usd: float | None = None


@dataclass
class PeriodUsage:
    used_pct: float
    resets_at: str | None
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
    spend: dict | None = None  # cost of the current month, from the usage report

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
                        "cost_usd": m.cost_usd,
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
            "spend": self.spend,
            "source": "web",
        }


def iter_periods(data: dict) -> list[tuple[str, dict]]:
    """Return the (key, period) pairs present in a usage dict, in display order."""
    return [(key, data[key]) for key in PERIOD_KEYS if data.get(key)]


def _fetch_html(cookie: str, url: str = _DASHBOARD_URL, *, fragment: bool = False) -> str:
    """Fetch an ollama.com page using the provided session cookie.

    ``fragment`` marks the request as coming from htmx, like the browser does for
    the parts of a page that are loaded afterwards (the usage report).
    """
    logger.debug("Fetching %s (cookie: ***)", url)
    headers = {
        "Cookie": f"__Secure-session={cookie}",
        "User-Agent": "Mozilla/5.0",
    }
    if fragment:
        headers["HX-Request"] = "true"
    req = urllib.request.Request(url, headers=headers)
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
        raise NetworkError(f"HTTP error {e.code} reaching {url}") from e
    except urllib.error.URLError as e:
        raise NetworkError(f"Failed to reach {url}: {e}") from e


# Only rendered for a signed-in user: the account menu of the settings/dashboard layout.
_SIGNED_IN_MARKER = 'id="settings-account-menu"'


def _check_auth(html: str) -> None:
    """Raise AuthError if the page redirected to login."""
    logger.debug("Checking auth...")
    if _SIGNED_IN_MARKER not in html and ("/login" in html or "sign in" in html.lower()):
        logger.debug("Auth check failed — redirected to login")
        raise AuthError("Cookie is invalid or expired — please refresh it.")
    logger.debug("Auth check passed")


def _text(fragment: str) -> str:
    """Visible text of an HTML fragment (tags removed, entities decoded, spaces collapsed)."""
    return " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


# --- dashboard (since 2026-11) -------------------------------------------------------

# <div class="text-sm">Free usage</div>
# <p id="dashboard-included" ...>72.5% <span ...>left</span></p>
_DASHBOARD_METER_RE = re.compile(
    r'>\s*([A-Za-z][\w -]*?)\s+usage\s*</div>\s*'
    r'<p[^>]*id="dashboard-included"[^>]*>\s*([\d.]+)\s*%\s*(?:<span[^>]*>)?\s*(left|used)?',
    re.IGNORECASE,
)


def _is_dashboard(html: str) -> bool:
    return 'id="dashboard-included"' in html


def _extract_dashboard_plan(html: str) -> str:
    """The plan is the meter label ("Free usage" → "free", "Pro usage" → "pro").

    It matches the plan the API reports, unlike the "Usage credits" badge next to the
    balance, which shows the billing mode ("Pay as you go").
    """
    meter = _DASHBOARD_METER_RE.search(html)
    if not meter:
        raise ParseError("Could not extract plan from the dashboard.")
    return " ".join(meter.group(1).split()).lower()


def _extract_dashboard_periods(html: str) -> dict[str, PeriodUsage]:
    """The dashboard shows the share of the quota LEFT, without any reset date."""
    match = _DASHBOARD_METER_RE.search(html)
    if not match:
        raise ParseError("Could not find the usage percentage on the dashboard "
                         "(expected '<plan> usage' followed by 'N% left').")
    label, pct, wording = match.groups()
    pct_value = float(pct)
    used = pct_value if (wording or "").lower() == "used" else round(100.0 - pct_value, 1)
    return {_period_key(label): PeriodUsage(used_pct=max(0.0, min(used, 100.0)), resets_at=None)}


# --- settings page (until 2026-11), still accepted as a fallback -----------------------

def _extract_plan(html: str) -> str:
    match = re.search(r'capitalize[^>]*>\s*(\w[\w -]*?)\s*</', html)
    if not match:
        raise ParseError("Could not extract plan from HTML.")
    return match.group(1).lower()


# e.g. aria-label="Free usage 12.5% used" (or Session / Weekly / Pro / Max...).
# Since 2026-10 the page words it "Free usage: 12.5%": colon and "used" are optional.
_METER_ARIA_RE = re.compile(
    r'aria-label="([A-Za-z][\w -]*?)\s+usage:?\s+([\d.]+)%(?:\s*used)?"',
    re.IGNORECASE,
)
# Fallback: <span>Free usage</span> <span>12.5% used</span> (or just "12.5%")
_METER_TEXT_RE = re.compile(
    r'>\s*([A-Za-z][\w -]*?)\s+usage\s*</span\s*>\s*<span[^>]*>\s*([\d.]+)%(?:\s*used)?',
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
        raise ParseError("Could not find any usage percentages (expected '<plan> usage N%').")

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


# --- usage report (/settings/usage/report, since 2026-11) ------------------------------

_TOTAL_COST_RE = re.compile(r'<dt[^>]*>\s*Total cost\s*</dt>\s*<dd[^>]*>(.*?)</dd>', re.S | re.I)
_MODEL_TABLE_RE = re.compile(r'id="usage-by-model".*?<tbody[^>]*>(.*?)</tbody>', re.S)
_ROW_RE = re.compile(r'<tr\b[^>]*>(.*?)</tr>', re.S)
_CELL_RE = re.compile(r'<td\b[^>]*>(.*?)</td>', re.S)
# Chart legend: <i ... style="background: #34c759"></i>gpt-oss:120b</span>
_LEGEND_RE = re.compile(
    r'<i\b[^>]*style="background:\s*(#[0-9a-fA-F]{3,8})[^"]*"[^>]*>\s*</i>\s*([^<]+?)\s*<'
)
_FETCHED_AT_RE = re.compile(r'data-usage-fetched[^>]*>.*?<time[^>]*datetime="([^"]+)"', re.S)
_MONEY_RE = re.compile(r'(-?)\$\s*([\d,]+(?:\.\d+)?)')


def _parse_money(text: str) -> float:
    """'$1,234.50' → 1234.5; '<$0.01' (an amount too small to show) → 0.0."""
    text = _text(text)
    if text.startswith("<"):
        return 0.0
    match = _MONEY_RE.search(text)
    if not match:
        raise ParseError(f"Could not read the amount {text!r} in the usage report.")
    sign, amount = match.groups()
    return float(sign + amount.replace(",", ""))


def _parse_count(text: str) -> int:
    text = _text(text).replace(",", "")
    if not text.isdigit():
        raise ParseError(f"Could not read the request count {text!r} in the usage report.")
    return int(text)


def _parse_report_models(report_html: str) -> list[ModelUsage]:
    table = _MODEL_TABLE_RE.search(report_html)
    if not table:
        return []  # nothing used this month yet
    colors = {_text(name): color for color, name in _LEGEND_RE.findall(report_html)}
    models: list[ModelUsage] = []
    for row in _ROW_RE.findall(table.group(1)):
        cells = _CELL_RE.findall(row)
        if len(cells) < 3:
            continue  # placeholder row
        name = _text(cells[0])
        models.append(ModelUsage(
            model=name,
            requests=_parse_count(cells[1]),
            share_pct=None,
            color=colors.get(name, _DEFAULT_COLOR),
            cost_usd=_parse_money(cells[-1]),
        ))
    total = sum(m.cost_usd or 0.0 for m in models)
    if total > 0:
        for m in models:
            m.share_pct = round((m.cost_usd or 0.0) * 100.0 / total, 1)
    return models


def _parse_report_spend(report_html: str) -> dict:
    match = _TOTAL_COST_RE.search(report_html)
    if not match:
        raise ParseError("Could not find 'Total cost' in the usage report.")
    fetched = _FETCHED_AT_RE.search(report_html)
    ending_at = fetched.group(1) if fetched else None
    starting_at = None
    if ending_at and re.match(r"\d{4}-\d{2}-", ending_at):
        starting_at = f"{ending_at[:7]}-01T00:00:00Z"  # the report covers the UTC month
    return {
        "cost_usd": _parse_money(match.group(1)),
        "period": "current_month",
        "starting_at": starting_at,
        "ending_at": ending_at,
    }


def parse_report(report_html: str) -> tuple[list[ModelUsage], dict]:
    """Parse the usage report fragment: (per-model usage of the month, spend of the month)."""
    _check_auth(report_html)
    spend = _parse_report_spend(report_html)
    return _parse_report_models(report_html), spend


# --- entry points ---------------------------------------------------------------------

def parse_html(html: str, report_html: str | None = None) -> dict:
    """Parse the dashboard HTML (and optionally the usage report) into a usage dict.

    The page of the previous layout (settings page with one meter per period) is
    still accepted. Periods absent from the page (e.g. session/weekly on credit-based
    plans) are returned as None. The report, when given and readable, fills the
    per-model breakdown of the monthly quota and ``spend``; an unreadable report is
    ignored so that the quota is still returned.
    """
    _check_auth(html)
    logger.debug("Parsing HTML...")
    if _is_dashboard(html):
        plan = _extract_dashboard_plan(html)
        periods = _extract_dashboard_periods(html)
    else:
        plan = _extract_plan(html)
        periods = _extract_periods(html)
    credits_balance = _extract_credits_balance(html)

    spend = None
    if report_html is not None:
        try:
            models, spend = parse_report(report_html)
        except (AuthError, ParseError) as e:
            logger.debug("Ignoring unreadable usage report: %s", e)
        else:
            monthly = periods.get("monthly")
            if monthly is not None and not monthly.models:
                monthly.models = models

    logger.debug(
        "Parsed: plan=%s periods=%s credits=%s spend=%s",
        plan,
        ", ".join(f"{k}={p.used_pct:.1f}% ({len(p.models)} models)" for k, p in periods.items()),
        credits_balance,
        spend and spend["cost_usd"],
    )
    return UsageData(plan=plan, credits_balance=credits_balance, spend=spend, **periods).to_dict()


def get_usage(cookie: str) -> dict:
    """Fetch and return Ollama Cloud usage for the given session cookie."""
    html = _fetch_html(cookie, _DASHBOARD_URL)
    report_html = None
    if _is_dashboard(html):
        try:
            report_html = _fetch_html(cookie, _REPORT_URL, fragment=True)
        except OllamaUsageError as e:  # the quota is on the dashboard, the report is extra
            logger.debug("Usage report unavailable, per-model breakdown skipped: %s", e)
    return parse_html(html, report_html)
