# ollama-usage

> Programmatic access to your [Ollama Cloud](https://ollama.com) usage quota — CLI, Python library, notifications and desktop widget.

![CI](https://github.com/florian-croiset/ollama-usage/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.9+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

Two data sources are supported:

| | **API key** (recommended) | **Session cookie** |
|---|---|---|
| Endpoint | `ollama.com/api/usage` | scrapes `ollama.com/settings` |
| Credentials | API key from [ollama.com/settings/keys](https://ollama.com/settings/keys) | auto-detected in Firefox, or copied manually from any browser |
| Usage % + per-model requests | ✅ | ✅ |
| Spend over the last 4 weeks | ✅ | ❌ |
| Plan name, reset dates, credits balance, per-model share | ❌ | ✅ |

Source selection in the CLI: `--api-key` → `--cookie` / `--browser` → `OLLAMA_API_KEY` → `OLLAMA_BROWSER_COOKIE` → Firefox auto-detection.  
In short: set `OLLAMA_API_KEY` and the official API is used; without it, the session cookie is used.

> ⚠️ `ollama.com/api/usage` is not documented by Ollama yet ([issue #12532](https://github.com/ollama/ollama/issues/12532)) and may change.

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
# Official API with an ollama.com API key (recommended: environment variable)
export OLLAMA_API_KEY=YOUR_API_KEY
ollama-usage
ollama-usage --api-key YOUR_API_KEY

# No API key: read the session cookie from Firefox
ollama-usage
ollama-usage --browser firefox

# Output as JSON
ollama-usage --json

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

# Desktop widget (always on top, right-click for menu)
ollama-usage --widget
ollama-usage --widget --theme light --size compact --opacity 0.8 --position bottom-right

# Debug mode
ollama-usage --debug
ollama-usage --debug --browser firefox

# Version
ollama-usage --version

# Help
ollama-usage --help
```

### Supported plans

Since August 31, 2026, Ollama Cloud uses monthly usage credits. `ollama-usage` supports both pricing models:

| Plan | Quotas reported |
|------|-----------------|
| Free, Pro, Max, Team (credit-based) | `monthly` |
| Legacy Pro / Max subscriptions (started before the switch) | `session` (5 h) + `weekly` |

Quotas that don't apply to your plan are returned as `null` and hidden from the text output.

### Example output

With an API key:
```
Monthly : 18.4% used
    deepseek-v3.1:671b       112 req
    gpt-oss:120b              64 req
    web search                21 req
Spend   : $1.20 (last 4 weeks)
```

With the session cookie (adds plan, reset date, per-model share and credits balance):
```
Plan    : free
Monthly : 18.4% used — reset at 2026-10-01T00:00:00Z
    deepseek-v3.1:671b       112 req  ( 54.1%)
    gpt-oss:120b              64 req  ( 31.2%)
    web search                21 req  ( 14.7%)
Credits : $5.00
```

Legacy Pro / Max subscription:
```
Plan    : pro
Session : 12.0% used — reset at 2026-04-04T15:00:00Z
    qwen3-coder:480b          42 req  ( 55.0%)
Weekly  : 40.0% used — reset at 2026-04-06T00:00:00Z
    qwen3-coder:480b          42 req  ( 25.0%)
```

Usage percentages are color-coded in the terminal:
- 🟢 Green — below 50%
- 🟡 Yellow — between 50% and 80%
- 🔴 Red — above 80%

Colors are only used when writing to a terminal (not in pipes, files or cron). Set [`NO_COLOR`](https://no-color.org) to disable them, or `FORCE_COLOR` to force them.

### JSON output (`--json`)

Both sources return the same keys; fields a source can't provide are `null`.

```json
{
  "plan": "free",
  "session": null,
  "weekly": null,
  "monthly": {
    "used_pct": 18.4,
    "resets_at": "2026-10-01T00:00:00Z",
    "models": [
      { "model": "deepseek-v3.1:671b", "requests": 112, "share_pct": 54.1, "color": "#22c55e" },
      { "model": "gpt-oss:120b",       "requests": 64,  "share_pct": 31.2, "color": "#3b82f6" },
      { "model": "web search",         "requests": 21,  "share_pct": 14.7, "color": "#525252" }
    ]
  },
  "credits_balance": 5.0,
  "spend": null,
  "source": "web"
}
```

| Key | Description | API key | Cookie |
|-----|-------------|:-------:|:------:|
| `plan` | `free`, `pro`, `max`… | `null` | ✅ |
| `session` / `weekly` / `monthly` | quota object, or `null` if not part of your plan | ✅ | ✅ |
| `…used_pct` | percentage of the quota used | ✅ | ✅ |
| `…resets_at` | ISO 8601 reset date | `null` | ✅ |
| `…models[].model` / `.requests` | per-model request count | ✅ | ✅ |
| `…models[].share_pct` / `.color` | share of the usage bar and its color | `null` | ✅ |
| `credits_balance` | usage credits balance in USD | `null` | ✅ |
| `spend` | `{cost_usd, period, starting_at, ending_at}` over the last 4 weeks | ✅ | `null` |
| `source` | `"api"` or `"web"` | | |

---

## Alert & scripting

`--alert PCT` exits with code 1 if any quota (monthly, session **or** weekly) exceeds `PCT%`.  
Combine with `--quiet` to suppress all output and use only the exit code.

```bash
# Cron: send a notification if usage exceeds 90%
ollama-usage --quiet --alert 90 || notify-send "Ollama quota warning"

# Bash script
if ! ollama-usage --quiet --alert 75; then
  echo "Quota running low!"
fi
```

---

## Desktop notifications

`--notify` sends a native desktop notification when any quota (monthly, session **or** weekly) crosses a threshold.  
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

### With an API key (official endpoint)
```python
import os
from ollama_usage import get_usage_api

usage = get_usage_api(os.environ["OLLAMA_API_KEY"])

print(usage["monthly"]["used_pct"])         # 18.4
print(usage["spend"]["cost_usd"])           # 1.2 (last 4 weeks)
for m in usage["monthly"]["models"]:
    print(m["model"], m["requests"])        # "gpt-oss:120b" 64
# plan, resets_at, credits_balance and share_pct are None with this source
```

### With the session cookie
```python
from ollama_usage import get_usage
from ollama_usage.cookie import get_cookie_auto

cookie = get_cookie_auto()
usage = get_usage(cookie)

print(usage["plan"])                        # "free"
print(usage["monthly"]["used_pct"])         # 18.4
print(usage["monthly"]["resets_at"])        # "2026-10-01T00:00:00Z"
print(usage["credits_balance"])             # 5.0
for m in usage["monthly"]["models"]:
    print(m["model"], m["requests"])        # "deepseek-v3.1:671b" 112
```

Both functions return the same keys (`source` is `"api"` or `"web"`). To handle every plan (credit-based or legacy session/weekly) the same way:
```python
from ollama_usage import iter_periods

for key, period in iter_periods(usage):     # skips quotas set to None
    print(key, period["used_pct"], period["resets_at"])
```

### Error handling
```python
from ollama_usage import get_usage, get_usage_api
from ollama_usage.exceptions import AuthError, NetworkError, ParseError

try:
    usage = get_usage_api(api_key)          # or get_usage(cookie)
except AuthError:
    print("API key invalid/revoked, or cookie expired.")
except NetworkError:
    print("Could not reach ollama.com.")
except ParseError:
    print("Unexpected response or page structure — open an issue.")
```

---

## Getting an API key

1. Go to [ollama.com/settings/keys](https://ollama.com/settings/keys)
2. Create a new key and copy it
3. Export it: `export OLLAMA_API_KEY=...` (PowerShell: `$env:OLLAMA_API_KEY = "..."`)

This is the same key used for Ollama Cloud models, so no browser access is needed.

---

## Finding your cookie manually

Only Firefox is read automatically. With any other browser (or if auto-detection fails), copy the cookie manually — or simply use an [API key](#getting-an-api-key):

**Chrome / Edge / Brave**
1. Go to `https://ollama.com/settings`
2. Open DevTools → Application → Cookies → `ollama.com`
3. Copy the value of `__Secure-session`

**Firefox**
1. Go to `https://ollama.com/settings`
2. Open DevTools → Storage → Cookies → `https://ollama.com`
3. Copy the value of `__Secure-session`

Then pass it with `--cookie`, `OLLAMA_BROWSER_COOKIE`, or directly in Python.

---

## Supported browsers (cookie auto-detection)

| Browser | Windows | Linux | macOS |
|---------|---------|-------|-------|
| Firefox | ✅ | ✅ (incl. Snap / Flatpak) | ✅ |
| Chrome, Edge, Brave, Opera | ❌ | ❌ | ❌ |
| Safari  | ❌ | ❌ | ❌ |

Chromium-based browsers encrypt their cookies (App-Bound Encryption on Windows since Chrome 127, OS keyring on macOS / Linux), so they can't be read reliably without elevated privileges or keyring access. Use an API key or copy the cookie manually instead.

---

## Security note

**API key** — it grants access to your Ollama account and cloud usage (which can be billed). Prefer the `OLLAMA_API_KEY` environment variable over `--api-key`, which ends up in your shell history. The key is never logged, even with `--debug`.

**Session cookie** — the library reads a temporary copy of your Firefox cookie database (deleted right after) to authenticate. If your OS asks for permission to access Firefox data, this is expected: allow access to continue, or use an API key instead.

---

## Roadmap

- [x] CLI with `--json`, `--browser`, `--cookie`
- [x] Always-on-top desktop widget (`--widget`)
- [x] Python library API
- [x] Firefox cookie auto-detection (Chromium support removed: encrypted cookies)
- [x] `--watch` mode
- [x] Colored output
- [x] `--alert` and `--quiet` for scripting
- [x] Desktop notifications with `--notify`
- [x] Environment variable support (`OLLAMA_BROWSER_COOKIE`)
- [x] Per-model usage breakdown (`session.models`, `weekly.models`)
- [x] Credit-based plans (`monthly`, `credits_balance`)
- [x] Official usage API with an API key (`ollama.com/api/usage`, `--api-key`, `OLLAMA_API_KEY`)
- [ ] Drop scraping once `/api/usage` exposes plan, reset dates and credits balance

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

MIT — see [LICENSE](LICENSE).

---

## Disclaimer

This project is not affiliated with Ollama.  
It relies on an undocumented API endpoint and on scraping `ollama.com/settings`; either may break if Ollama changes them.  
If it breaks, please [open an issue](https://github.com/florian-croiset/ollama-usage/issues).