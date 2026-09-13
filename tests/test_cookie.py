"""Tests for ollama_usage.cookie.

Everything is mocked: no real browser is needed, and `_SYSTEM` is patched
so the tests behave identically on every OS.
"""

from __future__ import annotations

import pathlib
import sqlite3

import pytest

from ollama_usage.cookie import (
    _COOKIE_HOST,
    _COOKIE_NAME,
    _copy_db,
    _firefox_profiles_dir,
    _get_default_firefox_profile,
    _query_cookie,
    get_cookie_auto,
    get_cookie_brave,
    get_cookie_chrome,
    get_cookie_edge,
    get_cookie_env,
    get_cookie_firefox,
    get_cookie_opera,
)
from ollama_usage.exceptions import (
    BrowserNotFoundError,
    OllamaUsageError,
    UnsupportedOSError,
)


def _make_firefox_db(path: pathlib.Path, rows: list[tuple]) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE moz_cookies (host TEXT, name TEXT, value TEXT)")
    conn.executemany(
        "INSERT INTO moz_cookies (host, name, value) VALUES (?, ?, ?)", rows
    )
    conn.commit()
    conn.close()


def _force_system(monkeypatch, value: str) -> None:
    monkeypatch.setattr("ollama_usage.cookie._SYSTEM", value)


def _force_home(monkeypatch, home: pathlib.Path) -> None:
    monkeypatch.setattr(pathlib.Path, "home", lambda: home)


class TestCopyDb:

    def test_missing_source_raises(self, tmp_path: pathlib.Path) -> None:
        with pytest.raises(BrowserNotFoundError, match="not found"):
            with _copy_db(tmp_path / "does-not-exist.sqlite"):
                pass

    def test_yields_existing_temp_copy(self, tmp_path: pathlib.Path) -> None:
        src = tmp_path / "src.sqlite"
        src.write_bytes(b"hello")
        with _copy_db(src) as tmp:
            assert pathlib.Path(tmp).exists()
            assert pathlib.Path(tmp).read_bytes() == b"hello"
            assert pathlib.Path(tmp) != src

    def test_temp_deleted_after_success(self, tmp_path: pathlib.Path) -> None:
        src = tmp_path / "src.sqlite"
        src.write_bytes(b"data")
        with _copy_db(src) as tmp:
            saved = tmp
        assert not pathlib.Path(saved).exists()

    def test_temp_deleted_after_exception(self, tmp_path: pathlib.Path) -> None:
        src = tmp_path / "src.sqlite"
        src.write_bytes(b"data")
        saved = {}
        with pytest.raises(RuntimeError):
            with _copy_db(src) as tmp:
                saved["path"] = tmp
                raise RuntimeError("boom")
        assert not pathlib.Path(saved["path"]).exists()

    def test_permission_error_raises_browser_not_found(
        self, tmp_path: pathlib.Path, monkeypatch
    ) -> None:
        src = tmp_path / "locked.sqlite"
        src.write_bytes(b"data")

        def boom(*_a, **_k):
            raise PermissionError("WinError 32: file locked")

        monkeypatch.setattr("ollama_usage.cookie.shutil.copy2", boom)
        with pytest.raises(BrowserNotFoundError, match="locked"):
            with _copy_db(src):
                pass

    def test_permission_error_cleans_up_temp(
        self, tmp_path: pathlib.Path, monkeypatch
    ) -> None:
        src = tmp_path / "locked.sqlite"
        src.write_bytes(b"data")
        created = {}
        real_named = __import__("tempfile").NamedTemporaryFile

        def tracking_named(*a, **k):
            f = real_named(*a, **k)
            created["name"] = f.name
            return f

        monkeypatch.setattr("ollama_usage.cookie.tempfile.NamedTemporaryFile", tracking_named)
        monkeypatch.setattr(
            "ollama_usage.cookie.shutil.copy2",
            lambda *a, **k: (_ for _ in ()).throw(PermissionError("locked")),
        )
        with pytest.raises(BrowserNotFoundError):
            with _copy_db(src):
                pass
        assert not pathlib.Path(created["name"]).exists()


