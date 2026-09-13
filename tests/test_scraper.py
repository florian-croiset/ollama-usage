"""Tests for ollama_usage.scraper."""

from __future__ import annotations

import pytest

from ollama_usage.exceptions import AuthError, ParseError
from ollama_usage.scraper import parse_html


_MODEL_BUTTONS = """
          <button type="button" class="usage-meter__segment"
            style="width: 55.0%; background: #ffcc00"
            data-model="qwen3-coder:480b" data-requests="42"
            aria-label="qwen3-coder:480b: 42 requests"></button>
          <button type="button" class="usage-meter__segment"
            style="width: 40.0%; background: #34c759"
            data-model="gpt-oss:120b" data-requests="30"
            aria-label="gpt-oss:120b: 30 requests"></button>
          <button type="button" class="usage-meter__segment"
            style="width: 5.0%; background: #5ac8fa"
            data-model="glm-4.6" data-requests="4"
            aria-label="glm-4.6: 4 requests"></button>
"""

_WEEKLY_MODEL_BUTTONS = """
          <button type="button" class="usage-meter__segment"
            style="width: 25.0%; background: #ffcc00"
            data-model="qwen3-coder:480b" data-requests="42"
            aria-label="qwen3-coder:480b: 42 requests"></button>
          <button type="button" class="usage-meter__segment"
            style="width: 65.0%; background: #34c759"
            data-model="gpt-oss:120b" data-requests="110"
            aria-label="gpt-oss:120b: 110 requests"></button>
          <button type="button" class="usage-meter__segment"
            style="width: 10.0%; background: #5ac8fa"
            data-model="glm-4.6" data-requests="16"
            aria-label="glm-4.6: 16 requests"></button>
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
    """Legacy settings page (session + weekly meters)."""
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
    return make_html(
        plan="free",
        session_pct=30.2,
        session_time="2026-05-24T02:00:00Z",
        weekly_pct=15.0,
        weekly_time="2026-05-25T00:00:00Z",
        session_buttons=_MODEL_BUTTONS,
        weekly_buttons=_WEEKLY_MODEL_BUTTONS,
    )


class TestPlan:

    @pytest.mark.parametrize("plan", ["free", "pro", "max"])
    def test_known_plans(self, plan: str) -> None:
        assert parse_html(make_html(plan=plan))["plan"] == plan

    def test_plan_is_lowercase(self) -> None:
        html = make_html(plan="FREE")
        assert parse_html(html)["plan"] == "free"

    def test_plan_present_in_output(self, free_html: str) -> None:
        assert "plan" in parse_html(free_html)


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
        data = parse_html(make_html(session_pct=30.2, weekly_pct=15.0))
        assert data["session"]["used_pct"] == 30.2
        assert data["weekly"]["used_pct"] == 15.0

    def test_aria_label_duplicate_not_counted(self) -> None:
        """The HTML duplicates each % in an aria-label — it must not skew the result."""
        # session=10%, weekly=90%: without the fix, the naive regex would return (10, 10)
        data = parse_html(make_html(session_pct=10.0, weekly_pct=90.0))
        assert data["session"]["used_pct"] == 10.0
        assert data["weekly"]["used_pct"] == 90.0


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
        assert names == ["qwen3-coder:480b", "gpt-oss:120b", "glm-4.6"]

    def test_weekly_model_names(self, models_html: str) -> None:
        names = [m["model"] for m in parse_html(models_html)["weekly"]["models"]]
        assert names == ["qwen3-coder:480b", "gpt-oss:120b", "glm-4.6"]

    def test_session_model_requests(self, models_html: str) -> None:
        reqs = [m["requests"] for m in parse_html(models_html)["session"]["models"]]
        assert reqs == [42, 30, 4]

    def test_weekly_model_requests(self, models_html: str) -> None:
        reqs = [m["requests"] for m in parse_html(models_html)["weekly"]["models"]]
        assert reqs == [42, 110, 16]

    def test_session_model_share_pct(self, models_html: str) -> None:
        shares = [m["share_pct"] for m in parse_html(models_html)["session"]["models"]]
        assert shares == [55.0, 40.0, 5.0]

    def test_weekly_model_share_pct(self, models_html: str) -> None:
        shares = [m["share_pct"] for m in parse_html(models_html)["weekly"]["models"]]
        assert shares == [25.0, 65.0, 10.0]

    def test_session_model_colors(self, models_html: str) -> None:
        colors = [m["color"] for m in parse_html(models_html)["session"]["models"]]
        assert colors == ["#ffcc00", "#34c759", "#5ac8fa"]

    def test_weekly_model_colors(self, models_html: str) -> None:
        colors = [m["color"] for m in parse_html(models_html)["weekly"]["models"]]
        assert colors == ["#ffcc00", "#34c759", "#5ac8fa"]

    def test_models_not_cross_contaminated(self, models_html: str) -> None:
        data = parse_html(models_html)
        session_reqs = [m["requests"] for m in data["session"]["models"]]
        weekly_reqs  = [m["requests"] for m in data["weekly"]["models"]]
        assert session_reqs != weekly_reqs  # gpt-oss: 30 vs 110

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


_TOP_LEVEL_KEYS = {"plan", "session", "weekly", "monthly", "credits_balance", "spend", "source"}


class TestOutputStructure:

    def test_top_level_keys(self, free_html: str) -> None:
        assert set(parse_html(free_html).keys()) == _TOP_LEVEL_KEYS

    def test_full_structure(self, pro_html: str) -> None:
        data = parse_html(pro_html)
        assert set(data.keys()) == _TOP_LEVEL_KEYS
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
            "monthly": None,
            "credits_balance": None,
            "spend": None,
            "source": "web",
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

    def test_parse_error_unlabelled_pct(self) -> None:
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
        <span class="text-sm">Free usage</span>
        <span class="text-sm">27.9% used</span>
        """
        with pytest.raises(ParseError, match="timestamp"):
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


