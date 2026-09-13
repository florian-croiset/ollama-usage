"""Tests for ollama_usage.api (official ollama.com/api/usage endpoint)."""

from __future__ import annotations

import io
import json
import logging
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from ollama_usage.api import get_api_key_env, get_usage_api, parse_api_response
from ollama_usage.exceptions import AuthError, NetworkError, ParseError


MONTHLY_PAYLOAD = {
    "activity": {
        "cost": "1.68054",
        "period": {
            "type": "last_4_weeks",
            "starting_at": "2026-08-16T00:00:00Z",
            "ending_at": "2026-09-13T00:00:00Z",
        },
        "models": [{"name": "kimi-k3", "request_count": 47, "cost": "1.68054"}],
    },
    "limits": {
        "monthly": {"usage": 0.007, "models": [{"name": "glm-5.3-flash", "request_count": 213}]},
    },
}

LEGACY_PAYLOAD = {
    "activity": {"cost": "0", "period": {"type": "last_4_weeks"}},
    "limits": {
        "session": {"usage": 0.03, "models": [{"name": "glm-5.3-flash", "request_count": 54}]},
        "weekly": {"usage": 0.335, "models": [{"name": "glm-5.3-flash", "request_count": 458}]},
    },
}


def _response(body: bytes) -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://ollama.com/api/usage", code=code, msg="error",
        hdrs=None, fp=io.BytesIO(b'{"error":"invalid credentials"}'),  # type: ignore[arg-type]
    )


class TestParseMonthly:

    def test_monthly_pct(self) -> None:
        assert parse_api_response(MONTHLY_PAYLOAD)["monthly"]["used_pct"] == 0.7

    def test_legacy_periods_none(self) -> None:
        data = parse_api_response(MONTHLY_PAYLOAD)
        assert data["session"] is None
        assert data["weekly"] is None

    def test_monthly_models(self) -> None:
        assert parse_api_response(MONTHLY_PAYLOAD)["monthly"]["models"] == [
            {"model": "glm-5.3-flash", "requests": 213, "share_pct": None, "color": None},
        ]

    def test_fields_not_exposed_by_api(self) -> None:
        data = parse_api_response(MONTHLY_PAYLOAD)
        assert data["plan"] is None
        assert data["credits_balance"] is None
        assert data["monthly"]["resets_at"] is None

    def test_source(self) -> None:
        assert parse_api_response(MONTHLY_PAYLOAD)["source"] == "api"

    def test_spend(self) -> None:
        assert parse_api_response(MONTHLY_PAYLOAD)["spend"] == {
            "cost_usd": 1.68054,
            "period": "last_4_weeks",
            "starting_at": "2026-08-16T00:00:00Z",
            "ending_at": "2026-09-13T00:00:00Z",
        }

    def test_same_keys_as_scraper(self) -> None:
        from ollama_usage.scraper import UsageData
        assert set(parse_api_response(MONTHLY_PAYLOAD)) == set(UsageData(plan="free").to_dict())


class TestParseLegacy:

    def test_session_and_weekly(self) -> None:
        data = parse_api_response(LEGACY_PAYLOAD)
        assert data["session"]["used_pct"] == 3.0
        assert data["weekly"]["used_pct"] == 33.5
        assert data["monthly"] is None

    def test_models_not_cross_contaminated(self) -> None:
        data = parse_api_response(LEGACY_PAYLOAD)
        assert data["session"]["models"][0]["requests"] == 54
        assert data["weekly"]["models"][0]["requests"] == 458

    def test_models_as_dict(self) -> None:
        payload = {"limits": {"session": {"usage": 0.025, "models": {"qwen3": {"request_count": 7}}}}}
        assert parse_api_response(payload)["session"]["models"] == [
            {"model": "qwen3", "requests": 7, "share_pct": None, "color": None},
        ]


class TestParseEdgeCases:

    @pytest.mark.parametrize("fraction,expected", [(0, 0.0), (1, 100.0), (0.0254, 2.5), (1.2, 120.0)])
    def test_fraction_to_pct(self, fraction: float, expected: float) -> None:
        payload = {"limits": {"monthly": {"usage": fraction}}}
        assert parse_api_response(payload)["monthly"]["used_pct"] == expected

    def test_missing_models_is_empty_list(self) -> None:
        assert parse_api_response({"limits": {"monthly": {"usage": 0.1}}})["monthly"]["models"] == []

    def test_empty_limits_all_none(self) -> None:
        data = parse_api_response({"limits": {}})
        assert data["session"] is data["weekly"] is data["monthly"] is None

    def test_missing_activity_spend_none(self) -> None:
        assert parse_api_response({"limits": {}})["spend"] is None

    def test_invalid_cost_spend_none(self) -> None:
        assert parse_api_response({"limits": {}, "activity": {"cost": "n/a"}})["spend"] is None

    @pytest.mark.parametrize("payload", [{}, {"limits": None}, {"limits": []}])
    def test_missing_limits_raises(self, payload: dict) -> None:
        with pytest.raises(ParseError, match="limits"):
            parse_api_response(payload)

    def test_invalid_fraction_raises(self) -> None:
        with pytest.raises(ParseError, match="fraction"):
            parse_api_response({"limits": {"monthly": {"usage": "lots"}}})