class TestQueryCookie:

    def test_returns_value_when_row_exists(self, tmp_path: pathlib.Path) -> None:
        db = tmp_path / "c.sqlite"
        _make_firefox_db(db, [(_COOKIE_HOST, _COOKIE_NAME, "secret")])
        val = _query_cookie(
            str(db),
            "SELECT value FROM moz_cookies WHERE host=? AND name=?",
            (_COOKIE_HOST, _COOKIE_NAME),
        )
        assert val == "secret"

    def test_returns_none_when_no_row(self, tmp_path: pathlib.Path) -> None:
        db = tmp_path / "c.sqlite"
        _make_firefox_db(db, [])
        val = _query_cookie(
            str(db),
            "SELECT value FROM moz_cookies WHERE host=? AND name=?",
            (_COOKIE_HOST, _COOKIE_NAME),
        )
        assert val is None

    def test_params_are_not_interpolated(self, tmp_path: pathlib.Path) -> None:
        db = tmp_path / "c.sqlite"
        _make_firefox_db(db, [(_COOKIE_HOST, _COOKIE_NAME, "secret")])
        val = _query_cookie(
            str(db),
            "SELECT value FROM moz_cookies WHERE host=? AND name=?",
            ("ollama.com' OR '1'='1", _COOKIE_NAME),
        )
        assert val is None


class TestFirefoxProfilesDir:

    def test_windows(self, tmp_path: pathlib.Path, monkeypatch) -> None:
        _force_system(monkeypatch, "Windows")
        _force_home(monkeypatch, tmp_path)
        assert _firefox_profiles_dir() == tmp_path / "AppData/Roaming/Mozilla/Firefox/Profiles"

    def test_darwin(self, tmp_path: pathlib.Path, monkeypatch) -> None:
        _force_system(monkeypatch, "Darwin")
        _force_home(monkeypatch, tmp_path)
        assert _firefox_profiles_dir() == tmp_path / "Library/Application Support/Firefox/Profiles"

    def test_linux_returns_first_existing(self, tmp_path: pathlib.Path, monkeypatch) -> None:
        _force_system(monkeypatch, "Linux")
        _force_home(monkeypatch, tmp_path)
        (tmp_path / ".mozilla/firefox").mkdir(parents=True)
        assert _firefox_profiles_dir() == tmp_path / ".mozilla/firefox"

    def test_linux_snap_fallback(self, tmp_path: pathlib.Path, monkeypatch) -> None:
        _force_system(monkeypatch, "Linux")
        _force_home(monkeypatch, tmp_path)
        (tmp_path / "snap/firefox/common/.mozilla/firefox").mkdir(parents=True)
        assert _firefox_profiles_dir() == tmp_path / "snap/firefox/common/.mozilla/firefox"

    def test_linux_none_exist_returns_classic_path(self, tmp_path: pathlib.Path, monkeypatch) -> None:
        _force_system(monkeypatch, "Linux")
        _force_home(monkeypatch, tmp_path)
        assert _firefox_profiles_dir() == tmp_path / ".mozilla/firefox"

    def test_unsupported_os_raises(self, monkeypatch) -> None:
        _force_system(monkeypatch, "Plan9")
        with pytest.raises(UnsupportedOSError):
            _firefox_profiles_dir()


