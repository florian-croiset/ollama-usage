# Changelog

All notable changes to this project will be documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## Unreleased


## [1.0.0-alpha.3] - 2026-11-08

### Added
- The Python package is published on PyPI as `ollama-cloud-usage`; as a
  pre-release, it installs with `pip install --pre ollama-cloud-usage`

### Fixed
- Certificates are verified with the operating system's trust store instead of a
  bundled list. Behind an antivirus or proxy that inspects TLS, every request
  failed with `invalid peer certificate: UnknownIssuer`

## [1.0.0-alpha.2] - 2026-11-07

### Changed
- The Python package is installed as `ollama-cloud-usage` and imported as
  `ollama_cloud_usage`; the command keeps its name, `ollama-usage`. An unrelated
  project is published on PyPI as `ollama-usage` with the same module and
  command names. Uninstall `ollama-usage` before installing this version


## [1.0.0-alpha.1] - 2026-11-07

Version 1.0 is a rewrite on a Rust core shared by the command and the Python
package. See [MIGRATING.md](https://github.com/florian-croiset/ollama-usage/blob/main/MIGRATING.md) for every change from 0.3.

### Added
- A versioned JSON report, [schema 1.0](https://github.com/florian-croiset/ollama-usage/blob/main/schemas/usage-report-1.0.json), shared by
  `--json`, the Python package and the Rust crate. Fields are only added within 1.x
- Input, cached input and output tokens, in total and per model, and the models
  beyond the first ten combined in `usage.other`
- `--range 24h|7d|30d` (Python: `fetch(range)`) for the usage period
- The included credits of the current period: balance, allowance and amount spent
- The start of the monthly period
- A configuration file holding the API key, and `--config PATH`
- Partial reports: when only one of `/api/balance` and `/api/usage` answers, the
  report carries what it got and `warnings` says what is missing (exit code 2)
- Distinct exit codes for a partial report, a failed fetch, a missing or rejected
  key and invalid arguments
- `RateLimitedError` with the delay ollama.com asked for
- `FORCE_COLOR` forces colours
- A Rust crate, `ollama-usage`
- Python examples in `examples/`: quota, usage per model, an alert on usage or
  credits, and polling

### Changed
- The Python API is a client returning read-only dataclasses:
  `Client(key).fetch()` replaces `get_usage_api(key)`, `report.windows.items()`
  replaces `iter_periods()`, and `ApiError` replaces `ParseError`
- `--alert PCT` fires at `PCT` percent, not only above it
- The text output shows one line per window with a bar and the time left before
  the reset
- Installing from the repository compiles Rust; releases provide prebuilt wheels
  and standalone binaries

### Removed
- Page scraping and the session cookie: `--cookie`, `--browser`,
  `OLLAMA_BROWSER_COOKIE`, Firefox cookie detection, `get_usage(cookie)` and
  `get_usage_with_fallback()`
- `--watch`, `--notify` and the desktop widget
- The `notify` extra, `models[].color` and the `source` field


## [0.3.0] - 2026-11-07

### Fixed
- The usage works again after the November 2026 redesign of ollama.com: the quota
  moved from the settings page to `ollama.com/dashboard`, which is now scraped
  (`used_pct` = 100 − "% left"). The dashboard shows no reset date, so with the
  session cookie `resets_at` is `None`. The previous page layout is still recognised
- A signed-in page mentioning "sign in" is no longer mistaken for the login page

### Added
- With an API key the quota is back without any cookie, from the documented
  `ollama.com/api/balance` endpoint: `used_pct` from the included credits, `resets_at`
  when they refill (the day and time the plan started, not the 1st), `credits_balance`,
  and `session` / `weekly` on legacy plans
- `plan` with an API key, from `ollama.com/api/me` (undocumented, best effort, cached
  in memory for 24 h; only the plan name is read)
- New `models[].cost_usd`. Per-model requests, cost and share come from `/api/usage`
  (last 30 days) with a key, or from the cost report of the month with the cookie
- The CLI shows each model's cost; the widget labels the spend period

### Changed
- Python 3.10 or later is required (3.9 is end of life)
- With an API key, `spend` covers the last 30 days (`period` `"30d"`, was `"7d"`)
- With the cookie, `share_pct` is each model's share of the month's cost, and `spend`
  is the month's cost (`period` `"current_month"`)
- `plan` comes from the dashboard meter label ("Free usage" → `"free"`)
- With an API key, `--watch` and the widget refresh at most every 15 s (API limit of
  10 requests per minute)


## [0.2.1] - 2026-10-08

### Fixed
- Parsing the `ollama.com/settings` page works again: the usage meter is now worded
  "Free usage: 12.5%" (colon, no "used"), which was no longer recognised
- `ollama.com/api/usage` no longer returns `limits`, so an API key alone failed with
  "Usage API response has no 'limits' object". The response is now read as a spend
  time series: `spend` is filled (over the last 7 days, `period` is `"7d"` instead of
  `"last_4_weeks"`) and `session` / `weekly` / `monthly` are `None`

### Added
- `get_usage_with_fallback(api_key, cookie=None)`: calls the API and, since it no
  longer reports the quota, completes it from the settings page when a session cookie
  is given or found (`OLLAMA_BROWSER_COOKIE`, Firefox). The CLI (`--api-key`,
  `OLLAMA_API_KEY`) and the widget use it, and the CLI says so on stderr when no cookie
  could be found


## [0.2.0] - 2026-09-13

### Fixed
- Parsing no longer fails on the new `ollama.com/settings` page introduced
  with credit-based pricing (Aug 31, 2026): the Session / Weekly meters were
  replaced by a single monthly meter ("Free usage", "Pro usage"...)
- Plan names made of several words or containing a hyphen (e.g. "Pro Max")
  no longer make parsing fail

### Added
- Official usage API support: `GET https://ollama.com/api/usage` with an
  ollama.com API key, via `--api-key`, the `OLLAMA_API_KEY` environment
  variable, or `get_usage_api()` in Python. Used in priority when a key is
  available; cookie scraping remains the fallback. The API does not expose the plan,
  reset dates, credits balance or per-model share (returned as `null`)
- `spend`: cost over the last 4 weeks (API source only)
- `source` key (`"api"` or `"web"`) in the usage dict
- `monthly` quota (used %, reset date, per-model breakdown) for Free, Pro,
  Max and Team credit-based plans
- `credits_balance`: current "Usage credits" balance in USD (`null` if absent)
- `iter_periods()` helper to iterate over the quotas present in a usage dict
- Widget countdown shows days for long reset periods (e.g. `29d 00h`)
- Project website (`docs/`, GitHub Pages)

### Removed
- **Breaking:** cookie reading from Chromium-based browsers (Chrome, Edge,
  Brave, Opera). On Windows, Chrome 127+ App-Bound Encryption (`v20` cookies)
  made decryption fail for every cookie; on macOS / Linux the implementation
  used the wrong cipher (AES-GCM instead of AES-128-CBC) and ignored keyring
  (`v11`) keys. `get_cookie_chrome()` & co. and `--browser chrome|edge|brave|opera`
  now raise a clear error pointing to `OLLAMA_API_KEY`, Firefox or `--cookie`.
  Auto-detection only tries Firefox
- `cryptography`, `pywin32` and `colorama` dependencies — the package now has
  **no runtime dependencies**. Terminal colors use plain ANSI codes, with
  Windows 10+ console support enabled through `ctypes` (`SetConsoleMode`)

### Changed
- Colors are no longer written when output is redirected (pipe, file, cron);
  `NO_COLOR` disables them and `FORCE_COLOR` forces them
- `session` and `weekly` are now `null` when the plan has no such limit;
  legacy Pro / Max subscriptions keep reporting them as before
- `--alert`, `--notify`, text output and widget handle whichever quotas the
  plan exposes


## [0.1.3] - 2026-07-11

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