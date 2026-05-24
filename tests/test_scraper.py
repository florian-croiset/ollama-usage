"""Tests for ollama_usage.scraper."""

from __future__ import annotations

import pytest

from ollama_usage.exceptions import AuthError, ParseError
from ollama_usage.scraper import parse_html


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MODEL_BUTTONS = """
          <button type="button" class="usage-meter__segment"
            style="width: 61.3%; background: #ffcc00"
            data-model="qwen3-coder:480b" data-requests="78"
            aria-label="qwen3-coder:480b: 78 requests"></button>
          <button type="button" class="usage-meter__segment"
            style="width: 36.2%; background: #34c759"
            data-model="gpt-oss:120b" data-requests="170"
            aria-label="gpt-oss:120b: 170 requests"></button>
          <button type="button" class="usage-meter__segment"
            style="width: 2.5%; background: #5ac8fa"
            data-model="gemma4:31b" data-requests="1"
            aria-label="gemma4:31b: 1 request"></button>
"""

_WEEKLY_MODEL_BUTTONS = """
          <button type="button" class="usage-meter__segment"
            style="width: 45.7%; background: #ffcc00"
            data-model="qwen3-coder:480b" data-requests="78"
            aria-label="qwen3-coder:480b: 78 requests"></button>
          <button type="button" class="usage-meter__segment"
            style="width: 35.6%; background: #34c759"
            data-model="gpt-oss:120b" data-requests="262"
            aria-label="gpt-oss:120b: 262 requests"></button>
          <button type="button" class="usage-meter__segment"
            style="width: 18.7%; background: #5ac8fa"
            data-model="gemma4:31b" data-requests="28"
            aria-label="gemma4:31b: 28 requests"></button>
"""


