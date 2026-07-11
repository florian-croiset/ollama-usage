"""Tests for ollama_usage.cookie.

Couvre tous les chemins d'erreur imaginables : DB verrouillée / absente,
requêtes SQLite, résolution de profil Firefox (ini valide / malformé / absent /
chemins relatifs et absolus), dérivation de clé Chromium (Windows / macOS /
Linux), déchiffrement AES-GCM, auto-détection et variable d'environnement.

Tout est moqué : aucun navigateur réel n'est requis, les tests passent
identiquement sur Windows, Linux et macOS (le `_SYSTEM` est patché).
"""

from __future__ import annotations

import base64
import hashlib
import json
import pathlib
import sqlite3
import sys
import types
from unittest.mock import MagicMock

import pytest

from ollama_usage.cookie import (
    _COOKIE_HOST,
    _COOKIE_NAME,
    _chromium_base,
    _chromium_key,
    _copy_db,
    _decrypt_chromium_value,
    _firefox_profiles_dir,
    _get_default_firefox_profile,
    _query_cookie,
    _read_chromium_cookie,
    get_cookie_auto,
    get_cookie_chrome,
    get_cookie_env,
    get_cookie_firefox,
)
from ollama_usage.exceptions import (
    BrowserNotFoundError,
    OllamaUsageError,
    UnsupportedOSError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_firefox_db(path: pathlib.Path, rows: list[tuple]) -> None:
    """Crée une cookies.sqlite Firefox (table moz_cookies)."""
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE moz_cookies (host TEXT, name TEXT, value TEXT)")
    conn.executemany(
        "INSERT INTO moz_cookies (host, name, value) VALUES (?, ?, ?)", rows
    )
    conn.commit()
    conn.close()


def _make_chromium_db(path: pathlib.Path, rows: list[tuple]) -> None:
    """Crée une DB Cookies Chromium (table cookies, encrypted_value BLOB)."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE cookies (host_key TEXT, name TEXT, encrypted_value BLOB)"
    )
    conn.executemany(
        "INSERT INTO cookies (host_key, name, encrypted_value) VALUES (?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def _encrypt_chromium(key: bytes, plaintext: str,
                      nonce: bytes = b"\x00" * 12, prefix: bytes = b"v10") -> bytes:
    """Chiffre une valeur au format Chromium AES-GCM : prefix(3) + nonce(12) + ct."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    ct = AESGCM(key).encrypt(nonce, plaintext.encode(), None)
    return prefix + nonce + ct


def _write_local_state(path: pathlib.Path, encrypted_key: bytes = b"DPAPIabcdef") -> None:
    """Écrit un fichier 'Local State' Chromium minimal."""
    path.write_text(
        json.dumps({"os_crypt": {"encrypted_key": base64.b64encode(encrypted_key).decode()}}),
        encoding="utf-8",
    )


def _force_system(monkeypatch, value: str) -> None:
    monkeypatch.setattr("ollama_usage.cookie._SYSTEM", value)


def _force_home(monkeypatch, home: pathlib.Path) -> None:
    monkeypatch.setattr(pathlib.Path, "home", lambda: home)


# ---------------------------------------------------------------------------
# _copy_db
# ---------------------------------------------------------------------------

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
        """Le fichier temporaire ne doit pas fuiter si la copie échoue."""
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


# ---------------------------------------------------------------------------
# _query_cookie
# ---------------------------------------------------------------------------

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
        """Une valeur avec des métacaractères SQL doit être traitée littéralement."""
        db = tmp_path / "c.sqlite"
        _make_firefox_db(db, [(_COOKIE_HOST, _COOKIE_NAME, "secret")])
        val = _query_cookie(
            str(db),
            "SELECT value FROM moz_cookies WHERE host=? AND name=?",
            ("ollama.com' OR '1'='1", _COOKIE_NAME),
        )
        assert val is None  # aucune injection : pas de correspondance, pas d'erreur


# ---------------------------------------------------------------------------
# _firefox_profiles_dir
# ---------------------------------------------------------------------------

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
        # classique absent → snap présent
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


# ---------------------------------------------------------------------------
# _get_default_firefox_profile
# ---------------------------------------------------------------------------

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
        # le non-défaut est listé en premier — le défaut doit quand même gagner
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
        """Régression : un profiles.ini illisible ne doit pas faire planter."""
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
        prof.mkdir()  # pas de cookies.sqlite
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


# ---------------------------------------------------------------------------
# get_cookie_firefox (intégration _copy_db + _query_cookie)
# ---------------------------------------------------------------------------

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
        _make_firefox_db(profile / "cookies.sqlite", [])  # table vide
        monkeypatch.setattr("ollama_usage.cookie._firefox_profiles_dir", lambda: tmp_path)
        monkeypatch.setattr("ollama_usage.cookie._get_default_firefox_profile", lambda base: profile)
        assert get_cookie_firefox() is None


# ---------------------------------------------------------------------------
# _chromium_key
# ---------------------------------------------------------------------------

class TestChromiumKey:

    def test_missing_local_state_raises(self, tmp_path: pathlib.Path) -> None:
        with pytest.raises(BrowserNotFoundError, match="Local State"):
            _chromium_key(tmp_path / "Local State")

    def test_linux_uses_peanuts(self, tmp_path: pathlib.Path, monkeypatch) -> None:
        _force_system(monkeypatch, "Linux")
        ls = tmp_path / "Local State"
        _write_local_state(ls)
        key = _chromium_key(ls)
        assert key == hashlib.pbkdf2_hmac("sha1", b"peanuts", b"saltysalt", 1, 16)
        assert len(key) == 16

    def test_darwin_uses_keychain_password(self, tmp_path: pathlib.Path, monkeypatch) -> None:
        _force_system(monkeypatch, "Darwin")
        ls = tmp_path / "Local State"
        _write_local_state(ls)
        fake = MagicMock(returncode=0, stdout="kc-password\n", stderr="")
        monkeypatch.setattr("subprocess.run", lambda *a, **k: fake)
        key = _chromium_key(ls)
        assert key == hashlib.pbkdf2_hmac("sha1", b"kc-password", b"saltysalt", 1003, 16)

    def test_darwin_keychain_failure_raises(self, tmp_path: pathlib.Path, monkeypatch) -> None:
        _force_system(monkeypatch, "Darwin")
        ls = tmp_path / "Local State"
        _write_local_state(ls)
        fake = MagicMock(returncode=1, stdout="", stderr="user cancelled")
        monkeypatch.setattr("subprocess.run", lambda *a, **k: fake)
        with pytest.raises(BrowserNotFoundError, match="Keychain"):
            _chromium_key(ls)

    def test_darwin_empty_password_raises(self, tmp_path: pathlib.Path, monkeypatch) -> None:
        _force_system(monkeypatch, "Darwin")
        ls = tmp_path / "Local State"
        _write_local_state(ls)
        fake = MagicMock(returncode=0, stdout="   \n", stderr="")
        monkeypatch.setattr("subprocess.run", lambda *a, **k: fake)
        with pytest.raises(BrowserNotFoundError):
            _chromium_key(ls)

    def test_windows_uses_dpapi(self, tmp_path: pathlib.Path, monkeypatch) -> None:
        _force_system(monkeypatch, "Windows")
        ls = tmp_path / "Local State"
        _write_local_state(ls, encrypted_key=b"DPAPI" + b"payload")
        fake_win = types.ModuleType("win32crypt")
        fake_win.CryptUnprotectData = lambda *a, **k: ("desc", b"sixteen-byte-key")
        monkeypatch.setitem(sys.modules, "win32crypt", fake_win)
        key = _chromium_key(ls)
        assert key == b"sixteen-byte-key"

    def test_invalid_json_local_state_raises(self, tmp_path: pathlib.Path, monkeypatch) -> None:
        _force_system(monkeypatch, "Linux")
        ls = tmp_path / "Local State"
        ls.write_text("{ not valid json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            _chromium_key(ls)


# ---------------------------------------------------------------------------
# _decrypt_chromium_value
# ---------------------------------------------------------------------------

class TestDecryptChromiumValue:

    def test_roundtrip(self) -> None:
        key = b"0" * 32
        blob = _encrypt_chromium(key, "my-cookie-value")
        assert _decrypt_chromium_value(blob, key) == "my-cookie-value"

    def test_wrong_key_raises(self) -> None:
        blob = _encrypt_chromium(b"0" * 32, "secret")
        from cryptography.exceptions import InvalidTag
        with pytest.raises(InvalidTag):
            _decrypt_chromium_value(blob, b"1" * 32)


# ---------------------------------------------------------------------------
# _read_chromium_cookie
# ---------------------------------------------------------------------------

class TestReadChromiumCookie:

    def test_decrypts_stored_cookie(self, tmp_path: pathlib.Path) -> None:
        key = b"0" * 32
        blob = _encrypt_chromium(key, "chrome-secret")
        db = tmp_path / "Cookies"
        _make_chromium_db(db, [(_COOKIE_HOST, _COOKIE_NAME, blob)])
        assert _read_chromium_cookie(db, key) == "chrome-secret"

    def test_returns_none_when_no_row(self, tmp_path: pathlib.Path) -> None:
        db = tmp_path / "Cookies"
        _make_chromium_db(db, [])
        assert _read_chromium_cookie(db, b"0" * 32) is None

    def test_returns_none_on_empty_blob(self, tmp_path: pathlib.Path) -> None:
        db = tmp_path / "Cookies"
        _make_chromium_db(db, [(_COOKIE_HOST, _COOKIE_NAME, b"")])
        assert _read_chromium_cookie(db, b"0" * 32) is None


# ---------------------------------------------------------------------------
# _chromium_base
# ---------------------------------------------------------------------------

class TestChromiumBase:

    def test_windows(self, tmp_path: pathlib.Path, monkeypatch) -> None:
        _force_system(monkeypatch, "Windows")
        _force_home(monkeypatch, tmp_path)
        base = _chromium_base(win="AppData/Local/X", linux=".config/x", mac="Library/X")
        assert base == tmp_path / "AppData/Local/X"

    def test_darwin(self, tmp_path: pathlib.Path, monkeypatch) -> None:
        _force_system(monkeypatch, "Darwin")
        _force_home(monkeypatch, tmp_path)
        base = _chromium_base(win="AppData/Local/X", linux=".config/x", mac="Library/X")
        assert base == tmp_path / "Library/X"

    def test_linux_returns_first_existing(self, tmp_path: pathlib.Path, monkeypatch) -> None:
        _force_system(monkeypatch, "Linux")
        _force_home(monkeypatch, tmp_path)
        (tmp_path / ".config/x").mkdir(parents=True)
        base = _chromium_base(
            win="AppData/Local/X", linux=".config/x", mac="Library/X",
            linux_flatpak=".var/app/x",
        )
        assert base == tmp_path / ".config/x"

    def test_linux_flatpak_fallback(self, tmp_path: pathlib.Path, monkeypatch) -> None:
        _force_system(monkeypatch, "Linux")
        _force_home(monkeypatch, tmp_path)
        (tmp_path / ".var/app/x").mkdir(parents=True)
        base = _chromium_base(
            win="AppData/Local/X", linux=".config/x", mac="Library/X",
            linux_flatpak=".var/app/x",
        )
        assert base == tmp_path / ".var/app/x"

    def test_unsupported_os_raises(self, monkeypatch) -> None:
        _force_system(monkeypatch, "Plan9")
        with pytest.raises(UnsupportedOSError):
            _chromium_base(win="a", linux="b", mac="c")


# ---------------------------------------------------------------------------
# Régression : chemin Snap Chromium sans double "Default"
# ---------------------------------------------------------------------------

class TestSnapChromiumPath:

    def test_chrome_snap_base_has_no_trailing_default(
        self, tmp_path: pathlib.Path, monkeypatch
    ) -> None:
        _force_system(monkeypatch, "Linux")
        _force_home(monkeypatch, tmp_path)
        # seul le chemin snap existe → il doit être retenu tel quel
        snap = tmp_path / "snap/chromium/common/chromium"
        snap.mkdir(parents=True)
        captured = {}

        def fake_cookie(base, rel):
            captured["base"] = base
            return "x"

        monkeypatch.setattr("ollama_usage.cookie._chromium_cookie", fake_cookie)
        get_cookie_chrome()
        assert captured["base"] == snap
        assert captured["base"].name == "chromium"  # pas "Default"


# ---------------------------------------------------------------------------
# get_cookie_auto
# ---------------------------------------------------------------------------

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
        with pytest.raises(OllamaUsageError, match="No Ollama session cookie"):
            get_cookie_auto()

    def test_unexpected_error_propagates(self, monkeypatch) -> None:
        """Seules les OllamaUsageError sont avalées ; le reste remonte."""
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
        assert calls == ["first"]  # second jamais appelé


# ---------------------------------------------------------------------------
# get_cookie_env
# ---------------------------------------------------------------------------

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
