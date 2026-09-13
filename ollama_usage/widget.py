"""Always-on-top desktop widget showing Ollama quota gauges.

Requires tkinter (stdlib). On minimal Linux installs:
    sudo apt install python3-tk
"""

from __future__ import annotations

import json
import logging
import pathlib
import sys
import threading
import tkinter as tk
from datetime import datetime, timezone

from ollama_usage.api import get_usage_api
from ollama_usage.exceptions import NetworkError, OllamaUsageError
from ollama_usage.scraper import get_usage, iter_periods

logger = logging.getLogger(__name__)

_STATE_FILE = pathlib.Path.home() / ".ollama-usage-widget.json"

THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "bg":     "#1e1e2e",
        "fg":     "#cdd6f4",
        "sub":    "#6c7086",
        "bar_bg": "#313244",
        "border": "#45475a",
        "green":  "#a6e3a1",
        "yellow": "#f9e2af",
        "red":    "#f38ba8",
    },
    "light": {
        "bg":     "#eff1f5",
        "fg":     "#4c4f69",
        "sub":    "#9ca0b0",
        "bar_bg": "#ccd0da",
        "border": "#bcc0cc",
        "green":  "#40a02b",
        "yellow": "#df8e1d",
        "red":    "#d20f39",
    },
    "minimal": {
        "bg":     "#0a0a0a",
        "fg":     "#f0f0f0",
        "sub":    "#666666",
        "bar_bg": "#1a1a1a",
        "border": "#2a2a2a",
        "green":  "#00e676",
        "yellow": "#ffea00",
        "red":    "#ff1744",
    },
}

POSITIONS = {
    "top-left":     lambda sw, sh, ww, wh: (10, 10),
    "top-right":    lambda sw, sh, ww, wh: (sw - ww - 10, 10),
    "bottom-left":  lambda sw, sh, ww, wh: (10, sh - wh - 50),
    "bottom-right": lambda sw, sh, ww, wh: (sw - ww - 10, sh - wh - 50),
}

_W_COMPACT = (240, 72)
_W_FULL    = (240, 200)
_BAR_W     = 200
_BAR_H     = 8
_PAD       = 14
_FONT      = "Helvetica"
_MAX_MODELS = 3           # per period


def _pct_color(pct: float, theme: dict) -> str:
    if pct < 50:
        return theme["green"]
    if pct < 80:
        return theme["yellow"]
    return theme["red"]


def _seconds_until(iso: str) -> int:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return max(0, int((dt - datetime.now(timezone.utc)).total_seconds()))
    except Exception:
        return 0