class TestFetchHtmlHTTPErrors:

    def _http_error(self, code: int):
        import io
        import urllib.error
        return urllib.error.HTTPError(
            url="https://ollama.com/settings",
            code=code,
            msg="error",
            hdrs=None,
            fp=io.BytesIO(b""),
        )

    @pytest.mark.parametrize("code", [401, 403])
    def test_auth_error_on_401_403(self, code: int) -> None:
        from unittest.mock import patch
        from ollama_usage.scraper import _fetch_html

        with patch("urllib.request.urlopen", side_effect=self._http_error(code)):
            with pytest.raises(AuthError, match="cookie is invalid or expired"):
                _fetch_html("my-cookie")

    @pytest.mark.parametrize("code", [400, 404, 418, 429, 500, 502, 503])
    def test_network_error_on_other_http_codes(self, code: int) -> None:
        from unittest.mock import patch
        from ollama_usage.scraper import _fetch_html
        from ollama_usage.exceptions import NetworkError

        with patch("urllib.request.urlopen", side_effect=self._http_error(code)):
            with pytest.raises(NetworkError, match="HTTP error"):
                _fetch_html("my-cookie")


class TestParsingEdgeCases:

    def test_integer_percentage_parsed_as_float(self) -> None:
        data = parse_html(make_html(session_pct=50, weekly_pct=75))
        assert data["session"]["used_pct"] == 50.0
        assert isinstance(data["session"]["used_pct"], float)

    def test_uppercase_hex_color_accepted(self) -> None:
        button = (
            '<button style="width: 100.0%; background: #ABCDEF"'
            ' data-model="m:1b" data-requests="3"></button>'
        )
        data = parse_html(make_html(session_pct=5.0, session_buttons=button))
        assert data["session"]["models"][0]["color"] == "#ABCDEF"

    def test_model_name_with_special_chars(self) -> None:
        button = (
            '<button style="width: 100.0%; background: #000000"'
            ' data-model="org/model:7b-instruct-q4_K_M" data-requests="9"></button>'
        )
        data = parse_html(make_html(session_pct=5.0, session_buttons=button))
        assert data["session"]["models"][0]["model"] == "org/model:7b-instruct-q4_K_M"

    def test_zero_request_count(self) -> None:
        button = (
            '<button style="width: 100.0%; background: #000000"'
            ' data-model="m:1b" data-requests="0"></button>'
        )
        data = parse_html(make_html(session_pct=5.0, session_buttons=button))
        assert data["session"]["models"][0]["requests"] == 0

    def test_weekly_only_models_do_not_leak_to_session(self) -> None:
        button = (
            '<button style="width: 100.0%; background: #111111"'
            ' data-model="only-weekly:1b" data-requests="4"></button>'
        )
        data = parse_html(make_html(weekly_pct=20.0, weekly_buttons=button))
        assert data["session"]["models"] == []
        assert data["weekly"]["models"][0]["model"] == "only-weekly:1b"


