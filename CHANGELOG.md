# Changelog

All notable changes to this project will be documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## Unreleased

### Fixed
- Model breakdown now correctly parsed after Ollama updated their settings
  page HTML from BEM class names to Tailwind utility classes
- Raise a clear error (exit 1) when the browser returns no Ollama session
  cookie, instead of crashing with `AttributeError: 'NoneType'`
- Critical notifications now fire independently of the warning check
  (`elif` → `if` in notification logic)
- Add validation guards for `--alert`, `--notify-threshold` and `--opacity`
  arguments (range checks with `parser.error`)
- Handle locked cookie DB on Windows (PermissionError / WinError 32) 
  by raising a clear BrowserNotFoundError instead of crashing
- Firefox `profiles.ini` parsing now falls back to glob detection when the
  file is malformed, instead of raising an uncaught `configparser.Error`
- Snap Chromium cookie path no longer contains a duplicated `Default`
  segment, so cookie lookup on Snap Chromium resolves correctly
- `--widget` no longer requires `cryptography` / `pywin32` when the session
  cookie is already available (`--cookie`, `OLLAMA_BROWSER_COOKIE`, or Firefox)

### Changed
- Deduplicated the per-model HTML parsing in the scraper into a single
  `_parse_fill_models` helper (removed an unused duplicate)

### Added
- Extensive error-path test suite (264 tests). New `tests/test_cookie.py`
  covers DB copy/lock cleanup, parameterized SQLite queries, Firefox profile
  resolution (relative/absolute paths, malformed/absent `profiles.ini`, glob
  fallback), Chromium key derivation on Windows/macOS/Linux, AES-GCM
  round-trip decryption, browser auto-detection and the environment variable.
  New `tests/test_widget.py` covers the pure widget helpers. The scraper and
  CLI suites gain HTTP 401/403/5xx handling and argument-validation cases.


## [0.1.2] - 2026-05-24

### Fixed
- `_extract_percentages` was silently returning the session percentage for
  both session and weekly on the new Ollama HTML (duplicated values via
  `aria-label`). Now targets the unambiguous `aria-label` on the track divs,
  with a fallback for older HTML.

### Added
- Per-model usage breakdown: `session.models` and `weekly.models` now expose
  `model`, `requests`, `share_pct`, and `color` for each model segment.
- CLI `display()` shows the model breakdown indented under each period.
- Widget (full mode): bar is now segmented by model with the colors from the
  site; a legend with colored squares and request counts appears below each bar.


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