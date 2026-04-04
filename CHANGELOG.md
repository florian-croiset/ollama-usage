# Changelog

All notable changes to this project will be documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

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