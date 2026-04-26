# Changelog

All notable changes to this project will be documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [0.1.1] - 2026-04-26

### Fixed
- Cookie sanitized against HTTP header injection (`\r`, `\n`, `\0`)
- `--interval` clamped to 10–3600s
- Terminal clear no longer uses `os.system`
- TLS context now explicit in scraper
- HTTP 401/403 raises `AuthError` instead of `NetworkError`
- UTF-8 decode error raises `ParseError`
- Widget exit uses `sys.exit` instead of `os._exit`
- Widget fetch lock uses `threading.Event` (thread-safe)
- Widget state file validates coordinate types

### Added
- Firefox Snap & Flatpak profile detection on Linux
- Chrome/Edge/Brave Snap & Flatpak paths on Linux
- Explicit macOS Keychain error for Chromium browsers
- `BrowserNotFoundError` and `UnsupportedOSError` exported in `__all__`
- `tests/test_cli.py`
- Environment variable support via `OLLAMA_BROWSER_COOKIE` ([@1ts-Alec](https://github.com/1ts-Alec), [#1](https://github.com/florian-croiset/ollama-usage/pull/1))


## [0.1.0] - 2026-04-04

### Added
- Initial release
- CLI with `--json`, `--browser`, `--cookie`, `--watch`, `--interval`, `--debug`, `--alert`, `--quiet`
- Python library API (`get_usage`)
- Auto browser detection (Chrome, Firefox, Edge, Brave, Opera)
- Cross-platform support (Windows, Linux, macOS)
- Custom exception hierarchy (`AuthError`, `NetworkError`, `ParseError`, `BrowserNotFoundError`, `UnsupportedOSError`)
- Colored output — session/weekly usage is green (<50%), yellow (50–80%), or red (>80%) via `colorama`
- `--alert PCT` — exits with code 1 if session or weekly usage exceeds `PCT%`
- `--quiet` — suppresses all output, only sets the exit code
- `--watch` recovers from network errors instead of crashing