"""Tests for OllamaWidget behaviour, using mocked Tk objects (no display needed)."""

from __future__ import annotations

import json
import threading
from unittest.mock import MagicMock, call, patch

import pytest

pytest.importorskip("tkinter")

from ollama_usage import widget
from ollama_usage.exceptions import AuthError, NetworkError
from ollama_usage.widget import THEMES, OllamaWidget, launch_widget

FUTURE = "2099-01-01T00:00:00Z"


def make_widget(size: str = "full", data: dict | None = None, error: str | None = None) -> OllamaWidget:
    w = OllamaWidget.__new__(OllamaWidget)
    w._cookie = "cookie"
    w._api_key = None
    w._interval = 30
    w._theme = THEMES["dark"]
    w._size = size
    w._opacity = 0.9
    w._position = None
    w._data = data
    w._error = error
    w._after_id = None
    w._is_running = True
    w._is_fetching = threading.Event()
    w._drag_x = w._drag_y = 0
    w._root = MagicMock()
    w._canvas = MagicMock()
    w._menu = MagicMock()
    return w


def texts(w: OllamaWidget) -> list[str]:
    return [c.kwargs.get("text") for c in w._canvas.create_text.call_args_list]


def rect_fills(w: OllamaWidget) -> list[str]:
    return [c.kwargs.get("fill") for c in w._canvas.create_rectangle.call_args_list]


def legacy_data(session_pct: float = 30.0, weekly_pct: float = 60.0) -> dict:
    models = [
        {"model": "qwen3-coder:480b", "requests": 42, "share_pct": 55.0, "color": "#ffcc00"},
        {"model": "gpt-oss:120b", "requests": 30, "share_pct": 40.0, "color": "#34c759"},
        {"model": "glm-4.6", "requests": 4, "share_pct": 5.0, "color": "#5ac8fa"},
    ]
    return {
        "plan": "pro",
        "session": {"used_pct": session_pct, "resets_at": FUTURE, "models": models},
        "weekly": {"used_pct": weekly_pct, "resets_at": FUTURE, "models": models},
        "monthly": None,
        "credits_balance": 5.0,
        "spend": None,
        "source": "web",
    }


def api_data(pct: float = 18.4) -> dict:
    return {
        "plan": None,
        "session": None,
        "weekly": None,
        "monthly": {
            "used_pct": pct,
            "resets_at": None,
            "models": [{"model": "deepseek-v3.1:671b", "requests": 112, "share_pct": None, "color": None}],
        },
        "credits_balance": None,
        "spend": {"cost_usd": 1.5, "period": "last_4_weeks", "starting_at": None, "ending_at": None},
        "source": "api",
    }


def web_monthly_data(pct: float = 18.4, balance: float | None = 0.0) -> dict:
    return {
        "plan": "free",
        "session": None,
        "weekly": None,
        "monthly": {
            "used_pct": pct,
            "resets_at": FUTURE,
            "models": [{"model": "deepseek-v3.1:671b", "requests": 112, "share_pct": 100.0, "color": "#22c55e"}],
        },
        "credits_balance": balance,
        "spend": None,
        "source": "web",
    }


class TestInit:

    def _build(self, **kwargs) -> OllamaWidget:
        with patch.object(widget, "tk"), \
             patch.object(OllamaWidget, "_restore_position"), \
             patch.object(OllamaWidget, "_fetch_async") as fetch:
            w = OllamaWidget(**kwargs)
        fetch.assert_called_once()
        return w

    def test_defaults(self) -> None:
        w = self._build(cookie="c")
        assert w._interval == 30
        assert w._theme is THEMES["dark"]
        assert w._size == "full"
        assert w._api_key is None

    def test_interval_min_10(self) -> None:
        assert self._build(cookie="c", interval=1)._interval == 10

    @pytest.mark.parametrize("opacity,expected", [(5.0, 1.0), (0.0, 0.1), (0.5, 0.5)])
    def test_opacity_clamped(self, opacity: float, expected: float) -> None:
        assert self._build(cookie="c", opacity=opacity)._opacity == expected

    def test_unknown_theme_falls_back_to_dark(self) -> None:
        assert self._build(cookie="c", theme="neon")._theme is THEMES["dark"]

    @pytest.mark.parametrize("theme", ["light", "minimal"])
    def test_known_theme(self, theme: str) -> None:
        assert self._build(cookie="c", theme=theme)._theme is THEMES[theme]

    def test_api_key_stored(self) -> None:
        assert self._build(api_key="sk")._api_key == "sk"