def make_html(
    plan: str = "free",
    session_pct: float = 0.0,
    session_time: str = "2026-04-04T17:00:00Z",
    weekly_pct: float = 27.9,
    weekly_time: str = "2026-04-06T00:00:00Z",
    session_buttons: str = "",
    weekly_buttons: str = "",
) -> str:
    """Build a minimal but realistic settings page HTML fragment.

    Reproduit la structure du nouveau HTML Ollama (avec aria-label sur le
    track et les boutons de breakdown par modèle dans le fill).
    """
    return f"""
    <span class="text-xs font-normal px-2 py-0.5 rounded-full bg-neutral-100 text-neutral-600 capitalize">{plan}</span>
    <div class="flex justify-between mb-2">
      <span class="text-sm ">Session usage</span>
      <span class="text-sm ">
        {session_pct}% used
      </span>
    </div>
    <div class="usage-meter__track" data-usage-track
         aria-label="Session usage {session_pct}% used">
      <div class="usage-meter__fill" style="width: {session_pct}%;">
        {session_buttons}
      </div>
    </div>
    <div class="local-time" data-time="{session_time}">Resets soon</div>
    <div class="flex justify-between mb-2">
      <span class="text-sm">Weekly usage</span>
      <span class="text-sm">
        {weekly_pct}% used
      </span>
    </div>
    <div class="usage-meter__track" data-usage-track
         aria-label="Weekly usage {weekly_pct}% used">
      <div class="usage-meter__fill" style="width: {weekly_pct}%;">
        {weekly_buttons}
      </div>
    </div>
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


@pytest.fixture
def models_html() -> str:
    """HTML avec breakdown complet (3 modèles session, 3 weekly)."""
    return make_html(
        plan="free",
        session_pct=30.2,
        session_time="2026-05-24T02:00:00Z",
        weekly_pct=15.0,
        weekly_time="2026-05-25T00:00:00Z",
        session_buttons=_MODEL_BUTTONS,
        weekly_buttons=_WEEKLY_MODEL_BUTTONS,
    )


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------

class TestPlan:

    @pytest.mark.parametrize("plan", ["free", "pro", "max"])
    def test_known_plans(self, plan: str) -> None:
        assert parse_html(make_html(plan=plan))["plan"] == plan

    def test_plan_is_lowercase(self) -> None:
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
        assert "T" in resets_at
        assert resets_at.endswith("Z")

    def test_session_keys(self, free_html: str) -> None:
        assert set(parse_html(free_html)["session"].keys()) == {"used_pct", "resets_at", "models"}

    def test_session_zero(self) -> None:
        data = parse_html(make_html(session_pct=0.0))
        assert data["session"]["used_pct"] == 0.0

    def test_session_full(self) -> None:
        data = parse_html(make_html(session_pct=100.0))
        assert data["session"]["used_pct"] == 100.0

    def test_session_weekly_not_confused(self) -> None:
        """session_pct != weekly_pct — les deux doivent être correctement assignés."""
        data = parse_html(make_html(session_pct=30.2, weekly_pct=15.0))
        assert data["session"]["used_pct"] == 30.2
        assert data["weekly"]["used_pct"] == 15.0

    def test_aria_label_duplicate_not_counted(self) -> None:
        """Le nouveau HTML duplique chaque % dans un aria-label — ne doit pas fausser le résultat."""
        # session=10%, weekly=90% : sans le fix, le regex naïf renverrait (10, 10)
        data = parse_html(make_html(session_pct=10.0, weekly_pct=90.0))
        assert data["session"]["used_pct"] == 10.0
        assert data["weekly"]["used_pct"] == 90.0


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
        assert set(parse_html(free_html)["weekly"].keys()) == {"used_pct", "resets_at", "models"}

    def test_weekly_zero(self) -> None:
        data = parse_html(make_html(weekly_pct=0.0))
        assert data["weekly"]["used_pct"] == 0.0

    def test_weekly_full(self) -> None:
        data = parse_html(make_html(weekly_pct=100.0))
        assert data["weekly"]["used_pct"] == 100.0


# ---------------------------------------------------------------------------
# Model breakdown
# ---------------------------------------------------------------------------

class TestModelBreakdown:

    def test_no_models_returns_empty_list(self, free_html: str) -> None:
        data = parse_html(free_html)
        assert data["session"]["models"] == []
        assert data["weekly"]["models"] == []

    def test_session_models_count(self, models_html: str) -> None:
        assert len(parse_html(models_html)["session"]["models"]) == 3

    def test_weekly_models_count(self, models_html: str) -> None:
        assert len(parse_html(models_html)["weekly"]["models"]) == 3

    def test_model_keys(self, models_html: str) -> None:
        m = parse_html(models_html)["session"]["models"][0]
        assert set(m.keys()) == {"model", "requests", "share_pct", "color"}

    def test_session_model_names(self, models_html: str) -> None:
        names = [m["model"] for m in parse_html(models_html)["session"]["models"]]
        assert names == ["qwen3-coder:480b", "gpt-oss:120b", "gemma4:31b"]

    def test_weekly_model_names(self, models_html: str) -> None:
        names = [m["model"] for m in parse_html(models_html)["weekly"]["models"]]
        assert names == ["qwen3-coder:480b", "gpt-oss:120b", "gemma4:31b"]

    def test_session_model_requests(self, models_html: str) -> None:
        reqs = [m["requests"] for m in parse_html(models_html)["session"]["models"]]
        assert reqs == [78, 170, 1]

    def test_weekly_model_requests(self, models_html: str) -> None:
        reqs = [m["requests"] for m in parse_html(models_html)["weekly"]["models"]]
        assert reqs == [78, 262, 28]

    def test_session_model_share_pct(self, models_html: str) -> None:
        shares = [m["share_pct"] for m in parse_html(models_html)["session"]["models"]]
        assert shares == [61.3, 36.2, 2.5]

    def test_weekly_model_share_pct(self, models_html: str) -> None:
        shares = [m["share_pct"] for m in parse_html(models_html)["weekly"]["models"]]
        assert shares == [45.7, 35.6, 18.7]

    def test_session_model_colors(self, models_html: str) -> None:
        colors = [m["color"] for m in parse_html(models_html)["session"]["models"]]
        assert colors == ["#ffcc00", "#34c759", "#5ac8fa"]

    def test_weekly_model_colors(self, models_html: str) -> None:
        colors = [m["color"] for m in parse_html(models_html)["weekly"]["models"]]
        assert colors == ["#ffcc00", "#34c759", "#5ac8fa"]

    def test_models_not_cross_contaminated(self, models_html: str) -> None:
        """Les modèles session et weekly doivent être indépendants."""
        data = parse_html(models_html)
        session_reqs = [m["requests"] for m in data["session"]["models"]]
        weekly_reqs  = [m["requests"] for m in data["weekly"]["models"]]
        assert session_reqs != weekly_reqs  # gpt-oss: 170 vs 262

    def test_requests_type_is_int(self, models_html: str) -> None:
        for m in parse_html(models_html)["session"]["models"]:
            assert isinstance(m["requests"], int)

    def test_share_pct_type_is_float(self, models_html: str) -> None:
        for m in parse_html(models_html)["session"]["models"]:
            assert isinstance(m["share_pct"], float)

    def test_color_is_hex(self, models_html: str) -> None:
        import re
        for m in parse_html(models_html)["session"]["models"]:
            assert re.match(r"^#[0-9a-fA-F]{6}$", m["color"])

    def test_single_model(self) -> None:
        single_button = """
          <button type="button" class="usage-meter__segment"
            style="width: 100.0%; background: #ff0000"
            data-model="llama3:8b" data-requests="5"
            aria-label="llama3:8b: 5 requests"></button>
        """
        html = make_html(session_pct=5.0, session_buttons=single_button)
        models = parse_html(html)["session"]["models"]
        assert len(models) == 1
        assert models[0]["model"] == "llama3:8b"
        assert models[0]["requests"] == 5
        assert models[0]["share_pct"] == 100.0
        assert models[0]["color"] == "#ff0000"


# ---------------------------------------------------------------------------
# Output structure
# ---------------------------------------------------------------------------

class TestOutputStructure:

    def test_top_level_keys(self, free_html: str) -> None:
        assert set(parse_html(free_html).keys()) == {"plan", "session", "weekly"}

    def test_full_structure(self, pro_html: str) -> None:
        data = parse_html(pro_html)
        assert set(data.keys()) == {"plan", "session", "weekly"}
        assert set(data["session"].keys()) == {"used_pct", "resets_at", "models"}
        assert set(data["weekly"].keys()) == {"used_pct", "resets_at", "models"}

    def test_returns_dict(self, free_html: str) -> None:
        assert isinstance(parse_html(free_html), dict)

    def test_full_values(self, full_usage_html: str) -> None:
        data = parse_html(full_usage_html)
        assert data == {
            "plan": "pro",
            "session": {"used_pct": 45.0, "resets_at": "2026-04-05T10:00:00Z", "models": []},
            "weekly": {"used_pct": 80.0, "resets_at": "2026-04-07T00:00:00Z", "models": []},
        }

    def test_max_plan_full_usage(self, max_html: str) -> None:
        data = parse_html(max_html)
        assert data["plan"] == "max"
        assert data["session"]["used_pct"] == 99.9
        assert data["weekly"]["used_pct"] == 100.0

    def test_models_field_is_list(self, free_html: str) -> None:
        data = parse_html(free_html)
        assert isinstance(data["session"]["models"], list)
        assert isinstance(data["weekly"]["models"], list)


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
        '<span class="capitalize">free</span>',
    ])
    def test_parse_error_missing_data(self, html: str) -> None:
        with pytest.raises(ParseError):
            parse_html(html)

    def test_parse_error_missing_weekly_pct(self) -> None:
        html = """
        <span class="text-xs capitalize">free</span>
        <span class="text-sm ">0% used</span>
        <div class="local-time" data-time="2026-04-04T17:00:00Z"></div>
        """
        with pytest.raises(ParseError, match="percentages"):
            parse_html(html)

    def test_parse_error_missing_reset_times(self) -> None:
        html = """
        <span class="text-xs capitalize">free</span>
        <span class="text-sm ">0% used</span>
        <span class="text-sm">27.9% used</span>
        """
        with pytest.raises(ParseError, match="timestamps"):
            parse_html(html)

    def test_parse_error_missing_plan(self) -> None:
        html = """
        <span class="text-sm ">0% used</span>
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