_MONTHLY_BUTTONS = """
          <button
            type="button"
            class="relative h-full min-w-[2px] flex-none overflow-hidden border-r border-white p-0 last:border-r-0 focus-visible:outline-none"
            style="width: 63.6%; background: #22c55e"
            data-usage-segment
            data-model="deepseek-v3.1:671b"
            data-requests="112"
            aria-label="deepseek-v3.1:671b: 112 requests"
          ></button>
          <button
            type="button"
            class="relative h-full min-w-[2px] flex-none overflow-hidden border-r border-white p-0 last:border-r-0 focus-visible:outline-none"
            style="width: 36.4%; background: #3b82f6"
            data-usage-segment
            data-model="gpt-oss:120b"
            data-requests="64"
            aria-label="gpt-oss:120b: 64 requests"
          ></button>
"""


def make_monthly_html(
    label: str = "Free",
    pct: float = 18.4,
    resets_at: str = "2026-10-01T00:00:00Z",
    buttons: str = "",
    balance: str | None = "$0",
    with_aria: bool = True,
) -> str:
    aria = f'aria-label="{label} usage {pct}% used"' if with_aria else ""
    balance_html = (
        f'<div id="extra-usage-balance" class="text-lg font-medium">{balance}</div>'
        if balance is not None else ""
    )
    return f"""
  <h2 class="text-xl font-medium flex items-center space-x-2">
    <span>Included usage</span>
    <span
      class="text-xs font-normal px-2 py-0.5 rounded-full bg-neutral-100 text-neutral-600 capitalize"
      >{label.lower()}</span
    >
  </h2>
  <div>
    <div class="flex justify-between mb-2">
      <span class="text-sm">{label} usage</span>
      <span class="text-sm"
        >{pct}% used</span
      >
    </div>
    <div class="relative group" data-usage-meter>
      <div class="relative h-3 overflow-hidden rounded-full bg-neutral-200"
        data-usage-track
        {aria}
      >
        <div class="flex h-full overflow-hidden bg-neutral-950" style="width: {pct}%; ">
          {buttons}
        </div>
      </div>
    </div>
    <div class="text-xs text-neutral-500 mt-1 local-time" data-time="{resets_at}">
      Resets in 4 weeks.
    </div>
    <div id="monthly-usage-models" class="mt-3 space-y-1.5">
      <span class="h-2 w-2 flex-none rounded-sm" style="background: #22c55e" aria-hidden="true"></span>
      <span class="min-w-0 flex-1 truncate text-neutral-700" title="deepseek-v3.1:671b">deepseek-v3.1:671b</span>
    </div>
  </div>
  <div id="extra-usage" class="space-y-6 pt-4">
    <h2 class="text-xl font-medium">Usage credits</h2>
    {balance_html}
  </div>
  <section id="recent-requests-self">
    <table><tbody><tr>
      <td class="local-time" data-time="2026-09-10T08:00:00.000000Z">3 hours ago</td>
      <td><div title="deepseek-v3.1:671b">deepseek-v3.1:671b</div></td>
      <td title="$0.00100">&lt;$0.01</td>
    </tr></tbody></table>
  </section>
    """


class TestMonthlyPlans:

    @pytest.mark.parametrize("label", ["Free", "Pro", "Max", "Team"])
    def test_plan_meter_is_monthly(self, label: str) -> None:
        data = parse_html(make_monthly_html(label=label, pct=12.5))
        assert data["plan"] == label.lower()
        assert data["monthly"]["used_pct"] == 12.5
        assert data["session"] is None
        assert data["weekly"] is None

    def test_monthly_resets_at_ignores_recent_requests(self) -> None:
        data = parse_html(make_monthly_html())
        assert data["monthly"]["resets_at"] == "2026-10-01T00:00:00Z"

    def test_monthly_models(self) -> None:
        models = parse_html(make_monthly_html(buttons=_MONTHLY_BUTTONS))["monthly"]["models"]
        assert models == [
            {"model": "deepseek-v3.1:671b", "requests": 112, "share_pct": 63.6, "color": "#22c55e"},
            {"model": "gpt-oss:120b", "requests": 64, "share_pct": 36.4, "color": "#3b82f6"},
        ]

    def test_monthly_without_models(self) -> None:
        assert parse_html(make_monthly_html())["monthly"]["models"] == []

    def test_text_fallback_without_aria_label(self) -> None:
        data = parse_html(make_monthly_html(pct=40.0, buttons=_MONTHLY_BUTTONS, with_aria=False))
        assert data["monthly"]["used_pct"] == 40.0
        assert len(data["monthly"]["models"]) == 2

    @pytest.mark.parametrize("balance,expected", [
        ("$0", 0.0),
        ("$12.50", 12.5),
        ("$1,234.56", 1234.56),
        ("-$3.20", -3.2),
    ])
    def test_credits_balance(self, balance: str, expected: float) -> None:
        assert parse_html(make_monthly_html(balance=balance))["credits_balance"] == expected

    def test_credits_balance_absent_is_none(self) -> None:
        assert parse_html(make_monthly_html(balance=None))["credits_balance"] is None

    def test_legacy_plan_has_no_monthly(self, free_html: str) -> None:
        data = parse_html(free_html)
        assert data["monthly"] is None
        assert data["session"] is not None
        assert data["weekly"] is not None

    def test_legacy_plan_with_credits_section(self) -> None:
        html = make_html(plan="pro", session_pct=10.0, weekly_pct=20.0) + (
            '<div id="extra-usage-balance" class="text-lg">$5</div>'
        )
        data = parse_html(html)
        assert data["credits_balance"] == 5.0
        assert data["monthly"] is None


