"""Tests for ollama_usage.widget (pure helpers, no display required).

Le module est importé via importorskip : si tkinter n'est pas compilé dans
l'interpréteur, les tests sont sautés proprement au lieu d'échouer à la
collecte. Aucun `Tk()` n'est instancié — on ne teste que les fonctions pures
et les constantes, donc pas besoin de serveur X / DISPLAY.
"""

from __future__ import annotations

import pytest

pytest.importorskip("tkinter")

from ollama_usage import widget
from ollama_usage.widget import (
    POSITIONS,
    THEMES,
    _fmt_countdown,
    _pct_color,
    _seconds_until,
    _truncate,
)

_THEME = {"green": "G", "yellow": "Y", "red": "R"}


# ---------------------------------------------------------------------------
# _pct_color
# ---------------------------------------------------------------------------

class TestPctColor:

    @pytest.mark.parametrize("pct,expected", [
        (0.0, "G"),
        (25.0, "G"),
        (49.9, "G"),
        (50.0, "Y"),
        (65.0, "Y"),
        (79.9, "Y"),
        (80.0, "R"),
        (99.9, "R"),
        (100.0, "R"),
        (150.0, "R"),
    ])
    def test_thresholds(self, pct: float, expected: str) -> None:
        assert _pct_color(pct, _THEME) == expected


# ---------------------------------------------------------------------------
# _seconds_until
# ---------------------------------------------------------------------------

class TestSecondsUntil:

    def test_far_future_is_positive(self) -> None:
        assert _seconds_until("2999-01-01T00:00:00Z") > 0

    def test_past_is_zero(self) -> None:
        assert _seconds_until("2000-01-01T00:00:00Z") == 0

    def test_handles_z_suffix(self) -> None:
        # ne doit pas lever malgré le 'Z' (non géré par fromisoformat avant 3.11)
        assert _seconds_until("2999-12-31T23:59:59Z") > 0

    def test_invalid_string_is_zero(self) -> None:
        assert _seconds_until("not-a-date") == 0

    def test_empty_string_is_zero(self) -> None:
        assert _seconds_until("") == 0

    def test_naive_datetime_is_zero(self) -> None:
        # sans timezone, la soustraction avec un now() aware lève → 0
        assert _seconds_until("2999-01-01T00:00:00") == 0

    def test_garbage_is_zero(self) -> None:
        assert _seconds_until("2026-13-45T99:99:99Z") == 0


# ---------------------------------------------------------------------------
# _fmt_countdown
# ---------------------------------------------------------------------------

class TestFmtCountdown:

    @pytest.mark.parametrize("seconds,expected", [
        (0, "now"),
        (-1, "now"),
        (-9999, "now"),
        (1, "1s"),
        (30, "30s"),
        (59, "59s"),
        (60, "1m 00s"),
        (90, "1m 30s"),
        (3599, "59m 59s"),
        (3600, "1h 00m"),
        (3661, "1h 01m"),
        (7325, "2h 02m"),
    ])
    def test_formatting(self, seconds: int, expected: str) -> None:
        assert _fmt_countdown(seconds) == expected


# ---------------------------------------------------------------------------
# _truncate
# ---------------------------------------------------------------------------

class TestTruncate:

    def test_shorter_than_max_unchanged(self) -> None:
        assert _truncate("abc", 5) == "abc"

    def test_exact_length_unchanged(self) -> None:
        assert _truncate("abc", 3) == "abc"

    def test_longer_is_truncated_with_ellipsis(self) -> None:
        assert _truncate("abcdef", 4) == "abc…"

    def test_ellipsis_keeps_max_length(self) -> None:
        result = _truncate("abcdefghij", 5)
        assert len(result) == 5
        assert result.endswith("…")

    def test_empty_string(self) -> None:
        assert _truncate("", 5) == ""


# ---------------------------------------------------------------------------
# THEMES / POSITIONS — constantes
# ---------------------------------------------------------------------------

class TestThemesAndPositions:

    _REQUIRED_THEME_KEYS = {
        "bg", "fg", "sub", "bar_bg", "border", "green", "yellow", "red",
    }

    @pytest.mark.parametrize("name", ["dark", "light", "minimal"])
    def test_theme_has_all_keys(self, name: str) -> None:
        assert self._REQUIRED_THEME_KEYS <= set(THEMES[name])

    @pytest.mark.parametrize("name", ["dark", "light", "minimal"])
    def test_theme_colors_are_hex(self, name: str) -> None:
        import re
        for value in THEMES[name].values():
            assert re.match(r"^#[0-9a-fA-F]{6}$", value)

    def test_positions_keys(self) -> None:
        assert set(POSITIONS) == {"top-left", "top-right", "bottom-left", "bottom-right"}

    @pytest.mark.parametrize("name", ["top-left", "top-right", "bottom-left", "bottom-right"])
    def test_positions_return_coordinate_tuple(self, name: str) -> None:
        x, y = POSITIONS[name](1920, 1080, 240, 200)
        assert isinstance(x, int) and isinstance(y, int)

    def test_top_left_is_origin_corner(self) -> None:
        assert POSITIONS["top-left"](1920, 1080, 240, 200) == (10, 10)

    def test_top_right_is_within_screen(self) -> None:
        x, y = POSITIONS["top-right"](1920, 1080, 240, 200)
        assert x == 1920 - 240 - 10
        assert y == 10


# ---------------------------------------------------------------------------
# Régression : check_dependencies supprimée
# ---------------------------------------------------------------------------

class TestRegressions:

    def test_check_dependencies_removed(self) -> None:
        """--widget ne doit plus exiger cryptography quand le cookie est fourni."""
        assert not hasattr(widget, "check_dependencies")