# ---------------------------------------------------------------------------
# _fetch_html — couverture réseau
# ---------------------------------------------------------------------------

class TestFetchHtml:

    def _make_response(self, body: str, status: int = 200):
        from unittest.mock import MagicMock
        resp = MagicMock()
        resp.read.return_value = body.encode("utf-8")
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def test_returns_html_on_success(self) -> None:
        from unittest.mock import patch
        from ollama_usage.scraper import _fetch_html

        fake_resp = self._make_response("<html>ok</html>")
        with patch("urllib.request.urlopen", return_value=fake_resp):
            result = _fetch_html("my-cookie")
        assert result == "<html>ok</html>"

    def test_raises_network_error_on_url_error(self) -> None:
        import urllib.error
        from unittest.mock import patch
        from ollama_usage.scraper import _fetch_html
        from ollama_usage.exceptions import NetworkError

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            with pytest.raises(NetworkError, match="Failed to reach"):
                _fetch_html("my-cookie")

    def test_raises_parse_error_on_invalid_utf8(self) -> None:
        from unittest.mock import patch, MagicMock
        from ollama_usage.scraper import _fetch_html
        from ollama_usage.exceptions import ParseError

        resp = MagicMock()
        resp.read.return_value = b"\xff\xfe invalid utf8"
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=resp):
            with pytest.raises(ParseError, match="UTF-8"):
                _fetch_html("my-cookie")

    def test_cookie_not_logged(self, caplog) -> None:
        import logging
        from unittest.mock import patch
        from ollama_usage.scraper import _fetch_html

        fake_resp = self._make_response("<html>ok</html>")
        with patch("urllib.request.urlopen", return_value=fake_resp):
            with caplog.at_level(logging.DEBUG, logger="ollama_usage.scraper"):
                _fetch_html("super-secret-cookie-value")

        for record in caplog.records:
            assert "super-secret-cookie-value" not in record.getMessage()


