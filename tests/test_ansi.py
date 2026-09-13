"""Tests for ollama_usage.ansi (colorama replacement)."""

from __future__ import annotations

import io

import pytest

from ollama_usage import ansi


class _Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setattr(ansi, "_vt_enabled", {})


class TestSupportsColor:

    def test_tty_on_posix(self, monkeypatch) -> None:
        monkeypatch.setattr(ansi.sys, "platform", "linux")
        assert ansi.supports_color(_Tty()) is True

    def test_not_a_tty(self, monkeypatch) -> None:
        monkeypatch.setattr(ansi.sys, "platform", "linux")
        assert ansi.supports_color(io.StringIO()) is False

    def test_stream_without_isatty(self) -> None:
        assert ansi.supports_color(object()) is False  # type: ignore[arg-type]

    def test_no_color_wins_over_tty(self, monkeypatch) -> None:
        monkeypatch.setenv("NO_COLOR", "1")
        assert ansi.supports_color(_Tty()) is False

    def test_no_color_wins_over_force_color(self, monkeypatch) -> None:
        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.setenv("FORCE_COLOR", "1")
        assert ansi.supports_color(_Tty()) is False

    def test_empty_no_color_is_ignored(self, monkeypatch) -> None:
        monkeypatch.setattr(ansi.sys, "platform", "linux")
        monkeypatch.setenv("NO_COLOR", "")
        assert ansi.supports_color(_Tty()) is True

    def test_force_color_on_pipe(self, monkeypatch) -> None:
        monkeypatch.setenv("FORCE_COLOR", "1")
        assert ansi.supports_color(io.StringIO()) is True

    def test_defaults_to_sys_stdout(self, monkeypatch) -> None:
        monkeypatch.setattr(ansi.sys, "stdout", io.StringIO())
        assert ansi.supports_color() is False

    @pytest.mark.parametrize("vt_ok,expected", [(True, True), (False, False)])
    def test_windows_depends_on_vt_mode(self, monkeypatch, vt_ok: bool, expected: bool) -> None:
        monkeypatch.setattr(ansi.sys, "platform", "win32")
        monkeypatch.setattr(ansi, "_set_vt_mode", lambda handle_id: vt_ok)
        assert ansi.supports_color(_Tty()) is expected


class TestEnableWindowsAnsi:

    def test_noop_on_posix(self, monkeypatch) -> None:
        monkeypatch.setattr(ansi.sys, "platform", "darwin")
        calls = []
        monkeypatch.setattr(ansi, "_set_vt_mode", lambda h: calls.append(h) or True)
        ansi.enable_windows_ansi()
        assert calls == []

    def test_enables_stdout_and_stderr_once(self, monkeypatch) -> None:
        monkeypatch.setattr(ansi.sys, "platform", "win32")
        calls = []
        monkeypatch.setattr(ansi, "_set_vt_mode", lambda h: calls.append(h) or True)
        ansi.enable_windows_ansi()
        ansi.enable_windows_ansi()
        assert calls == [ansi._STD_OUTPUT_HANDLE, ansi._STD_ERROR_HANDLE]

    def test_ctypes_failure_is_swallowed(self, monkeypatch) -> None:
        monkeypatch.setattr(ansi.sys, "platform", "win32")

        def boom(_h):
            raise OSError("no console")

        monkeypatch.setattr(ansi, "_set_vt_mode", boom)
        ansi.enable_windows_ansi()
        assert ansi.supports_color(_Tty()) is False


class TestColorize:

    def test_wraps_when_supported(self, monkeypatch) -> None:
        monkeypatch.setenv("FORCE_COLOR", "1")
        assert ansi.colorize("42%", ansi.RED) == "\033[31m42%\033[0m"

    def test_plain_when_not_supported(self) -> None:
        assert ansi.colorize("42%", ansi.GREEN, io.StringIO()) == "42%"

    @pytest.mark.parametrize("code", [ansi.GREEN, ansi.YELLOW, ansi.RED, ansi.RESET])
    def test_codes_are_ansi_sgr(self, code: str) -> None:
        assert code.startswith("\033[") and code.endswith("m")


class _FakeKernel32:
    def __init__(self, console: bool = True, mode: int = 0, set_ok: int = 1) -> None:
        self.console = console
        self.mode = mode
        self.set_ok = set_ok
        self.set_calls: list[int] = []

    def GetStdHandle(self, handle_id: int) -> int:
        return handle_id

    def GetConsoleMode(self, handle: int, mode_ref) -> int:
        if not self.console:
            return 0
        mode_ref._obj.value = self.mode
        return 1

    def SetConsoleMode(self, handle: int, mode: int) -> int:
        self.set_calls.append(mode)
        return self.set_ok


class TestSetVtMode:

    def _run(self, monkeypatch, kernel: _FakeKernel32) -> bool:
        import ctypes
        import types
        monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(kernel32=kernel), raising=False)
        return ansi._set_vt_mode(ansi._STD_OUTPUT_HANDLE)

    def test_not_a_console(self, monkeypatch) -> None:
        kernel = _FakeKernel32(console=False)
        assert self._run(monkeypatch, kernel) is False
        assert kernel.set_calls == []

    def test_already_enabled(self, monkeypatch) -> None:
        kernel = _FakeKernel32(mode=0x0004 | 0x0001)
        assert self._run(monkeypatch, kernel) is True
        assert kernel.set_calls == []

    def test_enables_flag_and_keeps_existing_bits(self, monkeypatch) -> None:
        kernel = _FakeKernel32(mode=0x0003)
        assert self._run(monkeypatch, kernel) is True
        assert kernel.set_calls == [0x0007]

    def test_set_console_mode_fails(self, monkeypatch) -> None:
        kernel = _FakeKernel32(mode=0, set_ok=0)
        assert self._run(monkeypatch, kernel) is False


class TestStderrHandle:

    def test_uses_stderr_handle_for_stderr(self, monkeypatch) -> None:
        tty_err = _Tty()
        monkeypatch.setattr(ansi.sys, "platform", "win32")
        monkeypatch.setattr(ansi.sys, "stderr", tty_err)
        monkeypatch.setattr(ansi, "_set_vt_mode", lambda h: h == ansi._STD_ERROR_HANDLE)
        assert ansi.supports_color(tty_err) is True
        assert ansi.supports_color(_Tty()) is False

    def test_colorize_on_stderr_stream(self, monkeypatch) -> None:
        monkeypatch.setenv("FORCE_COLOR", "1")
        assert ansi.colorize("x", ansi.YELLOW, io.StringIO()) == "\033[33mx\033[0m"

    def test_colorize_empty_text(self, monkeypatch) -> None:
        monkeypatch.setenv("FORCE_COLOR", "1")
        assert ansi.colorize("", ansi.RED) == "\033[31m\033[0m"