class TestIterPeriods:

    def test_legacy_order(self, free_html: str) -> None:
        from ollama_usage.scraper import iter_periods
        assert [k for k, _ in iter_periods(parse_html(free_html))] == ["session", "weekly"]

    def test_monthly_only(self) -> None:
        from ollama_usage.scraper import iter_periods
        assert [k for k, _ in iter_periods(parse_html(make_monthly_html()))] == ["monthly"]

    def test_missing_keys_are_skipped(self) -> None:
        from ollama_usage.scraper import iter_periods
        data = {"plan": "free", "session": {"used_pct": 1.0, "resets_at": "x"}}
        assert [k for k, _ in iter_periods(data)] == ["session"]


class TestPeriodKey:

    @pytest.mark.parametrize("label,expected", [
        ("Session", "session"),
        ("SESSION", "session"),
        (" weekly ", "weekly"),
        ("Free", "monthly"),
        ("Pro", "monthly"),
        ("Max", "monthly"),
        ("Team", "monthly"),
        ("Included", "monthly"),
    ])
    def test_mapping(self, label: str, expected: str) -> None:
        from ollama_usage.scraper import _period_key
        assert _period_key(label) == expected


class TestMeterParsingEdgeCases:

    def test_duplicate_meter_keeps_first(self) -> None:
        html = make_monthly_html(pct=10.0) + make_monthly_html(pct=90.0, resets_at="2027-01-01T00:00:00Z")
        data = parse_html(html)
        assert data["monthly"]["used_pct"] == 10.0
        assert data["monthly"]["resets_at"] == "2026-10-01T00:00:00Z"

    def test_hyphenated_plan_label(self) -> None:
        assert parse_html(make_monthly_html(label="Pro-Max", pct=7.0))["monthly"]["used_pct"] == 7.0

    def test_multi_word_plan_label(self) -> None:
        assert parse_html(make_monthly_html(label="Team Plus", pct=8.0))["monthly"]["used_pct"] == 8.0

    def test_integer_percentage(self) -> None:
        assert parse_html(make_monthly_html(pct=3))["monthly"]["used_pct"] == 3.0

    def test_legacy_and_monthly_together(self) -> None:
        html = make_html(session_pct=1.0, weekly_pct=2.0) + make_monthly_html(pct=3.0)
        data = parse_html(html)
        assert (data["session"]["used_pct"], data["weekly"]["used_pct"], data["monthly"]["used_pct"]) == (1.0, 2.0, 3.0)

    def test_models_after_reset_timestamp_ignored(self) -> None:
        stray = (
            '<button style="width: 100.0%; background: #123456"'
            ' data-model="stray:1b" data-requests="9"></button>'
        )
        html = make_monthly_html(buttons=_MONTHLY_BUTTONS).replace(
            '<div id="monthly-usage-models"', stray + '<div id="monthly-usage-models"'
        )
        names = [m["model"] for m in parse_html(html)["monthly"]["models"]]
        assert "stray:1b" not in names
        assert names == ["deepseek-v3.1:671b", "gpt-oss:120b"]

    def test_missing_reset_mentions_label(self) -> None:
        html = '<span class="capitalize">pro</span><div aria-label="Pro usage 5% used"></div>'
        with pytest.raises(ParseError, match="Pro usage"):
            parse_html(html)

    def test_segment_without_model_attributes_ignored(self) -> None:
        button = '<button style="width: 50.0%; background: #000000"></button>'
        assert parse_html(make_monthly_html(buttons=button))["monthly"]["models"] == []

    def test_short_hex_color_ignored(self) -> None:
        button = '<button style="width: 50.0%; background: #fff" data-model="m" data-requests="1"></button>'
        assert parse_html(make_monthly_html(buttons=button))["monthly"]["models"] == []