class TestSetup:

    def test_window_attributes(self) -> None:
        w = make_widget()
        w._setup_window()
        w._root.overrideredirect.assert_called_once_with(True)
        w._root.wm_attributes.assert_any_call("-topmost", True)
        w._root.wm_attributes.assert_any_call("-alpha", 0.9)
        w._root.title.assert_called_once_with("ollama-usage")

    @pytest.mark.parametrize("size,geometry", [("full", "240x200"), ("compact", "240x72")])
    def test_canvas_geometry(self, size: str, geometry: str) -> None:
        w = make_widget(size=size)
        old_canvas = w._canvas
        with patch.object(widget, "tk") as tk_mock:
            w._setup_canvas()
        old_canvas.destroy.assert_called_once()
        w._root.geometry.assert_called_once_with(geometry)
        assert w._canvas is tk_mock.Canvas.return_value

    def test_canvas_bindings(self) -> None:
        w = make_widget()
        with patch.object(widget, "tk"):
            w._setup_canvas()
        events = {c.args[0] for c in w._canvas.bind.call_args_list}
        assert events == {"<ButtonPress-1>", "<B1-Motion>", "<ButtonRelease-1>", "<Button-3>"}
        assert w._root.bind.call_count == 4

    def test_menu_entries(self) -> None:
        w = make_widget()
        w._setup_menu()
        labels = [c.kwargs["label"] for c in w._menu.add_command.call_args_list]
        assert any("Refresh" in label for label in labels)
        assert any("Toggle size" in label for label in labels)
        assert any("Close" in label for label in labels)
        w._menu.add_separator.assert_called_once()


class TestDrawCompact:

    def test_loading(self) -> None:
        w = make_widget(size="compact")
        w._draw()
        assert "Loading…" in texts(w)

    def test_error(self) -> None:
        w = make_widget(size="compact", error="Network error")
        w._draw()
        assert "Network error" in texts(w)
        red_calls = [c for c in w._canvas.create_text.call_args_list if c.kwargs.get("text") == "Network error"]
        assert red_calls[0].kwargs["fill"] == THEMES["dark"]["red"]

    def test_legacy_rows(self) -> None:
        w = make_widget(size="compact", data=legacy_data(30.0, 60.0))
        w._draw()
        t = texts(w)
        assert "Session:" in t and "30.0%" in t
        assert "Weekly:" in t and "60.0%" in t

    def test_monthly_row_only(self) -> None:
        w = make_widget(size="compact", data=api_data(18.4))
        w._draw()
        t = texts(w)
        assert "Monthly:" in t and "18.4%" in t
        assert "Session:" not in t

    def test_clears_canvas_first(self) -> None:
        w = make_widget(size="compact", data=api_data())
        w._draw()
        w._canvas.delete.assert_called_once_with("all")

    def test_status_dot_green_when_ok(self) -> None:
        w = make_widget(size="compact", data=api_data())
        w._draw()
        dot = next(c for c in w._canvas.create_text.call_args_list if c.kwargs.get("text") == "●")
        assert dot.kwargs["fill"] == THEMES["dark"]["green"]