class TestGetUsageApi:

    def test_success(self) -> None:
        body = json.dumps(MONTHLY_PAYLOAD).encode()
        with patch("urllib.request.urlopen", return_value=_response(body)) as urlopen:
            data = get_usage_api("sk-test")
        assert data["monthly"]["used_pct"] == 0.7
        req = urlopen.call_args[0][0]
        assert req.full_url == "https://ollama.com/api/usage"
        assert req.get_header("Authorization") == "Bearer sk-test"

    @pytest.mark.parametrize("code", [401, 403])
    def test_auth_error(self, code: int) -> None:
        with patch("urllib.request.urlopen", side_effect=_http_error(code)):
            with pytest.raises(AuthError, match="API key"):
                get_usage_api("bad")

    @pytest.mark.parametrize("code", [404, 429, 500, 503])
    def test_http_error(self, code: int) -> None:
        with patch("urllib.request.urlopen", side_effect=_http_error(code)):
            with pytest.raises(NetworkError, match="HTTP error"):
                get_usage_api("sk-test")

    def test_url_error(self) -> None:
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            with pytest.raises(NetworkError, match="Failed to reach"):
                get_usage_api("sk-test")

    @pytest.mark.parametrize("body", [b"<html>not json</html>", b"\xff\xfe", b"[1, 2]"])
    def test_invalid_body(self, body: bytes) -> None:
        with patch("urllib.request.urlopen", return_value=_response(body)):
            with pytest.raises(ParseError):
                get_usage_api("sk-test")

    def test_api_key_not_logged(self, caplog) -> None:
        body = json.dumps(MONTHLY_PAYLOAD).encode()
        with patch("urllib.request.urlopen", return_value=_response(body)):
            with caplog.at_level(logging.DEBUG, logger="ollama_usage.api"):
                get_usage_api("super-secret-api-key")
        assert all("super-secret-api-key" not in r.getMessage() for r in caplog.records)


class TestApiKeyEnv:

    def test_set(self, monkeypatch) -> None:
        monkeypatch.setenv("OLLAMA_API_KEY", "  sk-env  ")
        assert get_api_key_env() == "sk-env"

    @pytest.mark.parametrize("value", ["", "   "])
    def test_blank_is_none(self, monkeypatch, value: str) -> None:
        monkeypatch.setenv("OLLAMA_API_KEY", value)
        assert get_api_key_env() is None

    def test_unset_is_none(self, monkeypatch) -> None:
        monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
        assert get_api_key_env() is None

    def test_exported_from_package(self) -> None:
        from ollama_usage import get_usage_api as exported
        assert exported is get_usage_api


FREE_PAYLOAD = {
    "activity": {
        "cost": "0.00000",
        "period": {
            "type": "last_4_weeks",
            "starting_at": "2026-08-15T00:00:00Z",
            "ending_at": "2026-09-12T08:30:00.123456789Z",
        },
        "models": [],
    },
    "limits": {
        "monthly": {
            "usage": 0.184,
            "models": [
                {"name": "web search", "request_count": 21},
                {"name": "deepseek-v3.1:671b", "request_count": 112},
                {"name": "gpt-oss:120b", "request_count": 64},
                {"name": "kimi-k2:1t", "request_count": 7},
                {"name": "web fetch", "request_count": 3},
            ],
        },
    },
}


class TestFreePayload:

    def test_monthly_and_models(self) -> None:
        data = parse_api_response(FREE_PAYLOAD)
        assert data["monthly"]["used_pct"] == 18.4
        assert {m["model"]: m["requests"] for m in data["monthly"]["models"]} == {
            "web search": 21, "deepseek-v3.1:671b": 112, "gpt-oss:120b": 64,
            "kimi-k2:1t": 7, "web fetch": 3,
        }

    def test_zero_spend(self) -> None:
        assert parse_api_response(FREE_PAYLOAD)["spend"]["cost_usd"] == 0.0