class TestCreditsBalanceEdgeCases:

    @pytest.mark.parametrize("balance,expected", [
        ("$ 7.5", 7.5),
        ("$1,000", 1000.0),
        ("$0.01", 0.01),
        ("$-2", -2.0),
    ])
    def test_formats(self, balance: str, expected: float) -> None:
        assert parse_html(make_monthly_html(balance=balance))["credits_balance"] == expected

    @pytest.mark.parametrize("balance", ["€5", "free", ""])
    def test_unparseable_is_none(self, balance: str) -> None:
        assert parse_html(make_monthly_html(balance=balance))["credits_balance"] is None

    def test_type_is_float(self) -> None:
        assert isinstance(parse_html(make_monthly_html(balance="$3"))["credits_balance"], float)


class TestUsageDataAndIterPeriods:

    def test_to_dict_without_periods(self) -> None:
        from ollama_usage.scraper import UsageData
        assert UsageData(plan="free").to_dict() == {
            "plan": "free", "session": None, "weekly": None, "monthly": None,
            "credits_balance": None, "spend": None, "source": "web",
        }

    def test_to_dict_model_fields(self) -> None:
        from ollama_usage.scraper import ModelUsage, PeriodUsage, UsageData
        data = UsageData(plan="pro", monthly=PeriodUsage(1.0, "t", [ModelUsage("m", 2, 3.0, "#abcdef")]))
        assert data.to_dict()["monthly"]["models"] == [
            {"model": "m", "requests": 2, "share_pct": 3.0, "color": "#abcdef"},
        ]

    def test_model_usage_default_color(self) -> None:
        from ollama_usage.scraper import ModelUsage
        assert ModelUsage("m", 1, 1.0).color == "#888888"

    def test_iter_periods_skips_empty_dict(self) -> None:
        from ollama_usage.scraper import iter_periods
        data = {"session": {}, "weekly": None, "monthly": {"used_pct": 1.0}}
        assert [k for k, _ in iter_periods(data)] == ["monthly"]

    def test_iter_periods_empty_input(self) -> None:
        from ollama_usage.scraper import iter_periods
        assert iter_periods({}) == []

    def test_period_keys_order(self) -> None:
        from ollama_usage.scraper import PERIOD_KEYS
        assert PERIOD_KEYS == ("session", "weekly", "monthly")


class TestFetchHtmlRequest:

    def test_sends_session_cookie(self) -> None:
        from unittest.mock import MagicMock, patch
        from ollama_usage.scraper import _fetch_html

        resp = MagicMock()
        resp.read.return_value = b"<html></html>"
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=resp) as urlopen:
            _fetch_html("abc123")
        req = urlopen.call_args[0][0]
        assert req.full_url == "https://ollama.com/settings"
        assert req.get_header("Cookie") == "__Secure-session=abc123"
        assert req.get_header("User-agent")

    def test_get_usage_monthly_end_to_end(self) -> None:
        from unittest.mock import MagicMock, patch
        from ollama_usage.scraper import get_usage

        resp = MagicMock()
        resp.read.return_value = make_monthly_html(pct=18.4, buttons=_MONTHLY_BUTTONS, balance="$4").encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=resp):
            data = get_usage("cookie")
        assert data["plan"] == "free"
        assert data["monthly"]["used_pct"] == 18.4
        assert len(data["monthly"]["models"]) == 2
        assert data["credits_balance"] == 4.0
        assert data["source"] == "web"


class TestAuthCheckEdgeCases:

    def test_real_page_without_login_passes(self) -> None:
        assert parse_html(make_monthly_html())["plan"] == "free"

    @pytest.mark.parametrize("html", ['<a href="/login">Log in</a>', "SIGN IN"])
    def test_login_markers(self, html: str) -> None:
        with pytest.raises(AuthError):
            parse_html(make_monthly_html() + html)


class TestPlanNames:

    @pytest.mark.parametrize("badge,expected", [
        ("free", "free"),
        ("Pro Max", "pro max"),
        ("pro-max", "pro-max"),
        ("  Team  ", "team"),
    ])
    def test_plan_badge(self, badge: str, expected: str) -> None:
        html = make_monthly_html().replace(">free</span", f">{badge}</span", 1)
        assert parse_html(html)["plan"] == expected
