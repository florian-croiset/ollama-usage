"""Read the Ollama __Secure-session cookie from installed browsers."""

from __future__ import annotations

import configparser
import contextlib
import json
import pathlib
import platform
import shutil
import sqlite3
import tempfile
import logging
logger = logging.getLogger(__name__)
from base64 import b64decode
from typing import Callable, Generator

from ollama_usage.exceptions import (
    BrowserNotFoundError,
    OllamaUsageError,
    UnsupportedOSError,
)

_SYSTEM = platform.system()
_COOKIE_NAME = "__Secure-session"
_COOKIE_HOST = "ollama.com"


# --- SQLite helpers ---

@contextlib.contextmanager
def _copy_db(path: pathlib.Path) -> Generator[str, None, None]:
    """Copy a locked SQLite DB to a temp file, yield the path, then delete it."""
    if not path.exists():
        raise BrowserNotFoundError(f"Cookie database not found: {path}")
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    shutil.copy2(str(path), tmp.name)
    tmp.close()
    try:
        yield tmp.name
    finally:
        pathlib.Path(tmp.name).unlink(missing_ok=True)
        logger.debug("Temp DB deleted: %s", tmp.name)


def _query_cookie(db_path: str, query: str, params: tuple) -> bytes | None:
    """Execute a query on a SQLite cookie database and return the first result."""
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


# --- Firefox ---

def _firefox_profiles_dir() -> pathlib.Path:
    dirs = {
        "Windows": pathlib.Path.home() / "AppData/Roaming/Mozilla/Firefox/Profiles",
        "Linux":   pathlib.Path.home() / ".mozilla/firefox",
        "Darwin":  pathlib.Path.home() / "Library/Application Support/Firefox/Profiles",
    }
    if _SYSTEM not in dirs:
        raise UnsupportedOSError(f"Firefox not supported on {_SYSTEM}")
    return dirs[_SYSTEM]


def _get_default_firefox_profile(base: pathlib.Path) -> pathlib.Path:
    """
    Return the path of the default Firefox profile that contains cookies.sqlite.
    Reads profiles.ini, collects all candidates (Default=1 first),
    then returns the first one that actually has cookies.sqlite.
    Falls back to glob if profiles.ini is absent or malformed.
    """
    candidates: list[pathlib.Path] = []

    for ini_candidate in [base.parent / "profiles.ini", base / "profiles.ini"]:
        if not ini_candidate.exists():
            continue
        config = configparser.ConfigParser()
        config.read(str(ini_candidate), encoding="utf-8")

        defaults: list[pathlib.Path] = []
        others: list[pathlib.Path] = []

        for section in config.sections():
            rel_path = config.get(section, "Path", fallback=None)
            if not rel_path:
                continue
            is_relative = config.get(section, "IsRelative", fallback="1") == "1"
            profile = (
                (ini_candidate.parent / rel_path)
                if is_relative
                else pathlib.Path(rel_path)
            )
            if config.get(section, "Default", fallback="0") == "1":
                defaults.append(profile)
            else:
                others.append(profile)

        candidates = defaults + others
        break

    if not candidates:
        logger.debug("profiles.ini not found or empty — falling back to glob")
        candidates = list(base.glob("*.default*"))

    if not candidates:
        raise BrowserNotFoundError("No Firefox profile found.")

    for profile in candidates:
        db = profile / "cookies.sqlite"
        if db.exists():
            logger.debug("Firefox default profile: %s", profile)
            return profile

    logger.debug("No profile with cookies.sqlite found, returning: %s", candidates[0])
    return candidates[0]


def get_cookie_firefox() -> str | None:
    """Read __Secure-session from Firefox."""
    base = _firefox_profiles_dir()
    profile = _get_default_firefox_profile(base)
    with _copy_db(profile / "cookies.sqlite") as db:
        value = _query_cookie(
            db,
            "SELECT value FROM moz_cookies WHERE host=? AND name=?",
            (_COOKIE_HOST, _COOKIE_NAME),
        )
    return value if isinstance(value, str) else None


# --- Chromium-based browsers ---