class TestGetDefaultFirefoxProfile:

    def _base(self, tmp_path: pathlib.Path) -> pathlib.Path:
        base = tmp_path / "firefox"
        base.mkdir()
        return base

    def test_reads_default_profile_with_cookies(self, tmp_path: pathlib.Path) -> None:
        base = self._base(tmp_path)
        prof = base / "Profiles/abcd.default-release"
        prof.mkdir(parents=True)
        (prof / "cookies.sqlite").write_bytes(b"x")
        (base / "profiles.ini").write_text(
            "[Profile0]\nPath=Profiles/abcd.default-release\nIsRelative=1\nDefault=1\n",
            encoding="utf-8",
        )
        assert _get_default_firefox_profile(base) == prof

    def test_default_profile_wins_over_others(self, tmp_path: pathlib.Path) -> None:
        base = self._base(tmp_path)
        other = base / "p_other"
        default = base / "p_default"
        for p in (other, default):
            p.mkdir()
            (p / "cookies.sqlite").write_bytes(b"x")
        # non-default profile listed first
        (base / "profiles.ini").write_text(
            "[Profile0]\nPath=p_other\nIsRelative=1\nDefault=0\n"
            "[Profile1]\nPath=p_default\nIsRelative=1\nDefault=1\n",
            encoding="utf-8",
        )
        assert _get_default_firefox_profile(base) == default

    def test_absolute_path_is_relative_zero(self, tmp_path: pathlib.Path) -> None:
        base = self._base(tmp_path)
        prof = tmp_path / "absolute_profile"
        prof.mkdir()
        (prof / "cookies.sqlite").write_bytes(b"x")
        (base / "profiles.ini").write_text(
            f"[Profile0]\nPath={prof}\nIsRelative=0\nDefault=1\n",
            encoding="utf-8",
        )
        assert _get_default_firefox_profile(base) == prof

    def test_glob_fallback_when_no_ini(self, tmp_path: pathlib.Path) -> None:
        base = self._base(tmp_path)
        prof = base / "xxxx.default"
        prof.mkdir()
        (prof / "cookies.sqlite").write_bytes(b"x")
        assert _get_default_firefox_profile(base) == prof

    def test_malformed_ini_falls_back_to_glob(self, tmp_path: pathlib.Path) -> None:
        base = self._base(tmp_path)
        (base / "profiles.ini").write_text("this is not valid ini !!!\n", encoding="utf-8")
        prof = base / "zzzz.default"
        prof.mkdir()
        (prof / "cookies.sqlite").write_bytes(b"x")
        assert _get_default_firefox_profile(base) == prof

    def test_raises_when_no_profile_at_all(self, tmp_path: pathlib.Path) -> None:
        base = self._base(tmp_path)
        with pytest.raises(BrowserNotFoundError, match="No Firefox profile"):
            _get_default_firefox_profile(base)

    def test_returns_first_candidate_when_none_has_cookies(self, tmp_path: pathlib.Path) -> None:
        base = self._base(tmp_path)
        prof = base / "p1.default"
        prof.mkdir()  # no cookies.sqlite
        (base / "profiles.ini").write_text(
            "[Profile0]\nPath=p1.default\nIsRelative=1\nDefault=1\n", encoding="utf-8"
        )
        assert _get_default_firefox_profile(base) == prof

    def test_section_without_path_is_skipped(self, tmp_path: pathlib.Path) -> None:
        base = self._base(tmp_path)
        prof = base / "real.default"
        prof.mkdir()
        (prof / "cookies.sqlite").write_bytes(b"x")
        (base / "profiles.ini").write_text(
            "[General]\nStartWithLastProfile=1\n"
            "[Profile0]\nPath=real.default\nIsRelative=1\nDefault=1\n",
            encoding="utf-8",
        )
        assert _get_default_firefox_profile(base) == prof


class TestGetCookieFirefox:

    def test_returns_cookie_value(self, tmp_path: pathlib.Path, monkeypatch) -> None:
        profile = tmp_path / "prof"
        profile.mkdir()
        _make_firefox_db(profile / "cookies.sqlite",
                         [(_COOKIE_HOST, _COOKIE_NAME, "ff-secret")])
        monkeypatch.setattr("ollama_usage.cookie._firefox_profiles_dir", lambda: tmp_path)
        monkeypatch.setattr("ollama_usage.cookie._get_default_firefox_profile", lambda base: profile)
        assert get_cookie_firefox() == "ff-secret"

    def test_returns_none_when_cookie_absent(self, tmp_path: pathlib.Path, monkeypatch) -> None:
        profile = tmp_path / "prof"
        profile.mkdir()
        _make_firefox_db(profile / "cookies.sqlite", [])
        monkeypatch.setattr("ollama_usage.cookie._firefox_profiles_dir", lambda: tmp_path)
        monkeypatch.setattr("ollama_usage.cookie._get_default_firefox_profile", lambda base: profile)
        assert get_cookie_firefox() is None