def _fmt_countdown(seconds: int) -> str:
    if seconds <= 0:
        return "now"
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s   = divmod(rem, 60)
    if d:
        return f"{d}d {h:02d}h"
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def _truncate(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


class OllamaWidget:
    """Frameless always-on-top Tkinter widget."""

    def __init__(
        self,
        cookie: str | None = None,
        interval: int   = 30,
        theme: str      = "dark",
        size: str       = "full",
        opacity: float  = 0.92,
        position: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._cookie      = cookie
        self._api_key     = api_key
        self._interval    = max(10, interval)
        self._theme       = THEMES.get(theme, THEMES["dark"])
        self._size        = size
        self._opacity     = max(0.1, min(1.0, opacity))
        self._position    = position
        self._data: dict | None  = None
        self._error: str | None  = None
        self._after_id: str | None = None
        self._is_running: bool = True
        self._is_fetching = threading.Event()
        self._drag_x = self._drag_y = 0

        self._root = tk.Tk()
        self._canvas = tk.Canvas(self._root)
        self._menu   = tk.Menu(self._root, tearoff=0)

        self._setup_window()
        self._setup_canvas()
        self._setup_menu()
        self._restore_position()
        self._fetch_async()

    def _setup_window(self) -> None:
        r = self._root
        r.overrideredirect(True)
        r.wm_attributes("-topmost", True)
        r.wm_attributes("-alpha", self._opacity)
        r.configure(bg=self._theme["bg"])
        r.resizable(False, False)
        r.title("ollama-usage")

    def _setup_canvas(self) -> None:
        t = self._theme
        w, h = _W_FULL if self._size == "full" else _W_COMPACT
        self._root.geometry(f"{w}x{h}")

        self._canvas.destroy()
        self._canvas = tk.Canvas(
            self._root, width=w, height=h,
            bg=t["bg"],
            highlightthickness=1,
            highlightbackground=t["border"],
        )
        self._canvas.pack(fill="both", expand=True)

        for widget in (self._root, self._canvas):
            widget.bind("<ButtonPress-1>",   self._on_drag_start)
            widget.bind("<B1-Motion>",       self._on_drag_motion)
            widget.bind("<ButtonRelease-1>", self._on_drag_end)
            widget.bind("<Button-3>",        self._show_menu)

    def _setup_menu(self) -> None:
        t = self._theme
        m = self._menu
        m.configure(
            bg=t["bg"], fg=t["fg"],
            activebackground=t["bar_bg"],
            activeforeground=t["fg"],
            bd=0,
        )
        m.add_command(label="⟳  Refresh now",    command=self._fetch_async)
        m.add_command(label="⇅  Toggle size",    command=self._toggle_size)
        m.add_separator()
        m.add_command(label="✕  Close",          command=self._quit)

    def _on_drag_start(self, event: tk.Event) -> None:
        self._drag_x = event.x_root - self._root.winfo_x()
        self._drag_y = event.y_root - self._root.winfo_y()

    def _on_drag_motion(self, event: tk.Event) -> None:
        self._root.geometry(
            f"+{event.x_root - self._drag_x}+{event.y_root - self._drag_y}"
        )

    def _on_drag_end(self, _: tk.Event) -> None:
        self._save_position()

    def _restore_position(self) -> None:
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        ww, wh = _W_FULL if self._size == "full" else _W_COMPACT

        default_x, default_y = sw - ww - 10, 10
        x, y = default_x, default_y

        if self._position and self._position in POSITIONS:
            x, y = POSITIONS[self._position](sw, sh, ww, wh)
        else:
            try:
                state = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
                saved_x = state.get("x", default_x)
                saved_y = state.get("y", default_y)
                if not isinstance(saved_x, int) or not isinstance(saved_y, int):
                    raise ValueError("State file contains non-integer coordinates")
                if 0 <= saved_x <= sw - 20 and 0 <= saved_y <= sh - 20:
                    x, y = saved_x, saved_y
            except Exception as e:
                logger.debug("Could not restore widget position: %s", e)

        self._root.geometry(f"+{x}+{y}")

    def _save_position(self) -> None:
        try:
            _STATE_FILE.write_text(
                json.dumps({"x": self._root.winfo_x(), "y": self._root.winfo_y()}),
                encoding="utf-8"
            )
        except Exception:
            pass

    def _show_menu(self, event: tk.Event) -> None:
        try:
            if self._root.winfo_exists():
                self._menu.tk_popup(event.x_root, event.y_root)
        except tk.TclError:
            pass

    def _toggle_size(self) -> None:
        self._size = "compact" if self._size == "full" else "full"
        self._setup_canvas()
        self._draw()

    def _quit(self) -> None:
        self._is_running = False
        try:
            self._save_position()
        except Exception:
            pass
        self._root.destroy()
        sys.exit(0)

    def _fetch_async(self) -> None:
        if self._is_fetching.is_set():
            return
        self._is_fetching.set()
        if self._after_id:
            self._root.after_cancel(self._after_id)
        threading.Thread(target=self._fetch, daemon=True, name="ollama-fetch").start()

    def _fetch(self) -> None:
        try:
            if self._api_key:
                self._data = get_usage_api(self._api_key)
            else:
                self._data = get_usage(self._cookie or "")
            self._error = None
        except NetworkError:
            self._error = "Network error"
        except OllamaUsageError as exc:
            self._error = str(exc)
        finally:
            self._is_fetching.clear()
            if self._is_running:
                try:
                    self._root.after(0, self._draw)
                    self._after_id = self._root.after(
                        self._interval * 1000, self._fetch_async
                    )
                except Exception:
                    pass

    def _draw(self) -> None:
        self._canvas.delete("all")
        if self._size == "compact":
            self._draw_compact()
        else:
            self._draw_full()

    def _draw_compact(self) -> None:
        c, t   = self._canvas, self._theme
        w, h   = _W_COMPACT
        p      = _PAD

        dot = t["green"] if self._data and not self._error else t["red"]
        c.create_text(w - p, p, text="●", anchor="ne",
                      fill=dot, font=(_FONT, 8))
        c.create_text(p, p, text="ollama-usage", anchor="nw",
                      fill=t["sub"], font=(_FONT, 8))

        if self._error or not self._data:
            msg = self._error or "Loading…"
            c.create_text(w // 2, h // 2, text=msg, anchor="center",
                          fill=t["red"] if self._error else t["sub"],
                          font=(_FONT, 9))
            return

        y = p + 20
        for key, period in iter_periods(self._data):
            pct   = period["used_pct"]
            color = _pct_color(pct, t)
            c.create_text(p,     y, text=f"{key.capitalize()}:", anchor="nw",
                          fill=t["sub"], font=(_FONT, 9))
            c.create_text(w - p, y, text=f"{pct:.1f}%", anchor="ne",
                          fill=color, font=(_FONT, 9, "bold"))
            y += 16

    def _draw_full(self) -> None:
        c, t   = self._canvas, self._theme
        w, h   = _W_FULL
        p      = _PAD
        bw     = _BAR_W
        bh     = _BAR_H
        bar_x  = (w - bw) // 2

        plan = (self._data or {}).get("plan")
        header = f"ollama · {plan.capitalize()}" if plan else "ollama"
        c.create_text(p, p, text=header, anchor="nw",
                      fill=t["sub"], font=(_FONT, 8))
        dot = t["green"] if self._data and not self._error else t["red"]
        c.create_text(w - p, p, text="●", anchor="ne",
                      fill=dot, font=(_FONT, 8))

        if self._error or not self._data:
            msg = self._error or "Loading…"
            c.create_text(w // 2, h // 2, text=msg, anchor="center",
                          fill=t["red"] if self._error else t["sub"],
                          font=(_FONT, 9))
            return

        y = p + 22
        for key, period in iter_periods(self._data):
            label  = key.capitalize()
            pct    = period["used_pct"]
            iso    = period["resets_at"]
            models = period.get("models", [])
            color = _pct_color(pct, t)

            c.create_text(bar_x,      y, text=label,         anchor="nw",
                          fill=t["fg"], font=(_FONT, 9, "bold"))
            c.create_text(bar_x + bw, y, text=f"{pct:.1f}%", anchor="ne",
                          fill=color, font=(_FONT, 9, "bold"))
            y += 14

            c.create_rectangle(bar_x, y, bar_x + bw, y + bh,
                                fill=t["bar_bg"], outline="", width=0)
            total_fill_w = int(bw * min(pct, 100.0) / 100.0)
            # share_pct is only available from the settings page
            has_shares = all(m.get("share_pct") is not None for m in models)
            if models and has_shares and total_fill_w > 0:
                x_cursor = bar_x
                for m in models[:_MAX_MODELS]:
                    seg_w = int(total_fill_w * m["share_pct"] / 100.0)
                    if seg_w > 0:
                        c.create_rectangle(
                            x_cursor, y, x_cursor + seg_w, y + bh,
                            fill=m["color"], outline="", width=0,
                        )
                        x_cursor += seg_w
            elif total_fill_w > 0:
                c.create_rectangle(bar_x, y, bar_x + total_fill_w, y + bh,
                                   fill=color, outline="", width=0)
            y += bh + 5

            for m in models[:_MAX_MODELS]:
                dot_x = bar_x + 2
                c.create_rectangle(dot_x, y + 1, dot_x + 7, y + 9,
                                   fill=m.get("color") or t["sub"], outline="", width=0)
                name = _truncate(m["model"], 15)
                c.create_text(dot_x + 10, y, text=name, anchor="nw",
                              fill=t["sub"], font=(_FONT, 8))
                c.create_text(bar_x + bw, y, text=f"{m['requests']}req",
                              anchor="ne", fill=t["sub"], font=(_FONT, 8))
                y += 11

            if iso:
                c.create_text(bar_x, y,
                              text=f"resets in {_fmt_countdown(_seconds_until(iso))}",
                              anchor="nw", fill=t["sub"], font=(_FONT, 8))
                y += 20
            else:
                y += 8

        extras = []
        if self._data.get("credits_balance") is not None:
            extras.append(f"credits ${self._data['credits_balance']:.2f}")
        if self._data.get("spend"):
            extras.append(f"spend ${self._data['spend']['cost_usd']:.2f} (4w)")
        if extras and y + 12 <= h:
            c.create_text(bar_x, y, text="  ·  ".join(extras),
                          anchor="nw", fill=t["sub"], font=(_FONT, 8))

    def run(self) -> None:
        self._root.mainloop()


def launch_widget(
    cookie: str | None   = None,
    interval: int        = 30,
    theme: str           = "dark",
    size: str            = "full",
    opacity: float       = 0.92,
    position: str | None = None,
    api_key: str | None  = None,
) -> None:
    """
    Launch the always-on-top Ollama quota widget.

    Args:
        cookie:   __Secure-session cookie value (scrapes ollama.com/settings).
        api_key:  ollama.com API key (official /api/usage) — takes precedence over cookie.
        interval: Refresh interval in seconds (min 10).
        theme:    "dark" | "light" | "minimal".
        size:     "full" (bars + models + countdown) | "compact" (text only).
        opacity:  Window opacity between 0.1 and 1.0.
        position: "top-left" | "top-right" | "bottom-left" | "bottom-right"
                  or None to restore last saved position.
    """
    try:
        import tkinter  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "tkinter is not available. "
            "On Linux, install it with: sudo apt install python3-tk"
        )

    OllamaWidget(
        cookie=cookie,
        interval=interval,
        theme=theme,
        size=size,
        opacity=opacity,
        position=position,
        api_key=api_key,
    ).run()