class TestDrawFull:

    def test_loading(self) -> None:
        w = make_widget()
        w._draw()
        assert "Loading…" in texts(w)
        assert "ollama" in texts(w)

    def test_error_dot_red(self) -> None:
        w = make_widget(data=api_data(), error="Cookie expired")
        w._draw()
        assert "Cookie expired" in texts(w)
        dot = next(c for c in w._canvas.create_text.call_args_list if c.kwargs.get("text") == "●")
        assert dot.kwargs["fill"] == THEMES["dark"]["red"]

    def test_header_with_plan(self) -> None:
        w = make_widget(data=legacy_data())
        w._draw()
        assert "ollama · Pro" in texts(w)

    def test_header_without_plan(self) -> None:
        w = make_widget(data=api_data())
        w._draw()
        assert "ollama" in texts(w)
        assert not any(t and t.startswith("ollama ·") for t in texts(w))

    def test_labels_and_percentages(self) -> None:
        w = make_widget(data=legacy_data(30.0, 60.0))
        w._draw()
        t = texts(w)
        assert {"Session", "Weekly", "30.0%", "60.0%"} <= set(t)

    def test_segments_use_model_colors(self) -> None:
        w = make_widget(data=legacy_data(30.0, 60.0))
        w._draw()
        fills = rect_fills(w)
        # bar segments + legend squares, for both periods
        assert fills.count("#ffcc00") == 4

    def test_monochrome_bar_without_shares(self) -> None:
        w = make_widget(data=api_data(18.4))
        w._draw()
        fills = rect_fills(w)
        assert THEMES["dark"]["green"] in fills
        assert THEMES["dark"]["sub"] in fills  # legend square without color

    def test_no_fill_at_zero_percent(self) -> None:
        w = make_widget(data=api_data(0.0))
        w._draw()
        fills = rect_fills(w)
        assert THEMES["dark"]["green"] not in fills

    def test_fill_capped_at_100(self) -> None:
        w = make_widget(data=api_data(150.0))
        w._draw()
        widths = [c.args[2] - c.args[0] for c in w._canvas.create_rectangle.call_args_list]
        assert max(widths) <= widget._BAR_W

    def test_legend_lists_models(self) -> None:
        w = make_widget(data=legacy_data())
        w._draw()
        t = texts(w)
        assert "qwen3-coder:48…" in t
        assert "42req" in t

    def test_legend_limited_to_max_models(self) -> None:
        data = api_data()
        data["monthly"]["models"] = [
            {"model": f"m{i}", "requests": i, "share_pct": None, "color": None} for i in range(10)
        ]
        w = make_widget(data=data)
        w._draw()
        assert sum(1 for t in texts(w) if t and t.endswith("req")) == widget._MAX_MODELS

    def test_countdown_when_reset_date(self) -> None:
        w = make_widget(data=web_monthly_data())
        w._draw()
        assert any(t and t.startswith("resets in") for t in texts(w))

    def test_no_countdown_without_reset_date(self) -> None:
        w = make_widget(data=api_data())
        w._draw()
        assert not any(t and t.startswith("resets in") for t in texts(w))

    def test_spend_extra(self) -> None:
        w = make_widget(data=api_data())
        w._draw()
        assert "spend $1.50 (4w)" in texts(w)

    def test_credits_extra(self) -> None:
        w = make_widget(data=web_monthly_data(balance=12.5))
        w._draw()
        assert "credits $12.50" in texts(w)

    def test_credits_and_spend_joined(self) -> None:
        data = web_monthly_data(balance=1.0)
        data["spend"] = {"cost_usd": 2.0}
        w = make_widget(data=data)
        w._draw()
        assert "credits $1.00  ·  spend $2.00 (4w)" in texts(w)

    def test_extras_hidden_when_no_room(self) -> None:
        w = make_widget(data=legacy_data())
        w._draw()
        assert not any(t and t.startswith("credits") for t in texts(w))


class TestToggleSize:

    @pytest.mark.parametrize("start,expected", [("full", "compact"), ("compact", "full")])
    def test_toggle(self, start: str, expected: str) -> None:
        w = make_widget(size=start)
        with patch.object(w, "_setup_canvas") as setup, patch.object(w, "_draw") as draw:
            w._toggle_size()
        assert w._size == expected
        setup.assert_called_once()
        draw.assert_called_once()