def _chromium_key(local_state: pathlib.Path) -> bytes:
    """Decrypt the AES key from Chrome's Local State file."""
    if not local_state.exists():
        raise BrowserNotFoundError(f"Local State not found: {local_state}")
    with open(local_state, encoding="utf-8") as f:
        data = json.load(f)
    encrypted_key = b64decode(data["os_crypt"]["encrypted_key"])[5:]

    if _SYSTEM == "Windows":
        import win32crypt
        return win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)[1]
    elif _SYSTEM == "Darwin":
        import hashlib, subprocess
        password = subprocess.run(
            ["security", "find-generic-password", "-a", "Chrome",
             "-s", "Chrome Safe Storage", "-w"],
            capture_output=True, text=True,
        ).stdout.strip().encode()
        return hashlib.pbkdf2_hmac("sha1", password, b"saltysalt", 1003, 16)
    else:
        import hashlib
        return hashlib.pbkdf2_hmac("sha1", b"peanuts", b"saltysalt", 1, 16)


def _decrypt_chromium_value(encrypted: bytes, key: bytes) -> str:
    """Decrypt a Chromium AES-GCM encrypted cookie value."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce, ciphertext = encrypted[3:15], encrypted[15:]
    return AESGCM(key).decrypt(nonce, ciphertext, None).decode()


def _read_chromium_cookie(db_path: pathlib.Path, key: bytes) -> str | None:
    """Read and decrypt __Secure-session from a Chromium cookies DB."""
    with _copy_db(db_path) as tmp:
        encrypted = _query_cookie(
            tmp,
            "SELECT encrypted_value FROM cookies WHERE host_key=? AND name=?",
            (_COOKIE_HOST, _COOKIE_NAME),
        )
    if not encrypted:
        return None
    return _decrypt_chromium_value(encrypted, key)


def _chromium_cookie(base: pathlib.Path, cookies_rel: pathlib.Path) -> str | None:
    """Generic helper for all Chromium-based browsers."""
    key = _chromium_key(base / "Local State")
    return _read_chromium_cookie(base / cookies_rel, key)


# --- Per-browser public API ---

def _chromium_base(win: str, linux: str, mac: str) -> pathlib.Path:
    dirs = {
        "Windows": pathlib.Path.home() / win,
        "Linux":   pathlib.Path.home() / linux,
        "Darwin":  pathlib.Path.home() / mac,
    }
    if _SYSTEM not in dirs:
        raise UnsupportedOSError(f"Unsupported OS: {_SYSTEM}")
    return dirs[_SYSTEM]


_CHROMIUM_COOKIES_PATH = pathlib.Path("Default/Network/Cookies")


def get_cookie_chrome() -> str | None:
    base = _chromium_base(
        "AppData/Local/Google/Chrome/User Data",
        ".config/google-chrome",
        "Library/Application Support/Google/Chrome",
    )
    return _chromium_cookie(base, _CHROMIUM_COOKIES_PATH)


def get_cookie_edge() -> str | None:
    base = _chromium_base(
        "AppData/Local/Microsoft/Edge/User Data",
        ".config/microsoft-edge",
        "Library/Application Support/Microsoft Edge",
    )
    return _chromium_cookie(base, _CHROMIUM_COOKIES_PATH)


def get_cookie_brave() -> str | None:
    base = _chromium_base(
        "AppData/Local/BraveSoftware/Brave-Browser/User Data",
        ".config/BraveSoftware/Brave-Browser",
        "Library/Application Support/BraveSoftware/Brave-Browser",
    )
    return _chromium_cookie(base, _CHROMIUM_COOKIES_PATH)


def get_cookie_opera() -> str | None:
    base = _chromium_base(
        "AppData/Roaming/Opera Software/Opera Stable",
        ".config/opera",
        "Library/Application Support/com.operasoftware.Opera",
    )
    return _chromium_cookie(base, pathlib.Path("Cookies"))


# --- Auto-detection ---

_BROWSERS: list[Callable[[], str | None]] = [
    get_cookie_chrome,
    get_cookie_firefox,
    get_cookie_edge,
    get_cookie_brave,
    get_cookie_opera,
]

def get_cookie_auto() -> str:
    """Try each browser in order and return the first valid cookie found."""
    for browser in _BROWSERS:
        logger.debug("Trying %s...", browser.__name__)
        try:
            cookie = browser()
            if cookie:
                logger.debug("Cookie found via %s", browser.__name__)
                return cookie
        except OllamaUsageError as e:
            logger.debug("%s failed: %s", browser.__name__, e)
            continue
    raise OllamaUsageError(
        "No Ollama session cookie found in any supported browser. "
        "Pass it manually with --cookie."
    )


# --- Environment Variable ---


def get_cookie_env() -> str | None:
    """Read cookie from OLLAMA_BROWSER_COOKIE environment variable."""
    import os

    return os.environ.get("OLLAMA_BROWSER_COOKIE")