# ---------------------------------------------------------------------------
# get_usage — intégration scraper complet
# ---------------------------------------------------------------------------

class TestGetUsage:

    def _make_response(self, body: str):
        from unittest.mock import MagicMock
        resp = MagicMock()
        resp.read.return_value = body.encode("utf-8")
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def test_get_usage_returns_dict(self) -> None:
        from unittest.mock import patch
        from ollama_usage.scraper import get_usage

        html = make_html(session_pct=0.0, weekly_pct=33.3)
        with patch("urllib.request.urlopen", return_value=self._make_response(html)):
            result = get_usage("my-cookie")

        assert result["plan"] == "free"
        assert result["session"]["used_pct"] == 0.0
        assert result["weekly"]["used_pct"] == 33.3

    def test_get_usage_includes_models_key(self) -> None:
        from unittest.mock import patch
        from ollama_usage.scraper import get_usage

        html = make_html(session_pct=10.0, weekly_pct=20.0)
        with patch("urllib.request.urlopen", return_value=self._make_response(html)):
            result = get_usage("my-cookie")

        assert "models" in result["session"]
        assert "models" in result["weekly"]

    def test_get_usage_propagates_network_error(self) -> None:
        import urllib.error
        from unittest.mock import patch
        from ollama_usage.scraper import get_usage
        from ollama_usage.exceptions import NetworkError

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
            with pytest.raises(NetworkError):
                get_usage("my-cookie")

    def test_get_usage_propagates_auth_error(self) -> None:
        from unittest.mock import patch
        from ollama_usage.scraper import get_usage
        from ollama_usage.exceptions import AuthError

        html = "<html>redirecting to /login</html>"
        with patch("urllib.request.urlopen", return_value=self._make_response(html)):
            with pytest.raises(AuthError):
                get_usage("expired-cookie")


# ---------------------------------------------------------------------------
# __init__.py — exports publics
# ---------------------------------------------------------------------------

class TestPublicExports:

    def test_all_exceptions_importable_from_package(self) -> None:
        from ollama_usage import (
            OllamaUsageError,
            AuthError,
            ParseError,
            NetworkError,
            BrowserNotFoundError,
            UnsupportedOSError,
        )
        assert issubclass(AuthError, OllamaUsageError)
        assert issubclass(ParseError, OllamaUsageError)
        assert issubclass(NetworkError, OllamaUsageError)
        assert issubclass(BrowserNotFoundError, OllamaUsageError)
        assert issubclass(UnsupportedOSError, OllamaUsageError)

    def test_get_usage_importable_from_package(self) -> None:
        from ollama_usage import get_usage
        assert callable(get_usage)