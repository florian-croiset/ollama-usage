# ollama-usage

> Programmatic access to your [Ollama Cloud](https://ollama.com) usage quota — CLI, Python library, notifications and desktop widget.

![CI](https://github.com/florian-croiset/ollama-usage/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.9+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

Two data sources are supported:

| | **API key** | **Session cookie** |
|---|---|---|
| Endpoint | [`ollama.com/api/balance`](https://docs.ollama.com/api/balance) + [`ollama.com/api/usage`](https://docs.ollama.com/api/cloud-usage) | scrapes `ollama.com/dashboard` and the usage report of `ollama.com/settings` |
| Credentials | API key from [ollama.com/settings/keys](https://ollama.com/settings/keys) | auto-detected in Firefox, or copied manually from any browser |
| Usage % + per-model requests, share and cost | ✅ | ✅ |
| Reset date | ✅ | ❌ (not shown on the dashboard since 2026-11) |
| Credits balance | ✅ | ✅ |
| Spend | ✅ last 30 days | ✅ current calendar month |
| Plan name | ✅ (`/api/me`, undocumented, best effort) | ✅ |

Source selection in the CLI: `--api-key` → `--cookie` / `--browser` → `OLLAMA_API_KEY` → `OLLAMA_BROWSER_COOKIE` → Firefox auto-detection.  
In short: set `OLLAMA_API_KEY` and the official API is queried (quota from `/api/balance`, spend and per-model breakdown from `/api/usage`); the session cookie is only read when `/api/balance` can't be. Without a key, only the session cookie is used.

> ℹ️ The API allows 10 requests per minute per user; each refresh makes 2, so `--watch` / the widget refresh at most every 15 s with an API key.  
> The plan name comes from `/api/me`, which is not documented: it is fetched once and kept in memory for 24 hours (retried after 1 hour if it failed), and only its `Plan` field is read — the rest of that response (e-mail, name) is never stored or logged. If Ollama removes it, `plan` is `null` and nothing else changes.

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

With an API key (quota and reset date from `/api/balance`, models and spend over the last 30 days from `/api/usage`):
```
Monthly : 18.4% used — reset at 2026-05-15T08:30:00.123456Z
    deepseek-v3.1:671b      1120 req  ( 54.1%)  $0.65
    gpt-oss:120b             640 req  ( 31.2%)  $0.37
    glm-4.6                  210 req  ( 14.7%)  $0.18
Credits : $5.00
Spend   : $1.20 (30d)
```

The included usage refills on the day and time of the month your plan started (your
sign-up date on the free plan) — not on the 1st: `resets_at` is `included.period.until`
from `/api/balance`.

With the session cookie (adds plan, per-model requests, share and cost of the month, credits balance):
```
Plan    : free
Monthly : 18.4% used
    deepseek-v3.1:671b      1120 req  ( 54.1%)  $0.65
    gpt-oss:120b             640 req  ( 31.2%)  $0.37
    glm-4.6                  210 req  ( 14.7%)  $0.18
Credits : $5.00
Spend   : $1.20 (current month)
```

Since November 2026, `ollama.com/dashboard` shows the share of the included usage left but
no reset date, so with the cookie alone `resets_at` is `null`. The per-model breakdown comes
from the cost report of the current UTC calendar month (not the quota period): `share_pct` is
each model's share of that cost.

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
    "resets_at": null,
    "models": [
      { "model": "deepseek-v3.1:671b", "requests": 1120, "share_pct": 54.1, "color": "#22c55e", "cost_usd": 0.65 },
      { "model": "gpt-oss:120b",       "requests": 640,  "share_pct": 31.2, "color": "#3b82f6", "cost_usd": 0.37 },
      { "model": "glm-4.6",            "requests": 210,  "share_pct": 14.7, "color": "#525252", "cost_usd": 0.18 }
    ]
  },
  "credits_balance": 5.0,
  "spend": {
    "cost_usd": 1.2,
    "period": "current_month",
    "starting_at": "2026-05-01T00:00:00Z",
    "ending_at": "2026-05-07T10:00:00Z"
  },
  "source": "web"
}
```

| Key | Description | API key | Cookie |
|-----|-------------|:-------:|:------:|
| `plan` | `free`, `pro`, `max`… (`null` if it can't be read) | ✅ | ✅ |
| `session` / `weekly` / `monthly` | quota object, or `null` if not part of your plan | ✅ | ✅ |
| `…used_pct` | percentage of the quota used | ✅ | ✅ |
| `…resets_at` | ISO 8601 reset date (when the included usage refills) | ✅ | `null` |
| `…models[].model` / `.requests` | per-model request count | ✅ | ✅ |
| `…models[].share_pct` / `.cost_usd` | share of the cost and cost in USD (last 30 days with the API, current month with the cookie) | ✅ | ✅ |
| `…models[].color` | color of the model on ollama.com | `null` | ✅ |
| `credits_balance` | purchased usage credits balance in USD | ✅ | ✅ |
| `spend` | `{cost_usd, period, starting_at, ending_at}`: last 30 days (API, `period` `"30d"`) or current month (cookie, `period` `"current_month"`) | ✅ | ✅ |
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

### With an API key (official endpoints)
```python
import os
from ollama_usage import get_usage_api

usage = get_usage_api(os.environ["OLLAMA_API_KEY"])

print(usage["monthly"]["used_pct"])         # 18.4
print(usage["monthly"]["resets_at"])        # "2026-05-15T08:30:00.123456Z"
print(usage["credits_balance"])             # 5.0
print(usage["spend"]["cost_usd"])           # 1.2 (last 30 days)
print(usage["plan"])                        # "free" (from /api/me, None if unavailable)
```

If `/api/balance` can't be read, the dashboard can supply the quota (it looks for
a cookie in `OLLAMA_BROWSER_COOKIE` or Firefox, or takes one you pass):
```python
from ollama_usage import get_usage_with_fallback

usage = get_usage_with_fallback(os.environ["OLLAMA_API_KEY"])   # or (key, cookie)
print(usage["monthly"]["used_pct"], usage["spend"]["cost_usd"])
```

### With the session cookie
```python
from ollama_usage import get_usage
from ollama_usage.cookie import get_cookie_auto

cookie = get_cookie_auto()
usage = get_usage(cookie)

print(usage["plan"])                        # "free"
print(usage["monthly"]["used_pct"])         # 18.4
print(usage["monthly"]["resets_at"])        # None (not shown by ollama.com since 2026-11)
print(usage["credits_balance"])             # 5.0
print(usage["spend"]["cost_usd"])           # 1.2 (current month)
for m in usage["monthly"]["models"]:
    print(m["model"], m["requests"], m["cost_usd"])   # "deepseek-v3.1:671b" 1120 0.65
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
1. Go to `https://ollama.com/dashboard`
2. Open DevTools → Application → Cookies → `ollama.com`
3. Copy the value of `__Secure-session`

**Firefox**
1. Go to `https://ollama.com/dashboard`
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
- [x] Official usage API with an API key (`ollama.com/api/balance` + `/api/usage`, `--api-key`, `OLLAMA_API_KEY`)
- [x] Plan name with an API key (`/api/me`, cached in memory for 24 h)
- [ ] Drop scraping once a documented endpoint exposes the plan name

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

MIT — see [LICENSE](LICENSE).

---

## Disclaimer

This project is not affiliated with Ollama.  
It relies on the ollama.com API and on scraping `ollama.com/dashboard` and `ollama.com/settings`; either may break if Ollama changes them.  
If it breaks, please [open an issue](https://github.com/florian-croiset/ollama-usage/issues).