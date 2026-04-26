# ollama-usage

> Programmatic access to your [Ollama Cloud](https://ollama.com) usage quota — until an official API exists.

![CI](https://github.com/florian-croiset/ollama-usage/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.9+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

Ollama does not yet expose a `/api/me` endpoint for quota data ([issue #12532](https://github.com/ollama/ollama/issues/12532)).  
This library fills that gap by reading your session cookie and scraping `ollama.com/settings`.

> ⚠️ This is a workaround. Once Ollama ships an official API, this library will migrate to it.

---

## Installation
```bash
pip install git+https://github.com/florian-croiset/ollama-usage
```

### With desktop notifications support
```bash
pip install "ollama-usage[notify] @ git+https://github.com/florian-croiset/ollama-usage"
```
---

## CLI Usage
```bash
# Auto-detect browser and display usage
ollama-usage

# Output as JSON
ollama-usage --json

# Force a specific browser
ollama-usage --browser firefox
ollama-usage --browser chrome

# Pass cookie manually
ollama-usage --cookie YOUR_SESSION_COOKIE

# Pass cookie via environment variable
export OLLAMA_BROWSER_COOKIE=YOUR_SESSION_COOKIE
ollama-usage

# One-line usage
OLLAMA_BROWSER_COOKIE=YOUR_SESSION_COOKIE ollama-usage --json

# Watch mode (refresh every 30s)
ollama-usage --watch
ollama-usage --watch --json
ollama-usage --watch --interval 60

# Alert mode — exit code 1 if usage exceeds 80%
ollama-usage --alert 80

# Quiet mode — no output, only exit code (useful in scripts/cron)
ollama-usage --quiet --alert 80

# One-shot — notify if usage exceeds 80% (default threshold)
ollama-usage --notify

# One-shot — notify if usage exceeds 75%
ollama-usage --notify --notify-threshold 75

# Watch mode — notify when threshold is crossed, no spam between ticks
ollama-usage --notify --watch

# Watch mode — custom threshold and refresh interval
ollama-usage --notify --watch --notify-threshold 75 --interval 60

# Debug mode
ollama-usage --debug
ollama-usage --debug --browser firefox

# Version
ollama-usage --version

# Help
ollama-usage --help
```

### Example output
```
Plan    : free
Session : 0.0% used — resets at 2026-04-04T17:00:00Z
Weekly  : 33.3% used — resets at 2026-04-06T00:00:00Z
```

Session and weekly percentages are color-coded in the terminal:
- 🟢 Green — below 50%
- 🟡 Yellow — between 50% and 80%
- 🔴 Red — above 80%

```json
{
  "plan": "free",
  "session": {
    "used_pct": 0.0,
    "resets_at": "2026-04-04T00:00:00Z"
  },
  "weekly": {
    "used_pct": 33.3,
    "resets_at": "2026-04-06T00:00:00Z"
  }
}
```

---

## Alert & scripting

`--alert PCT` exits with code 1 if session **or** weekly usage exceeds `PCT%`.  
Combine with `--quiet` to suppress all output and use only the exit code.

```bash
# Cron: send a notification if weekly usage exceeds 90%
ollama-usage --quiet --alert 90 || notify-send "Ollama quota warning"

# Bash script
if ! ollama-usage --quiet --alert 75; then
  echo "Quota running low!"
fi
```

---

## Desktop notifications

`--notify` sends a native desktop notification when session **or** weekly usage crosses a threshold.  
Requires the `notify` extra: `pip install "ollama-usage[notify] @ git+https://..."`

Two levels are fired automatically:
- ⚠️ **Warning** — at the configured threshold (default: 80%)
- 🔴 **Critical** — 15% above the threshold (capped at 100%)

Each level notifies **once per threshold crossing** — no spam during `--watch`.  
If usage drops back below the threshold, the notification will fire again if it rises once more.
```bash
# One-shot — notify if usage exceeds 80%
ollama-usage --notify

# Custom threshold
ollama-usage --notify --notify-threshold 75

# Continuous monitoring with notifications
ollama-usage --notify --watch
ollama-usage --notify --watch --notify-threshold 75 --interval 60
```

---

## Python Usage
```python
from ollama_usage import get_usage
from ollama_usage.cookie import get_cookie_auto

cookie = get_cookie_auto()
usage = get_usage(cookie)

print(usage["plan"])                        # "free"
print(usage["session"]["used_pct"])         # 0.0
print(usage["weekly"]["resets_at"])         # "2026-04-06T00:00:00Z"
```

### Error handling
```python
from ollama_usage import get_usage
from ollama_usage.exceptions import AuthError, NetworkError, ParseError

try:
    usage = get_usage(cookie)
except AuthError:
    print("Cookie expired — please refresh it.")
except NetworkError:
    print("Could not reach ollama.com.")
except ParseError:
    print("Unexpected page structure — open an issue.")
```

---

## Finding your cookie manually

If auto-detection fails, grab your cookie manually:

**Chrome / Edge / Brave**
1. Go to `https://ollama.com/settings`
2. Open DevTools → Application → Cookies → `ollama.com`
3. Copy the value of `__Secure-session`

**Firefox**
1. Go to `https://ollama.com/settings`
2. Open DevTools → Storage → Cookies → `https://ollama.com`
3. Copy the value of `__Secure-session`

Then pass it with `--cookie` or directly in Python.

---

## Supported browsers

| Browser | Windows | Linux | macOS |
|---------|---------|-------|-------|
| Chrome  | ✅ | ✅ | ✅ |
| Firefox | ✅ | ✅ | ✅ |
| Edge    | ✅ | ✅ | ✅ |
| Brave   | ✅ | ✅ | ✅ |
| Opera   | ✅ | ✅ | ✅ |
| Safari  | ❌ | ❌ | 🚧 |

---

## Security note

Depending on your operating system and browser, you may see a security prompt asking for permission to access your browser cookies or local browser data.

This is expected — the library reads your local browser cookie database to authenticate.

Allow access to continue.

---

## Roadmap

- [x] CLI with `--json`, `--browser`, `--cookie`
- [x] Python library API
- [x] Auto browser detection
- [x] `--watch` mode
- [x] Colored output
- [x] `--alert` and `--quiet` for scripting
- [x] Desktop notifications with `--notify`
- [x] Environment variable support (`OLLAMA_BROWSER_COOKIE`)
- [ ] Safari support
- [ ] Migrate to official `/api/me` when available ([#12532](https://github.com/ollama/ollama/issues/12532))

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

MIT — see [LICENSE](LICENSE).

---

## Disclaimer

This project is not affiliated with Ollama.  
It relies on scraping and may break if Ollama changes their HTML structure.  
If it breaks, please [open an issue](https://github.com/florian-croiset/ollama-usage/issues).