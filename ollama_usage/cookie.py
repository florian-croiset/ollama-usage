"""Read the Ollama __Secure-session cookie from installed browsers."""

from __future__ import annotations

import configparser
import contextlib
import logging
import pathlib
import platform
import shutil
import sqlite3
import tempfile
from collections.abc import Generator
from typing import Callable

from ollama_usage.exceptions import (
    BrowserNotFoundError,
    OllamaUsageError,
    UnsupportedOSError,
)

logger = logging.getLogger(__name__)

_SYSTEM = platform.system()
_COOKIE_NAME = "__Secure-session"
_COOKIE_HOST = "ollama.com"


@contextlib.contextmanager
def _copy_db(path: pathlib.Path) -> Generator[str, None, None]:
    """Copy a locked SQLite DB to a temp file, yield the path, then delete it."""
    if not path.exists():
        raise BrowserNotFoundError(f"Cookie database not found: {path}")
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        shutil.copy2(str(path), tmp_path)
    except PermissionError as exc:
        pathlib.Path(tmp_path).unlink(missing_ok=True)
        raise BrowserNotFoundError(
            f"Cannot read cookie database (file locked by another process): {path}\n"
            "Close the browser and try again, or pass your cookie manually with --cookie."
        ) from exc
    try:
        yield tmp_path
    finally:
        pathlib.Path(tmp_path).unlink(missing_ok=True)
        logger.debug("Temp DB deleted: %s", tmp_path)


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


def _firefox_profiles_dir() -> pathlib.Path:
    """Return the Firefox profiles directory, taking Snap/Flatpak into account on Linux."""
    if _SYSTEM == "Windows":
        return pathlib.Path.home() / "AppData/Roaming/Mozilla/Firefox/Profiles"
    if _SYSTEM == "Darwin":
        return pathlib.Path.home() / "Library/Application Support/Firefox/Profiles"
    if _SYSTEM == "Linux":
        candidates = [
            pathlib.Path.home() / ".mozilla/firefox",
            pathlib.Path.home() / "snap/firefox/common/.mozilla/firefox",
            pathlib.Path.home() / ".var/app/org.mozilla.firefox/.mozilla/firefox",
        ]
        for path in candidates:
            if path.exists():
                logger.debug("Firefox profiles dir: %s", path)
                return path
        # Standard path, so the resulting error message is meaningful
        return candidates[0]
    raise UnsupportedOSError(f"Firefox not supported on {_SYSTEM}")


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
        try:
            config.read(str(ini_candidate), encoding="utf-8")
        except configparser.Error:
            logger.debug("Malformed profiles.ini at %s — falling back to glob", ini_candidate)
            continue

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


_CHROMIUM_UNSUPPORTED_MSG = (
    "{name} cookies can no longer be read: Chromium-based browsers encrypt them "
    "(App-Bound Encryption on Windows, OS keyring on macOS/Linux).\n"
    "Use an ollama.com API key instead (--api-key or OLLAMA_API_KEY, recommended), "
    "log in with Firefox, or pass the cookie manually with --cookie."
)


def _chromium_unsupported(name: str) -> Callable[[], str | None]:
    def get_cookie() -> str | None:
        raise BrowserNotFoundError(_CHROMIUM_UNSUPPORTED_MSG.format(name=name))

    get_cookie.__name__ = f"get_cookie_{name.lower()}"
    get_cookie.__doc__ = f"Unsupported: {name} cookies are encrypted — always raises BrowserNotFoundError."
    return get_cookie


# Kept for backward compatibility.
get_cookie_chrome = _chromium_unsupported("Chrome")
get_cookie_edge = _chromium_unsupported("Edge")
get_cookie_brave = _chromium_unsupported("Brave")
get_cookie_opera = _chromium_unsupported("Opera")


_BROWSERS: list[Callable[[], str | None]] = [
    get_cookie_firefox,
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
        "No Ollama session cookie found in Firefox.\n"
        "Use an ollama.com API key (--api-key or OLLAMA_API_KEY, recommended), "
        "or pass the cookie manually with --cookie."
    )


def get_cookie_env() -> str | None:
    """Read cookie from OLLAMA_BROWSER_COOKIE environment variable."""
    import os

    return os.environ.get("OLLAMA_BROWSER_COOKIE")