class TestFetch:

    def test_uses_cookie(self) -> None:
        w = make_widget()
        with patch.object(widget, "get_usage", return_value={"x": 1}) as web, \
             patch.object(widget, "get_usage_api") as api:
            w._fetch()
        web.assert_called_once_with("cookie")
        api.assert_not_called()
        assert w._data == {"x": 1}
        assert w._error is None

    def test_api_key_takes_precedence(self) -> None:
        w = make_widget()
        w._api_key = "sk"
        with patch.object(widget, "get_usage_api", return_value={"y": 2}) as api, \
             patch.object(widget, "get_usage") as web:
            w._fetch()
        api.assert_called_once_with("sk")
        web.assert_not_called()
        assert w._data == {"y": 2}

    def test_network_error(self) -> None:
        w = make_widget()
        with patch.object(widget, "get_usage", side_effect=NetworkError("down")):
            w._fetch()
        assert w._error == "Network error"

    def test_auth_error_message(self) -> None:
        w = make_widget()
        with patch.object(widget, "get_usage", side_effect=AuthError("Cookie expired")):
            w._fetch()
        assert w._error == "Cookie expired"

    def test_error_keeps_previous_data(self) -> None:
        w = make_widget(data={"old": True})
        with patch.object(widget, "get_usage", side_effect=NetworkError("down")):
            w._fetch()
        assert w._data == {"old": True}

    def test_success_clears_error(self) -> None:
        w = make_widget(error="Network error")
        with patch.object(widget, "get_usage", return_value={}):
            w._fetch()
        assert w._error is None

    def test_schedules_draw_and_next_fetch(self) -> None:
        w = make_widget()
        w._root.after.return_value = "after-id"
        with patch.object(widget, "get_usage", return_value={}):
            w._fetch()
        assert w._root.after.call_args_list == [call(0, w._draw), call(30_000, w._fetch_async)]
        assert w._after_id == "after-id"

    def test_clears_fetching_flag(self) -> None:
        w = make_widget()
        w._is_fetching.set()
        with patch.object(widget, "get_usage", side_effect=NetworkError("down")):
            w._fetch()
        assert not w._is_fetching.is_set()

    def test_no_scheduling_when_stopped(self) -> None:
        w = make_widget()
        w._is_running = False
        with patch.object(widget, "get_usage", return_value={}):
            w._fetch()
        w._root.after.assert_not_called()

    def test_scheduling_error_swallowed(self) -> None:
        w = make_widget()
        w._root.after.side_effect = RuntimeError("main thread is not in main loop")
        with patch.object(widget, "get_usage", return_value={}):
            w._fetch()


class TestFetchAsync:

    def test_starts_daemon_thread(self) -> None:
        w = make_widget()
        with patch.object(widget.threading, "Thread") as thread:
            w._fetch_async()
        thread.assert_called_once_with(target=w._fetch, daemon=True, name="ollama-fetch")
        thread.return_value.start.assert_called_once()
        assert w._is_fetching.is_set()

    def test_skips_when_already_fetching(self) -> None:
        w = make_widget()
        w._is_fetching.set()
        with patch.object(widget.threading, "Thread") as thread:
            w._fetch_async()
        thread.assert_not_called()

    def test_cancels_pending_refresh(self) -> None:
        w = make_widget()
        w._after_id = "pending"
        with patch.object(widget.threading, "Thread"):
            w._fetch_async()
        w._root.after_cancel.assert_called_once_with("pending")


