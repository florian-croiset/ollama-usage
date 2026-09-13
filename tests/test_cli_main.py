"""End-to-end tests for ollama_usage.cli.main() with mocked data sources."""

from __future__ import annotations

import json
import logging
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

from ollama_usage import cli
from ollama_usage.exceptions import AuthError, BrowserNotFoundError, NetworkError, ParseError


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch) -> None:
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_BROWSER_COOKIE", raising=False)
    monkeypatch.setenv("NO_COLOR", "1")


def usage(monthly_pct: float | None = 10.0, session_pct: float | None = None) -> dict:
    def period(pct):
        if pct is None:
            return None
        return {"used_pct": pct, "resets_at": "2026-10-01T00:00:00Z", "models": []}

    return {
        "plan": "free",
        "session": period(session_pct),
        "weekly": None,
        "monthly": period(monthly_pct),
        "credits_balance": 0.0,
        "spend": None,
        "source": "web",
    }


def run(argv: list[str], **patches) -> dict[str, MagicMock]:
    """Run main() with `ollama_usage.cli.<name>` patched; return the mocks."""
    defaults = {
        "get_usage": MagicMock(return_value=usage()),
        "get_usage_api": MagicMock(return_value=usage()),
        "get_cookie_auto": MagicMock(return_value="auto-cookie"),
        "check_and_notify": MagicMock(),
        "_watch_countdown": MagicMock(side_effect=KeyboardInterrupt),
    }
    defaults.update(patches)
    with ExitStack() as stack:
        for name, value in defaults.items():
            stack.enter_context(patch.object(cli, name, value))
        stack.enter_context(patch("sys.argv", ["ollama-usage", *argv]))
        cli.main()
    return defaults


