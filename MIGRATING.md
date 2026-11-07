# Migrating from 0.x to 1.0

Version 1.0 is a rewrite. It reads only the Ollama Cloud API with an API key,
from a Rust core that the command and the Python package share. This page lists
everything that changed for someone using 0.3.

## You need an API key

The session cookie, browser auto-detection and page scraping are gone, and so are
`--cookie`, `--browser` and `OLLAMA_BROWSER_COOKIE`. Create a key at
[ollama.com/settings/keys](https://ollama.com/settings/keys) and set
`OLLAMA_API_KEY`, as before, or put it in the
[configuration file](README.md#the-api-key).

With a key, 0.3 already used the API. 1.0 adds the token counts and the choice of
range, and no longer falls back to the dashboard when `/api/balance` fails: the
report is then partial.

## Installation

`pip install git+https://github.com/florian-croiset/ollama-usage` still installs
the library and the `ollama-usage` command, but now compiles Rust: install a
toolchain with [rustup](https://rustup.rs), or take a prebuilt wheel from the
[releases](https://github.com/florian-croiset/ollama-usage/releases). Python 3.10
or later is still required. The `notify` extra no longer exists.

## Command line

| 0.3 | 1.0 |
| --- | --- |
| `--api-key`, `--json`, `--quiet`, `--debug`, `--version` | unchanged |
| `--alert PCT`: above `PCT`, `⚠️  Warning: usage exceeds PCT%` | at or above `PCT`, `alert: monthly usage at 85.0%, threshold 80%` for each window reached |
| `--cookie`, `--browser` | removed: use an API key |
| `--watch`, `--interval` | removed |
| `--notify`, `--notify-threshold` | removed |
| `--widget`, `--theme`, `--size`, `--opacity`, `--position` | removed |
| | new: `--range 24h\|7d\|30d`, `--config PATH` |

The table is laid out differently: one line per window with a bar and the time
left before the reset, the credits on one line, then the usage per model.

### Exit codes

0.3 exited with 1 both when the alert fired and on any error, so
`ollama-usage --quiet --alert 90 || …` still runs its fallback in both cases.
Each outcome now has its own code:

| Code | Meaning |
| --- | --- |
| `0` | ok |
| `1` | `--alert` threshold reached |
| `2` | partial report |
| `3` | no report: both endpoints failed, or the key was rate-limited |
| `4` | no API key, or the key was rejected |
| `64` | invalid arguments or configuration |

## JSON output

The report now follows a versioned schema,
[`schemas/usage-report-1.0.json`](schemas/usage-report-1.0.json).

| 0.3 | 1.0 |
| --- | --- |
| `plan` | `plan` |
| `monthly`, `session`, `weekly` | `windows.monthly`, `windows.session`, `windows.weekly` |
| `….used_pct`, `….resets_at` | unchanged, inside each window |
| | `windows.monthly.starts_at`: start of the period |
| `….models[]` (inside a window) | `usage.models[]`: the usage is no longer attached to a window |
| `….models[].model`, `.requests`, `.cost_usd`, `.share_pct` | unchanged |
| `….models[].color` | removed: it came from the page |
| | `usage.models[].input_tokens`, `.cached_input_tokens`, `.output_tokens` |
| | `usage.other`: the models beyond the first ten, combined |
| `credits_balance` | `credits.purchased_balance_usd` |
| | `credits.included`: `balance_usd`, `allowance_usd`, `spent_usd` |
| `spend.cost_usd` | `usage.cost_usd` |
| `spend.period`, `spend.starting_at`, `spend.ending_at` | `usage.range`, `usage.from`, `usage.until` |
| `source` | removed: always the API |
| | `schema_version`, `fetched_at`, `warnings` |

`spend` covered the last 30 days with a key and the calendar month with a cookie.
`usage` always covers the range you ask for; what was used in the current quota
period is `credits.included.spent_usd`.

## Python

The functions returning a `dict` are replaced by a client returning typed,
read-only objects.

```python
# 0.3
from ollama_usage import get_usage_api, iter_periods

usage = get_usage_api(api_key)
for key, period in iter_periods(usage):
    print(key, period["used_pct"])
print(usage["credits_balance"])

# 1.0
from ollama_usage import Client

report = Client(api_key).fetch()
for name, window in report.windows.items():
    print(name, window.used_pct)
print(report.credits.purchased_balance_usd)
```

| 0.3 | 1.0 |
| --- | --- |
| `get_usage_api(key)` | `Client(key).fetch()` |
| `get_usage(cookie)`, `get_usage_with_fallback(key, cookie)` | removed |
| `iter_periods(usage)` | `report.windows.items()` |
| `usage["…"]` | attributes, e.g. `report.windows.monthly.used_pct`; `report.to_dict()` gives the JSON form |
| `ollama_usage.cookie`, `ollama_usage.widget`, `ollama_usage.notify` | removed |
| `AuthError`, `NetworkError`, `OllamaUsageError` | unchanged, imported from `ollama_usage` |
| `ParseError` | `ApiError` |
| | `RateLimitedError`, with `retry_after` |
| `BrowserNotFoundError`, `UnsupportedOSError` | removed |

Timestamps are timezone-aware `datetime` objects rather than strings.