class TestChromiumUnsupported:

    @pytest.mark.parametrize("fn,name", [
        (get_cookie_chrome, "Chrome"),
        (get_cookie_edge, "Edge"),
        (get_cookie_brave, "Brave"),
        (get_cookie_opera, "Opera"),
    ])
    def test_raises_clear_error(self, fn, name: str) -> None:
        with pytest.raises(BrowserNotFoundError, match=f"^{name} cookies can no longer be read"):
            fn()

    def test_error_suggests_alternatives(self) -> None:
        with pytest.raises(BrowserNotFoundError) as exc:
            get_cookie_chrome()
        msg = str(exc.value)
        assert "OLLAMA_API_KEY" in msg
        assert "Firefox" in msg
        assert "--cookie" in msg

    def test_function_names_preserved(self) -> None:
        assert get_cookie_edge.__name__ == "get_cookie_edge"

    def test_auto_detection_only_tries_firefox(self) -> None:
        from ollama_usage.cookie import _BROWSERS
        assert _BROWSERS == [get_cookie_firefox]

    def test_cryptography_not_imported(self) -> None:
        import ollama_usage.cookie as cookie_module
        assert "cryptography" not in open(cookie_module.__file__, encoding="utf-8").read()


class TestGetCookieAuto:

    def test_returns_first_truthy(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "ollama_usage.cookie._BROWSERS",
            [lambda: None, lambda: "cookie-2", lambda: "cookie-3"],
        )
        assert get_cookie_auto() == "cookie-2"

    def test_skips_browsers_that_raise(self, monkeypatch) -> None:
        def boom():
            raise BrowserNotFoundError("no profile")

        monkeypatch.setattr("ollama_usage.cookie._BROWSERS", [boom, lambda: "ok"])
        assert get_cookie_auto() == "ok"

    def test_raises_when_nothing_found(self, monkeypatch) -> None:
        monkeypatch.setattr("ollama_usage.cookie._BROWSERS", [lambda: None, lambda: None])
        with pytest.raises(OllamaUsageError, match="No Ollama session cookie") as exc:
            get_cookie_auto()
        assert "OLLAMA_API_KEY" in str(exc.value)

    def test_unexpected_error_propagates(self, monkeypatch) -> None:
        """Only OllamaUsageError is swallowed; anything else propagates."""
        def boom():
            raise ValueError("unexpected")

        monkeypatch.setattr("ollama_usage.cookie._BROWSERS", [boom])
        with pytest.raises(ValueError):
            get_cookie_auto()

    def test_stops_at_first_success(self, monkeypatch) -> None:
        calls = []

        def first():
            calls.append("first")
            return "winner"

        def second():
            calls.append("second")
            return "loser"

        monkeypatch.setattr("ollama_usage.cookie._BROWSERS", [first, second])
        assert get_cookie_auto() == "winner"
        assert calls == ["first"]


class TestGetCookieEnv:

    def test_returns_env_value(self, monkeypatch) -> None:
        monkeypatch.setenv("OLLAMA_BROWSER_COOKIE", "env-cookie")
        assert get_cookie_env() == "env-cookie"

    def test_returns_none_when_unset(self, monkeypatch) -> None:
        monkeypatch.delenv("OLLAMA_BROWSER_COOKIE", raising=False)
        assert get_cookie_env() is None

    def test_returns_empty_string_when_blank(self, monkeypatch) -> None:
        monkeypatch.setenv("OLLAMA_BROWSER_COOKIE", "")
        assert get_cookie_env() == ""