class TestVersionAndHelp:

    def test_version(self, capsys) -> None:
        with pytest.raises(SystemExit) as exc:
            run(["--version"])
        assert exc.value.code == 0
        assert capsys.readouterr().out.startswith("ollama-usage ")

    def test_help_mentions_api_key(self, capsys) -> None:
        with pytest.raises(SystemExit):
            run(["--help"])
        out = capsys.readouterr().out
        assert "--api-key" in out
        assert "OLLAMA_API_KEY" in out

    @pytest.mark.parametrize("argv", [["--size=huge"], ["--position=center"], ["--interval=abc"]])
    def test_invalid_choices_exit_2(self, argv: list[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            run(argv)
        assert exc.value.code == 2


class TestCredentialSources:

    def test_cookie_flag(self) -> None:
        mocks = run(["--cookie", "abc", "--quiet"])
        mocks["get_usage"].assert_called_once_with("abc")
        mocks["get_cookie_auto"].assert_not_called()

    def test_cookie_flag_sanitized(self) -> None:
        mocks = run(["--cookie", " abc\r\n", "--quiet"])
        mocks["get_usage"].assert_called_once_with("abc")

    def test_browser_flag(self) -> None:
        mocks = run(["--browser", "firefox", "--quiet"], BROWSERS={"firefox": lambda: " ff-cookie\n"})
        mocks["get_usage"].assert_called_once_with("ff-cookie")

    def test_browser_flag_no_cookie(self, capsys) -> None:
        with pytest.raises(SystemExit) as exc:
            run(["--browser", "firefox"], BROWSERS={"firefox": lambda: None})
        assert exc.value.code == 1
        assert "No Ollama session cookie found in firefox" in capsys.readouterr().err

    def test_browser_error_exits_1(self, capsys) -> None:
        def boom():
            raise BrowserNotFoundError("No Firefox profile found.")

        with pytest.raises(SystemExit) as exc:
            run(["--browser", "firefox"], BROWSERS={"firefox": boom})
        assert exc.value.code == 1
        assert "No Firefox profile found." in capsys.readouterr().err

    def test_env_cookie(self, monkeypatch) -> None:
        monkeypatch.setenv("OLLAMA_BROWSER_COOKIE", "env-cookie")
        mocks = run(["--quiet"])
        mocks["get_usage"].assert_called_once_with("env-cookie")
        mocks["get_cookie_auto"].assert_not_called()

    def test_env_api_key_beats_env_cookie(self, monkeypatch) -> None:
        monkeypatch.setenv("OLLAMA_BROWSER_COOKIE", "env-cookie")
        monkeypatch.setenv("OLLAMA_API_KEY", "sk-env")
        mocks = run(["--quiet"])
        mocks["get_usage_api"].assert_called_once_with("sk-env")
        mocks["get_usage"].assert_not_called()

    def test_auto_detection_fallback(self) -> None:
        mocks = run(["--quiet"])
        mocks["get_cookie_auto"].assert_called_once()
        mocks["get_usage"].assert_called_once_with("auto-cookie")

    def test_browser_flag_beats_env_api_key(self, monkeypatch) -> None:
        monkeypatch.setenv("OLLAMA_API_KEY", "sk-env")
        mocks = run(["--browser", "firefox", "--quiet"], BROWSERS={"firefox": lambda: "ff"})
        mocks["get_usage"].assert_called_once_with("ff")
        mocks["get_usage_api"].assert_not_called()

    def test_api_key_not_printed_in_debug_logs(self, caplog) -> None:
        with caplog.at_level(logging.DEBUG):
            run(["--api-key", "super-secret-key", "--quiet", "--debug"],
                **{"logging": MagicMock(DEBUG=logging.DEBUG)})
        assert all("super-secret-key" not in r.getMessage() for r in caplog.records)


class TestSingleRun:

    def test_text_output(self, capsys) -> None:
        run(["--cookie", "c"], get_usage=MagicMock(return_value=usage(42.0)))
        out = capsys.readouterr().out
        assert "Plan    : free" in out
        assert "Monthly : 42.0% used — reset at 2026-10-01T00:00:00Z" in out
        assert "Credits : $0.00" in out

    def test_json_output(self, capsys) -> None:
        run(["--cookie", "c", "--json"], get_usage=MagicMock(return_value=usage(42.0)))
        data = json.loads(capsys.readouterr().out)
        assert data["monthly"]["used_pct"] == 42.0
        assert data["source"] == "web"

    def test_quiet_prints_nothing(self, capsys) -> None:
        run(["--cookie", "c", "--quiet"])
        out, err = capsys.readouterr()
        assert out == "" and err == ""

    def test_alert_not_triggered(self) -> None:
        run(["--cookie", "c", "--quiet", "--alert", "50"], get_usage=MagicMock(return_value=usage(10.0)))

    def test_alert_triggered_on_any_period(self) -> None:
        with pytest.raises(SystemExit) as exc:
            run(["--cookie", "c", "--quiet", "--alert", "50"],
                get_usage=MagicMock(return_value=usage(10.0, session_pct=90.0)))
        assert exc.value.code == 1

    def test_alert_message_on_stderr(self, capsys) -> None:
        with pytest.raises(SystemExit):
            run(["--cookie", "c", "--alert", "5"])
        assert "Warning: usage exceeds 5.0%" in capsys.readouterr().err

    @pytest.mark.parametrize("error", [AuthError("expired"), ParseError("bad html"), NetworkError("down")])
    def test_errors_exit_1(self, error, capsys) -> None:
        with pytest.raises(SystemExit) as exc:
            run(["--cookie", "c"], get_usage=MagicMock(side_effect=error))
        assert exc.value.code == 1
        assert f"Error: {error}" in capsys.readouterr().err

    def test_interval_without_watch_warns(self, capsys) -> None:
        run(["--cookie", "c", "--quiet", "--interval", "60"])
        assert "--interval has no effect without --watch" in capsys.readouterr().err

    def test_default_interval_does_not_warn(self, capsys) -> None:
        run(["--cookie", "c", "--quiet"])
        assert "--interval" not in capsys.readouterr().err

    def test_debug_configures_logging(self) -> None:
        with patch.object(cli.logging, "basicConfig") as basic:
            run(["--cookie", "c", "--quiet", "--debug"])
        assert basic.call_args.kwargs["level"] == logging.DEBUG

    def test_no_debug_by_default(self) -> None:
        with patch.object(cli.logging, "basicConfig") as basic:
            run(["--cookie", "c", "--quiet"])
        basic.assert_not_called()

    def test_windows_ansi_enabled(self) -> None:
        with patch.object(cli, "enable_windows_ansi") as enable:
            run(["--cookie", "c", "--quiet"])
        enable.assert_called_once()


class TestNotify:

    def test_notify_called(self) -> None:
        mocks = run(["--cookie", "c", "--quiet", "--notify", "--notify-threshold", "70"],
                    notify_available=MagicMock(return_value=True))
        data, threshold, state = mocks["check_and_notify"].call_args.args
        assert data["monthly"]["used_pct"] == 10.0
        assert threshold == 70.0
        assert isinstance(state, cli.NotifyState)

    def test_notify_not_called_without_flag(self) -> None:
        mocks = run(["--cookie", "c", "--quiet"])
        mocks["check_and_notify"].assert_not_called()

    def test_warning_when_plyer_missing(self, capsys) -> None:
        run(["--cookie", "c", "--quiet", "--notify"], notify_available=MagicMock(return_value=False))
        assert "--notify requires plyer" in capsys.readouterr().err

    def test_no_warning_when_plyer_available(self, capsys) -> None:
        run(["--cookie", "c", "--quiet", "--notify"], notify_available=MagicMock(return_value=True))
        assert "plyer" not in capsys.readouterr().err


class TestWatch:

    def test_single_iteration_then_stop(self, capsys) -> None:
        mocks = run(["--cookie", "c", "--watch"])
        mocks["get_usage"].assert_called_once()
        mocks["_watch_countdown"].assert_called_once_with(30)
        out = capsys.readouterr().out
        assert "\033[2J\033[H" in out
        assert "Stopped." in out

    def test_multiple_iterations(self) -> None:
        mocks = run(["--cookie", "c", "--watch", "--quiet"],
                    _watch_countdown=MagicMock(side_effect=[None, None, KeyboardInterrupt]))
        assert mocks["get_usage"].call_count == 3

    def test_network_error_retries(self, capsys) -> None:
        mocks = run(["--cookie", "c", "--watch", "--quiet", "--interval", "15"],
                    get_usage=MagicMock(side_effect=[NetworkError("down"), usage()]),
                    _watch_countdown=MagicMock(side_effect=[None, KeyboardInterrupt]))
        assert mocks["get_usage"].call_count == 2
        assert "Network error: down — retrying in 15s" in capsys.readouterr().err

    def test_auth_error_stops_watch(self) -> None:
        with pytest.raises(SystemExit) as exc:
            run(["--cookie", "c", "--watch"], get_usage=MagicMock(side_effect=AuthError("expired")))
        assert exc.value.code == 1

    def test_alert_in_watch_exits_1_after_stop(self) -> None:
        with pytest.raises(SystemExit) as exc:
            run(["--cookie", "c", "--watch", "--quiet", "--alert", "5"])
        assert exc.value.code == 1

    def test_notify_each_iteration_shares_state(self) -> None:
        mocks = run(["--cookie", "c", "--watch", "--quiet", "--notify"],
                    notify_available=MagicMock(return_value=True),
                    _watch_countdown=MagicMock(side_effect=[None, KeyboardInterrupt]))
        states = [c.args[2] for c in mocks["check_and_notify"].call_args_list]
        assert len(states) == 2 and states[0] is states[1]

    def test_watch_uses_api(self) -> None:
        mocks = run(["--api-key", "sk", "--watch", "--quiet"],
                    _watch_countdown=MagicMock(side_effect=[None, KeyboardInterrupt]))
        assert mocks["get_usage_api"].call_count == 2
        mocks["get_usage"].assert_not_called()


class TestWatchCountdown:

    def test_counts_down_and_clears(self, capsys) -> None:
        with patch.object(cli.time, "sleep") as sleep:
            cli._watch_countdown(2)
        assert sleep.call_count == 20
        out = capsys.readouterr().out
        assert "Refreshing in 2s" in out
        assert "Refreshing in 1s" in out
        assert out.endswith("\r")


class TestWidgetFlag:

    @pytest.fixture(autouse=True)
    def _tk(self) -> None:
        pytest.importorskip("tkinter")

    def test_launches_widget_with_cookie(self) -> None:
        with patch("ollama_usage.widget.launch_widget") as launch:
            mocks = run(["--cookie", "c", "--widget", "--theme", "light", "--size", "compact",
                         "--opacity", "0.5", "--position", "bottom-left", "--interval", "5"])
        launch.assert_called_once_with(cookie="c", api_key=None, interval=10, theme="light",
                                       size="compact", opacity=0.5, position="bottom-left")
        mocks["get_usage"].assert_not_called()

    def test_launches_widget_with_api_key(self) -> None:
        with patch("ollama_usage.widget.launch_widget") as launch:
            run(["--api-key", "sk", "--widget"])
        assert launch.call_args.kwargs["api_key"] == "sk"
        assert launch.call_args.kwargs["cookie"] is None

    def test_widget_skips_watch_and_alert(self) -> None:
        with patch("ollama_usage.widget.launch_widget"):
            mocks = run(["--cookie", "c", "--widget", "--watch", "--alert", "1"])
        mocks["_watch_countdown"].assert_not_called()


class TestDisplayEdgeCases:

    def test_spend_without_period(self, capsys) -> None:
        data = usage()
        data["spend"] = {"cost_usd": 3.0, "period": None}
        cli.display(data, as_json=False, quiet=False)
        assert "Spend   : $3.00\n" in capsys.readouterr().out

    def test_no_periods(self, capsys) -> None:
        data = usage(monthly_pct=None)
        cli.display(data, as_json=False, quiet=False)
        out = capsys.readouterr().out
        assert "used" not in out
        assert "Plan    : free" in out

    def test_legacy_order(self, capsys) -> None:
        data = usage(monthly_pct=None, session_pct=1.0)
        data["weekly"] = {"used_pct": 2.0, "resets_at": None, "models": []}
        cli.display(data, as_json=False, quiet=False)
        out = capsys.readouterr().out
        assert out.index("Session") < out.index("Weekly")

    def test_quiet_beats_json(self, capsys) -> None:
        cli.display(usage(), as_json=True, quiet=True)
        assert capsys.readouterr().out == ""

    @pytest.mark.parametrize("pct,color", [(10.0, "\033[32m"), (60.0, "\033[33m"), (95.0, "\033[31m")])
    def test_forced_colors(self, monkeypatch, pct: float, color: str) -> None:
        monkeypatch.delenv("NO_COLOR")
        monkeypatch.setenv("FORCE_COLOR", "1")
        assert cli._color_pct(pct) == f"{color}{pct}%\033[0m"

    def test_no_color_env(self) -> None:
        assert cli._color_pct(95.0) == "95.0%"