class TestParseModelsEdgeCases:

    def test_entries_without_name_skipped(self) -> None:
        payload = {"limits": {"monthly": {"usage": 0.1, "models": [
            {"name": "a", "request_count": 1}, {"request_count": 5}, {"name": "", "request_count": 2},
        ]}}}
        assert [m["model"] for m in parse_api_response(payload)["monthly"]["models"]] == ["a"]

    def test_non_dict_entries_skipped(self) -> None:
        payload = {"limits": {"monthly": {"usage": 0.1, "models": ["a", 3, None, {"name": "b"}]}}}
        assert [m["model"] for m in parse_api_response(payload)["monthly"]["models"]] == ["b"]

    @pytest.mark.parametrize("count", [None, 0])
    def test_missing_request_count_is_zero(self, count) -> None:
        payload = {"limits": {"monthly": {"usage": 0.1, "models": [{"name": "a", "request_count": count}]}}}
        assert parse_api_response(payload)["monthly"]["models"][0]["requests"] == 0

    def test_request_count_absent_is_zero(self) -> None:
        payload = {"limits": {"monthly": {"usage": 0.1, "models": [{"name": "a"}]}}}
        assert parse_api_response(payload)["monthly"]["models"][0]["requests"] == 0

    def test_dict_form_with_non_dict_info(self) -> None:
        payload = {"limits": {"weekly": {"usage": 0.1, "models": {"a": 12}}}}
        assert parse_api_response(payload)["weekly"]["models"] == [
            {"model": "a", "requests": 0, "share_pct": None, "color": None},
        ]

    @pytest.mark.parametrize("models", ["gemma", 42, None])
    def test_unexpected_models_type(self, models) -> None:
        payload = {"limits": {"monthly": {"usage": 0.1, "models": models}}}
        assert parse_api_response(payload)["monthly"]["models"] == []

    def test_models_order_preserved(self) -> None:
        names = [m["model"] for m in parse_api_response(FREE_PAYLOAD)["monthly"]["models"]]
        assert names == ["web search", "deepseek-v3.1:671b", "gpt-oss:120b", "kimi-k2:1t", "web fetch"]


class TestParsePeriodEdgeCases:

    @pytest.mark.parametrize("raw", [0.5, "0.5", [], None, {"models": []}])
    def test_invalid_period_is_none(self, raw) -> None:
        assert parse_api_response({"limits": {"monthly": raw}})["monthly"] is None

    @pytest.mark.parametrize("usage", [None, "n/a", [], {}])
    def test_invalid_usage_raises(self, usage) -> None:
        with pytest.raises(ParseError, match="fraction"):
            parse_api_response({"limits": {"monthly": {"usage": usage}}})

    def test_numeric_string_usage(self) -> None:
        assert parse_api_response({"limits": {"monthly": {"usage": "0.5"}}})["monthly"]["used_pct"] == 50.0

    def test_unknown_limits_ignored(self) -> None:
        data = parse_api_response({"limits": {"daily": {"usage": 0.9}, "monthly": {"usage": 0.1}}})
        assert "daily" not in data
        assert data["monthly"]["used_pct"] == 10.0

    def test_all_three_periods(self) -> None:
        payload = {"limits": {k: {"usage": 0.25} for k in ("session", "weekly", "monthly")}}
        data = parse_api_response(payload)
        assert [data[k]["used_pct"] for k in ("session", "weekly", "monthly")] == [25.0, 25.0, 25.0]

    def test_rounding(self) -> None:
        assert parse_api_response({"limits": {"monthly": {"usage": 0.12345}}})["monthly"]["used_pct"] == 12.3


class TestParseSpendEdgeCases:

    def test_numeric_cost(self) -> None:
        assert parse_api_response({"limits": {}, "activity": {"cost": 2.5}})["spend"]["cost_usd"] == 2.5

    def test_period_not_a_dict(self) -> None:
        spend = parse_api_response({"limits": {}, "activity": {"cost": "1", "period": "last_4_weeks"}})["spend"]
        assert spend == {"cost_usd": 1.0, "period": None, "starting_at": None, "ending_at": None}

    @pytest.mark.parametrize("activity", [None, "x", [], {}, {"cost": None}])
    def test_missing_spend(self, activity) -> None:
        assert parse_api_response({"limits": {}, "activity": activity})["spend"] is None


class TestRequestHeaders:

    def _request(self):
        body = json.dumps(FREE_PAYLOAD).encode()
        with patch("urllib.request.urlopen", return_value=_response(body)) as urlopen:
            get_usage_api("sk-test")
        return urlopen.call_args

    def test_accept_json(self) -> None:
        assert self._request()[0][0].get_header("Accept") == "application/json"

    def test_user_agent(self) -> None:
        assert self._request()[0][0].get_header("User-agent") == "ollama-usage"

    def test_timeout_and_ssl_context(self) -> None:
        from ollama_usage.scraper import _SSL_CONTEXT, _TIMEOUT
        kwargs = self._request()[1]
        assert kwargs["timeout"] == _TIMEOUT
        assert kwargs["context"] is _SSL_CONTEXT

    def test_get_method(self) -> None:
        assert self._request()[0][0].get_method() == "GET"

    def test_401_does_not_leak_key(self) -> None:
        with patch("urllib.request.urlopen", side_effect=_http_error(401)):
            with pytest.raises(AuthError) as exc:
                get_usage_api("super-secret-api-key")
        assert "super-secret-api-key" not in str(exc.value)

    def test_empty_body_raises(self) -> None:
        with patch("urllib.request.urlopen", return_value=_response(b"")):
            with pytest.raises(ParseError, match="invalid JSON"):
                get_usage_api("sk-test")