class TestPosition:

    @pytest.fixture
    def state_file(self, tmp_path, monkeypatch):
        path = tmp_path / "state.json"
        monkeypatch.setattr(widget, "_STATE_FILE", path)
        return path

    def _widget(self, size: str = "full", position: str | None = None) -> OllamaWidget:
        w = make_widget(size=size)
        w._position = position
        w._root.winfo_screenwidth.return_value = 1920
        w._root.winfo_screenheight.return_value = 1080
        return w

    def test_explicit_position(self, state_file) -> None:
        w = self._widget(position="top-left")
        w._restore_position()
        w._root.geometry.assert_called_once_with("+10+10")

    def test_explicit_position_ignores_state_file(self, state_file) -> None:
        state_file.write_text(json.dumps({"x": 100, "y": 200}), encoding="utf-8")
        w = self._widget(position="bottom-right")
        w._restore_position()
        w._root.geometry.assert_called_once_with(f"+{1920 - 240 - 10}+{1080 - 200 - 50}")

    def test_default_without_state(self, state_file) -> None:
        w = self._widget()
        w._restore_position()
        w._root.geometry.assert_called_once_with("+1670+10")

    def test_restores_saved_state(self, state_file) -> None:
        state_file.write_text(json.dumps({"x": 100, "y": 200}), encoding="utf-8")
        w = self._widget()
        w._restore_position()
        w._root.geometry.assert_called_once_with("+100+200")

    @pytest.mark.parametrize("state", [
        {"x": 5000, "y": 10},
        {"x": 10, "y": -5},
        {"x": "100", "y": 200},
        {"x": 1.5, "y": 2.5},
    ])
    def test_invalid_state_uses_default(self, state_file, state: dict) -> None:
        state_file.write_text(json.dumps(state), encoding="utf-8")
        w = self._widget()
        w._restore_position()
        w._root.geometry.assert_called_once_with("+1670+10")

    def test_corrupt_state_uses_default(self, state_file) -> None:
        state_file.write_text("{not json", encoding="utf-8")
        w = self._widget()
        w._restore_position()
        w._root.geometry.assert_called_once_with("+1670+10")

    def test_unknown_position_falls_back_to_state(self, state_file) -> None:
        state_file.write_text(json.dumps({"x": 42, "y": 43}), encoding="utf-8")
        w = self._widget(position="center")
        w._restore_position()
        w._root.geometry.assert_called_once_with("+42+43")

    def test_save_position(self, state_file) -> None:
        w = self._widget()
        w._root.winfo_x.return_value = 12
        w._root.winfo_y.return_value = 34
        w._save_position()
        assert json.loads(state_file.read_text(encoding="utf-8")) == {"x": 12, "y": 34}

    def test_save_position_error_swallowed(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(widget, "_STATE_FILE", tmp_path)  # a directory: write fails
        w = self._widget()
        w._root.winfo_x.return_value = 1
        w._root.winfo_y.return_value = 1
        w._save_position()

    def test_save_then_restore_roundtrip(self, state_file) -> None:
        w = self._widget()
        w._root.winfo_x.return_value = 300
        w._root.winfo_y.return_value = 400
        w._save_position()
        w2 = self._widget()
        w2._restore_position()
        w2._root.geometry.assert_called_once_with("+300+400")


class TestInteractions:

    def test_drag(self) -> None:
        w = make_widget()
        w._root.winfo_x.return_value = 100
        w._root.winfo_y.return_value = 200
        w._on_drag_start(MagicMock(x_root=110, y_root=220))
        assert (w._drag_x, w._drag_y) == (10, 20)
        w._on_drag_motion(MagicMock(x_root=500, y_root=600))
        w._root.geometry.assert_called_once_with("+490+580")

    def test_drag_end_saves_position(self) -> None:
        w = make_widget()
        with patch.object(w, "_save_position") as save:
            w._on_drag_end(MagicMock())
        save.assert_called_once()

    def test_show_menu(self) -> None:
        w = make_widget()
        w._root.winfo_exists.return_value = True
        w._show_menu(MagicMock(x_root=5, y_root=6))
        w._menu.tk_popup.assert_called_once_with(5, 6)

    def test_show_menu_when_destroyed(self) -> None:
        w = make_widget()
        w._root.winfo_exists.return_value = False
        w._show_menu(MagicMock())
        w._menu.tk_popup.assert_not_called()

    def test_show_menu_tcl_error_swallowed(self) -> None:
        w = make_widget()
        w._root.winfo_exists.side_effect = widget.tk.TclError("gone")
        w._show_menu(MagicMock())

    def test_quit(self) -> None:
        w = make_widget()
        with patch.object(w, "_save_position") as save, pytest.raises(SystemExit) as exc:
            w._quit()
        assert exc.value.code == 0
        assert w._is_running is False
        save.assert_called_once()
        w._root.destroy.assert_called_once()

    def test_quit_save_error_swallowed(self) -> None:
        w = make_widget()
        with patch.object(w, "_save_position", side_effect=OSError("disk")), pytest.raises(SystemExit):
            w._quit()
        w._root.destroy.assert_called_once()

    def test_run_starts_mainloop(self) -> None:
        w = make_widget()
        w.run()
        w._root.mainloop.assert_called_once()


class TestLaunchWidget:

    def test_passes_arguments_and_runs(self) -> None:
        with patch.object(widget, "OllamaWidget") as cls:
            launch_widget(cookie="c", interval=60, theme="light", size="compact",
                          opacity=0.5, position="top-right", api_key="sk")
        cls.assert_called_once_with(cookie="c", interval=60, theme="light", size="compact",
                                    opacity=0.5, position="top-right", api_key="sk")
        cls.return_value.run.assert_called_once()

    def test_missing_tkinter(self, monkeypatch) -> None:
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "tkinter":
                raise ImportError("no tkinter")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with patch.object(widget, "OllamaWidget") as cls, \
             pytest.raises(RuntimeError, match="tkinter is not available"):
            launch_widget(cookie="c")
        cls.assert_not_called()
