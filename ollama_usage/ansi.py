"""Minimal ANSI terminal colors, without third-party dependencies.

- Windows 10+ consoles understand ANSI escape codes once "virtual terminal
  processing" is enabled on the output handle (SetConsoleMode).
- Colors are disabled when the stream is not a terminal (pipe, file, cron),
  when NO_COLOR is set (https://no-color.org), and forced with FORCE_COLOR.
"""

from __future__ import annotations

import os
import sys
from typing import TextIO

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"

_STD_OUTPUT_HANDLE = -11
_STD_ERROR_HANDLE = -12
_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004

_vt_enabled: dict[int, bool] = {}


def _set_vt_mode(handle_id: int) -> bool:
    """Enable VT processing on a Windows console handle; False if not a console."""
    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.GetStdHandle(handle_id)
    mode = ctypes.c_uint32()
    if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        return False  # not a console (redirected)
    if mode.value & _ENABLE_VIRTUAL_TERMINAL_PROCESSING:
        return True
    return bool(kernel32.SetConsoleMode(handle, mode.value | _ENABLE_VIRTUAL_TERMINAL_PROCESSING))


def enable_windows_ansi() -> None:
    """Enable ANSI escape codes on the Windows console (no-op on other platforms)."""
    if sys.platform != "win32":
        return
    for handle_id in (_STD_OUTPUT_HANDLE, _STD_ERROR_HANDLE):
        if handle_id not in _vt_enabled:
            try:
                _vt_enabled[handle_id] = _set_vt_mode(handle_id)
            except Exception:  # noqa: BLE001
                _vt_enabled[handle_id] = False


def supports_color(stream: TextIO | None = None) -> bool:
    """Return True if ANSI colors should be written to the stream."""
    out: TextIO = sys.stdout if stream is None else stream
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    if not (hasattr(out, "isatty") and out.isatty()):
        return False
    if sys.platform == "win32":
        enable_windows_ansi()
        handle_id = _STD_ERROR_HANDLE if out is sys.stderr else _STD_OUTPUT_HANDLE
        return _vt_enabled.get(handle_id, False)
    return True


def colorize(text: str, color: str, stream: TextIO | None = None) -> str:
    """Wrap text in an ANSI color if the stream supports it."""
    return f"{color}{text}{RESET}" if supports_color(stream) else text