class TestFirefoxEdgeCases:

    def test_binary_cookie_value_ignored(self, tmp_path: pathlib.Path, monkeypatch) -> None:
        profile = tmp_path / "prof"
        profile.mkdir()
        _make_firefox_db(profile / "cookies.sqlite", [(_COOKIE_HOST, _COOKIE_NAME, b"\x00bin")])
        monkeypatch.setattr("ollama_usage.cookie._firefox_profiles_dir", lambda: tmp_path)
        monkeypatch.setattr("ollama_usage.cookie._get_default_firefox_profile", lambda base: profile)
        assert get_cookie_firefox() is None

    def test_other_host_ignored(self, tmp_path: pathlib.Path, monkeypatch) -> None:
        profile = tmp_path / "prof"
        profile.mkdir()
        _make_firefox_db(profile / "cookies.sqlite", [("evil.com", _COOKIE_NAME, "nope")])
        monkeypatch.setattr("ollama_usage.cookie._firefox_profiles_dir", lambda: tmp_path)
        monkeypatch.setattr("ollama_usage.cookie._get_default_firefox_profile", lambda base: profile)
        assert get_cookie_firefox() is None

    def test_missing_cookie_db_raises(self, tmp_path: pathlib.Path, monkeypatch) -> None:
        monkeypatch.setattr("ollama_usage.cookie._firefox_profiles_dir", lambda: tmp_path)
        monkeypatch.setattr("ollama_usage.cookie._get_default_firefox_profile", lambda base: tmp_path / "none")
        with pytest.raises(BrowserNotFoundError, match="not found"):
            get_cookie_firefox()

    def test_full_resolution_from_profiles_ini(self, tmp_path: pathlib.Path, monkeypatch) -> None:
        _force_system(monkeypatch, "Windows")
        _force_home(monkeypatch, tmp_path)
        base = tmp_path / "AppData/Roaming/Mozilla/Firefox/Profiles"
        profile = base / "abcd.default-release"
        profile.mkdir(parents=True)
        (base.parent / "profiles.ini").write_text(
            "[Profile0]\nName=default-release\nIsRelative=1\nPath=Profiles/abcd.default-release\nDefault=1\n",
            encoding="utf-8",
        )
        _make_firefox_db(profile / "cookies.sqlite", [(_COOKIE_HOST, _COOKIE_NAME, "real-cookie")])
        assert get_cookie_firefox() == "real-cookie"

    def test_linux_flatpak_profiles_dir(self, tmp_path: pathlib.Path, monkeypatch) -> None:
        _force_system(monkeypatch, "Linux")
        _force_home(monkeypatch, tmp_path)
        flatpak = tmp_path / ".var/app/org.mozilla.firefox/.mozilla/firefox"
        flatpak.mkdir(parents=True)
        assert _firefox_profiles_dir() == flatpak


class TestAutoDetectionIntegration:

    def test_firefox_error_becomes_clear_message(self, monkeypatch) -> None:
        def boom():
            raise BrowserNotFoundError("No Firefox profile found.")

        monkeypatch.setattr("ollama_usage.cookie._BROWSERS", [boom])
        with pytest.raises(OllamaUsageError, match="No Ollama session cookie found in Firefox"):
            get_cookie_auto()

    def test_empty_string_cookie_skipped(self, monkeypatch) -> None:
        monkeypatch.setattr("ollama_usage.cookie._BROWSERS", [lambda: "", lambda: "good"])
        assert get_cookie_auto() == "good"

    @pytest.mark.parametrize("fn", [get_cookie_chrome, get_cookie_edge, get_cookie_brave, get_cookie_opera])
    def test_chromium_stubs_are_browser_not_found(self, fn) -> None:
        with pytest.raises(OllamaUsageError):
            fn()

    def test_chromium_stubs_have_docstrings(self) -> None:
        assert "Unsupported" in (get_cookie_chrome.__doc__ or "")
