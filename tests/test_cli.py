"""Tests for ollama_usage.cli."""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from ollama_usage.cli import _sanitize_cookie, _check_alert, display


# ---------------------------------------------------------------------------
# _sanitize_cookie — HTTP Header Injection
# ---------------------------------------------------------------------------

class TestSanitizeCookie:

    def test_strips_leading_trailing_whitespace(self) -> None:
        assert _sanitize_cookie("  abc  ") == "abc"

    def test_removes_carriage_return(self) -> None:
        # \r permet d'injecter des headers HTTP supplémentaires
        assert _sanitize_cookie("abc\rdef") == "abcdef"

    def test_removes_newline(self) -> None:
        # \n permet d'injecter des headers HTTP supplémentaires
        assert _sanitize_cookie("abc\ndef") == "abcdef"

    def test_removes_null_byte(self) -> None:
        assert _sanitize_cookie("abc\0def") == "abcdef"

    def test_removes_crlf_injection(self) -> None:
        # Cas classique d'HTTP Header Injection : \r\n
        payload = "legit\r\nX-Injected: evil"
        assert "\r" not in _sanitize_cookie(payload)
        assert "\n" not in _sanitize_cookie(payload)

    def test_valid_cookie_unchanged(self) -> None:
        # Un vrai cookie ne doit pas être altéré
        cookie = "abcdefghijklmnopqrstuvwxyz0123456789_-"
        assert _sanitize_cookie(cookie) == cookie

    def test_empty_string(self) -> None:
        assert _sanitize_cookie("") == ""

    def test_only_whitespace(self) -> None:
        assert _sanitize_cookie("   ") == ""

    def test_multiple_injections(self) -> None:
        assert _sanitize_cookie("a\r\nb\0c\rd") == "abcd"


# ---------------------------------------------------------------------------
# _check_alert — logique d'alerte quota
# ---------------------------------------------------------------------------

def make_data(session_pct: float = 0.0, weekly_pct: float = 0.0) -> dict:
    return {
        "plan": "free",
        "session": {"used_pct": session_pct, "resets_at": "2026-04-04T17:00:00Z"},
        "weekly":  {"used_pct": weekly_pct,  "resets_at": "2026-04-06T00:00:00Z"},
    }


class TestCheckAlert:

    def test_no_alert_when_threshold_is_none(self) -> None:
        assert _check_alert(make_data(99.9, 99.9), None, quiet=True) is False

    def test_triggers_on_session_above_threshold(self) -> None:
        assert _check_alert(make_data(session_pct=85.0), 80.0, quiet=True) is True

    def test_triggers_on_weekly_above_threshold(self) -> None:
        assert _check_alert(make_data(weekly_pct=85.0), 80.0, quiet=True) is True

    def test_no_trigger_when_both_below(self) -> None:
        assert _check_alert(make_data(50.0, 50.0), 80.0, quiet=True) is False

    def test_exactly_at_threshold_does_not_trigger(self) -> None:
        # > threshold, pas >=
        assert _check_alert(make_data(80.0, 80.0), 80.0, quiet=True) is False

    def test_one_above_one_below_triggers(self) -> None:
        assert _check_alert(make_data(90.0, 10.0), 80.0, quiet=True) is True

    def test_quiet_suppresses_stderr_output(self, capsys) -> None:
        _check_alert(make_data(90.0), 80.0, quiet=True)
        assert capsys.readouterr().err == ""

    def test_not_quiet_prints_to_stderr(self, capsys) -> None:
        _check_alert(make_data(90.0), 80.0, quiet=False)
        assert capsys.readouterr().err != ""


# ---------------------------------------------------------------------------
# display — sortie JSON vs texte
# ---------------------------------------------------------------------------

class TestDisplay:

    def test_quiet_prints_nothing(self, capsys) -> None:
        display(make_data(50.0, 50.0), as_json=False, quiet=True)
        out, err = capsys.readouterr()
        assert out == "" and err == ""

    def test_json_output_is_valid(self, capsys) -> None:
        import json
        display(make_data(33.3, 66.6), as_json=True, quiet=False)
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["session"]["used_pct"] == 33.3
        assert parsed["weekly"]["used_pct"] == 66.6

    def test_text_output_contains_plan(self, capsys) -> None:
        display(make_data(), as_json=False, quiet=False)
        out = capsys.readouterr().out
        assert "free" in out

    def test_text_output_contains_percentages(self, capsys) -> None:
        display(make_data(42.0, 77.0), as_json=False, quiet=False)
        out = capsys.readouterr().out
        assert "42.0" in out
        assert "77.0" in out


# ---------------------------------------------------------------------------
# Interval clamping
# ---------------------------------------------------------------------------

class TestIntervalClamping:
    """Vérifie que l'intervalle est borné entre 10 et 3600 dans main()."""

    def _run_main_interval(self, interval_arg: int) -> int:
        """Lance main() et retourne l'intervalle effectivement utilisé dans _watch_countdown."""
        captured = {}

        def fake_countdown(iv):
            captured["interval"] = iv
            raise KeyboardInterrupt  # stoppe la boucle watch après 1 tour

        fake_data = make_data(10.0, 10.0)

        with patch("ollama_usage.cli.get_cookie_auto", return_value="fake-cookie"), \
             patch("ollama_usage.cli.get_usage", return_value=fake_data), \
             patch("ollama_usage.cli._watch_countdown", side_effect=fake_countdown), \
             patch("ollama_usage.cli.sys.stdout.write"), \
             patch("sys.argv", ["ollama-usage", "--watch", "--quiet", "--interval", str(interval_arg)]):
            try:
                from ollama_usage.cli import main
                main()
            except SystemExit:
                pass

        return captured.get("interval", -1)

    def test_interval_below_min_is_clamped_to_10(self) -> None:
        assert self._run_main_interval(0) == 10

    def test_interval_of_1_is_clamped_to_10(self) -> None:
        assert self._run_main_interval(1) == 10

    def test_interval_above_max_is_clamped_to_3600(self) -> None:
        assert self._run_main_interval(9999) == 3600

    def test_valid_interval_is_unchanged(self) -> None:
        assert self._run_main_interval(60) == 60

    def test_default_interval_30_is_unchanged(self) -> None:
        assert self._run_main_interval(30) == 30