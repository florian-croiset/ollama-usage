"""Tests for ollama_usage.scraper."""

from __future__ import annotations

import pytest

from ollama_usage.exceptions import AuthError, ParseError
from ollama_usage.scraper import parse_html


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_html(
    plan: str = "free",
    session_pct: float = 0.0,
    session_time: str = "2026-04-04T17:00:00Z",
    weekly_pct: float = 27.9,
    weekly_time: str = "2026-04-06T00:00:00Z",
) -> str:
    """Build a minimal but realistic settings page HTML fragment."""
    return f"""
    <span class="capitalize">{plan}</span>
    <span class="text-sm">Session usage</span>
    <span class="text-sm">{session_pct}% used</span>
    <div class="local-time" data-time="{session_time}">Resets soon</div>
    <span class="text-sm">Weekly usage</span>
    <span class="text-sm">{weekly_pct}% used</span>
    <div class="local-time" data-time="{weekly_time}">Resets soon</div>
    """


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def free_html() -> str:
    return make_html()


@pytest.fixture
def pro_html() -> str:
    return make_html(plan="pro", session_pct=45.0, weekly_pct=60.0)


@pytest.fixture
def max_html() -> str:
    return make_html(plan="max", session_pct=99.9, weekly_pct=100.0)


@pytest.fixture
def full_usage_html() -> str:
    return make_html(
        plan="pro",
        session_pct=45.0,
        session_time="2026-04-05T10:00:00Z",
        weekly_pct=80.0,
        weekly_time="2026-04-07T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------

class TestPlan:

    @pytest.mark.parametrize("plan", ["free", "pro", "max"])
    def test_known_plans(self, plan: str) -> None:
        assert parse_html(make_html(plan=plan))["plan"] == plan

    def test_plan_is_lowercase(self) -> None:
        # Ollama may render "Free" or "FREE" — we always return lowercase
        html = make_html(plan="FREE")
        assert parse_html(html)["plan"] == "free"

    def test_plan_present_in_output(self, free_html: str) -> None:
        assert "plan" in parse_html(free_html)


# ---------------------------------------------------------------------------
# Session usage
# ---------------------------------------------------------------------------

class TestSessionUsage:

    @pytest.mark.parametrize("pct", [0.0, 1.5, 27.9, 50.0, 99.9, 100.0])
    def test_session_pct_values(self, pct: float) -> None:
        assert parse_html(make_html(session_pct=pct))["session"]["used_pct"] == pct

    def test_session_pct_type_is_float(self, free_html: str) -> None:
        assert isinstance(parse_html(free_html)["session"]["used_pct"], float)

    def test_session_resets_at(self, free_html: str) -> None:
        assert parse_html(free_html)["session"]["resets_at"] == "2026-04-04T17:00:00Z"

    def test_session_resets_at_is_iso8601(self, free_html: str) -> None:
        resets_at = parse_html(free_html)["session"]["resets_at"]
        # Basic ISO 8601 check
        assert "T" in resets_at
        assert resets_at.endswith("Z")

    def test_session_keys(self, free_html: str) -> None:
        assert set(parse_html(free_html)["session"].keys()) == {"used_pct", "resets_at"}

    def test_session_zero(self) -> None:
        data = parse_html(make_html(session_pct=0.0))
        assert data["session"]["used_pct"] == 0.0

    def test_session_full(self) -> None:
        data = parse_html(make_html(session_pct=100.0))
        assert data["session"]["used_pct"] == 100.0


# ---------------------------------------------------------------------------
# Weekly usage
# ---------------------------------------------------------------------------

class TestWeeklyUsage:

    @pytest.mark.parametrize("pct", [0.0, 14.3, 50.0, 99.9, 100.0])
    def test_weekly_pct_values(self, pct: float) -> None:
        assert parse_html(make_html(weekly_pct=pct))["weekly"]["used_pct"] == pct

    def test_weekly_pct_type_is_float(self, free_html: str) -> None:
        assert isinstance(parse_html(free_html)["weekly"]["used_pct"], float)

    def test_weekly_resets_at(self, free_html: str) -> None:
        assert parse_html(free_html)["weekly"]["resets_at"] == "2026-04-06T00:00:00Z"

    def test_weekly_resets_at_is_iso8601(self, free_html: str) -> None:
        resets_at = parse_html(free_html)["weekly"]["resets_at"]
        assert "T" in resets_at
        assert resets_at.endswith("Z")

    def test_weekly_keys(self, free_html: str) -> None:
        assert set(parse_html(free_html)["weekly"].keys()) == {"used_pct", "resets_at"}

    def test_weekly_zero(self) -> None:
        data = parse_html(make_html(weekly_pct=0.0))
        assert data["weekly"]["used_pct"] == 0.0

    def test_weekly_full(self) -> None:
        data = parse_html(make_html(weekly_pct=100.0))
        assert data["weekly"]["used_pct"] == 100.0


# ---------------------------------------------------------------------------
# Output structure
# ---------------------------------------------------------------------------

class TestOutputStructure:

    def test_top_level_keys(self, free_html: str) -> None:
        assert set(parse_html(free_html).keys()) == {"plan", "session", "weekly"}

    def test_full_structure(self, pro_html: str) -> None:
        data = parse_html(pro_html)
        assert set(data.keys()) == {"plan", "session", "weekly"}
        assert set(data["session"].keys()) == {"used_pct", "resets_at"}
        assert set(data["weekly"].keys()) == {"used_pct", "resets_at"}

    def test_returns_dict(self, free_html: str) -> None:
        assert isinstance(parse_html(free_html), dict)

    def test_full_values(self, full_usage_html: str) -> None:
        data = parse_html(full_usage_html)
        assert data == {
            "plan": "pro",
            "session": {"used_pct": 45.0, "resets_at": "2026-04-05T10:00:00Z"},
            "weekly": {"used_pct": 80.0, "resets_at": "2026-04-07T00:00:00Z"},
        }

    def test_max_plan_full_usage(self, max_html: str) -> None:
        data = parse_html(max_html)
        assert data["plan"] == "max"
        assert data["session"]["used_pct"] == 99.9
        assert data["weekly"]["used_pct"] == 100.0


# ---------------------------------------------------------------------------
# Auth errors
# ---------------------------------------------------------------------------

class TestAuthErrors:

    @pytest.mark.parametrize("html", [
        "<html>redirecting to /login</html>",
        "<html>please sign in to continue</html>",
        "<html><body>/login?next=/settings</body></html>",
        "<html>Sign In to Ollama</html>",
    ])
    def test_auth_error_on_login_redirect(self, html: str) -> None:
        with pytest.raises(AuthError):
            parse_html(html)

    def test_auth_error_message(self) -> None:
        with pytest.raises(AuthError, match="invalid or expired"):
            parse_html("<html>/login</html>")

    def test_auth_error_is_subclass(self) -> None:
        from ollama_usage.exceptions import OllamaUsageError
        with pytest.raises(OllamaUsageError):
            parse_html("<html>/login</html>")


# ---------------------------------------------------------------------------
# Parse errors
# ---------------------------------------------------------------------------

class TestParseErrors:

    @pytest.mark.parametrize("html", [
        "",
        "   ",
        "<html><body>nothing here</body></html>",
        "<span class='capitalize'>free</span>",
    ])
    def test_parse_error_missing_data(self, html: str) -> None:
        with pytest.raises(ParseError):
            parse_html(html)

    def test_parse_error_missing_weekly_pct(self) -> None:
        html = """
        <span class="capitalize">free</span>
        <span class="text-sm">0% used</span>
        <div class="local-time" data-time="2026-04-04T17:00:00Z"></div>
        """
        with pytest.raises(ParseError, match="percentages"):
            parse_html(html)

    def test_parse_error_missing_reset_times(self) -> None:
        html = """
        <span class="capitalize">free</span>
        <span class="text-sm">0% used</span>
        <span class="text-sm">27.9% used</span>
        """
        with pytest.raises(ParseError, match="timestamps"):
            parse_html(html)

    def test_parse_error_missing_plan(self) -> None:
        html = """
        <span class="text-sm">0% used</span>
        <span class="text-sm">27.9% used</span>
        <div class="local-time" data-time="2026-04-04T17:00:00Z"></div>
        <div class="local-time" data-time="2026-04-06T00:00:00Z"></div>
        """
        with pytest.raises(ParseError, match="plan"):
            parse_html(html)

    def test_parse_error_is_subclass(self) -> None:
        from ollama_usage.exceptions import OllamaUsageError
        with pytest.raises(OllamaUsageError):
            parse_html("")