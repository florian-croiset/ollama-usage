# ollama-usage

> Your [Ollama Cloud](https://ollama.com) quota, credits and per-model usage, from
> the official API — in the terminal, in Python, in Rust, or as JSON.

[![CI](https://github.com/florian-croiset/ollama-usage/actions/workflows/ci.yml/badge.svg)](https://github.com/florian-croiset/ollama-usage/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

```console
$ ollama-usage
Plan     free
Monthly  [███░░░░░░░░░░░░░░░░░]   12.5%   resets in 21d 12h
Credits  included $4.38 / $5.00  ·  purchased $0.00
Usage    last 30 days  ·  120 req  ·  $0.80
           model-a       60 req  $0.40   50.0%
           model-b       40 req  $0.30   37.5%
           other models  20 req  $0.10   12.5%
```

One API key is all it needs. Each run reads two documented endpoints and one
undocumented one:

| What | Where it comes from |
| --- | --- |
| Monthly usage, its start and reset time (current plans) | [`/api/balance`](https://docs.ollama.com/api/balance): included credits used out of the allowance |
| Session and weekly windows (plans from before the [2026-08-31 pricing change](https://ollama.com/blog/transparent-pricing)) | [`/api/balance`](https://docs.ollama.com/api/balance) |
| Included and purchased credit balances | [`/api/balance`](https://docs.ollama.com/api/balance) |
| Requests, cost and tokens, in total and for the ten most expensive models, over 24 hours, 7 days or 30 days | [`/api/usage`](https://docs.ollama.com/api/cloud-usage) |
| Plan name | `/api/me` (undocumented, best effort, only its `Plan` field is read) |

Since version 1.0 nothing is scraped from ollama.com pages and no browser cookie
is read. Coming from 0.x? See [MIGRATING.md](MIGRATING.md).

## Installation

**Python package**, which also installs the `ollama-usage` command:

```bash
pip install git+https://github.com/florian-croiset/ollama-usage
```

This compiles the package, so it needs a Rust toolchain
([rustup](https://rustup.rs)). Each [release](https://github.com/florian-croiset/ollama-usage/releases)
also provides prebuilt wheels for Python 3.10 and later, and standalone binaries
of the command, which need nothing else.

**Command only**, with Cargo:

```bash
cargo install --git https://github.com/florian-croiset/ollama-usage ollama-usage-cli
```

## The API key

Create a key at [ollama.com/settings/keys](https://ollama.com/settings/keys).
It is the same kind of key used to run Ollama Cloud models. The command looks for
it in this order:

1. `--api-key KEY`, which your shell history keeps, so prefer the next one;
2. the `OLLAMA_API_KEY` environment variable;
3. `api_key` in the configuration file:

   | OS | Configuration file |
   | --- | --- |
   | Linux | `~/.config/ollama-usage/config.toml`, or under `$XDG_CONFIG_HOME` |
   | macOS | `~/Library/Application Support/ollama-usage/config.toml` |
   | Windows | `%APPDATA%\ollama-usage\config.toml` |

   ```toml
   api_key = "…"
   ```

   `--config PATH` reads another file. An unknown setting is an error, so a typo
   does not go unnoticed.

The Python and Rust libraries read nothing on their own: pass them the key.

## Command line

| Option | Effect |
| --- | --- |
| `--range 24h\|7d\|30d` | Period of the usage breakdown. Default `30d`. |
| `--json` | Print the [JSON report](#json-report) instead of the table. |
| `--alert PCT` | Exit with code 1 when a quota window is at or above `PCT` percent, and say which on stderr. |
| `-q`, `--quiet` | Print nothing at all; only the exit code tells the outcome. |
| `--config PATH` | Read the configuration from `PATH`. |
| `--debug` | Log each request, its status and duration to stderr. The key is never logged. |

On a plan from before the pricing change the table shows two windows instead:

```console
$ ollama-usage
Plan     pro
Session  [███░░░░░░░░░░░░░░░░░]   12.5%   resets in 3h 0m
Weekly   [████████░░░░░░░░░░░░]   40.0%   resets in 1d 12h
Credits  purchased $2.50
Usage    last 30 days  ·  120 req  ·  $0.80
…
```

Percentages are green below 50 %, yellow up to 80 % and red beyond. Colours are
used only on a terminal; set [`NO_COLOR`](https://no-color.org) to turn them off
or `FORCE_COLOR` to force them. Warnings go to stderr, so `--json` output stays
parseable.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | ok |
| `1` | `--alert` threshold reached |
| `2` | partial report: `/api/balance` or `/api/usage` failed, the other answered |
| `3` | no report: both failed, or ollama.com rate-limited the key |
| `4` | no API key, or the key was rejected |
| `64` | invalid arguments or configuration |

An alert takes precedence over a partial report. In a cron job:

```bash
ollama-usage --quiet --alert 90 || notify-send "Ollama quota above 90 %, or the check failed"
```

## Python

```python
import os
from ollama_usage import Client

client = Client(os.environ["OLLAMA_API_KEY"])
report = client.fetch()            # or fetch("24h"), fetch("7d")

for name, window in report.windows.items():
    print(name, window.used_pct, window.resets_at)    # monthly 12.5 2026-02-01 00:00:00+00:00

if report.usage:
    for model in report.usage.models:
        print(model.model, model.requests, model.cost_usd, model.share_pct)
```

The report is made of read-only dataclasses that mirror the
[JSON report](#json-report). `report.to_dict()` gives the JSON form and
`Report.from_dict()` reads it back, for instance from `ollama-usage --json`.

A fetch raises only when no report can be built at all:

```python
from ollama_usage import ApiError, AuthError, NetworkError, RateLimitedError

try:
    report = client.fetch()
except AuthError:
    ...  # key rejected, or account suspended
except RateLimitedError as error:
    ...  # retry after error.retry_after seconds (None if ollama.com did not say)
except (NetworkError, ApiError):
    ...  # both endpoints failed
else:
    if report.is_partial:
        for warning in report.warnings:
            print(warning.code, warning.message)  # e.g. usage_unavailable
```

The client releases the GIL while it waits, and keeps the plan name for a day, so
reuse one client rather than creating one per call.

[`examples/`](examples/) has complete scripts: the quota windows
([`quota.py`](examples/quota.py)), the usage per model ([`models.py`](examples/models.py)),
an alert on usage or on the included credits left ([`alert.py`](examples/alert.py)), and
polling that respects the rate limit ([`watch.py`](examples/watch.py)).

## Rust

```toml
[dependencies]
ollama-usage = { git = "https://github.com/florian-croiset/ollama-usage" }
```

```rust
use ollama_usage::{Client, Range};

let client = Client::new(std::env::var("OLLAMA_API_KEY")?);
let report = client.fetch(Range::Days30)?;
println!("{}", serde_json::to_string_pretty(&report)?);
```

The client is blocking and `Send + Sync`. `cargo doc --open -p ollama-usage`
documents every type.

## JSON report

`--json`, `Report.to_dict()` and the Rust `Report` produce the same document,
described by [`schemas/usage-report-1.0.json`](schemas/usage-report-1.0.json).
Within version 1.x fields are only ever added, so check `schema_version` rather
than the package version. Fields that do not apply, or could not be read, are
`null`.

```json
{
  "schema_version": "1.0",
  "fetched_at": "2026-01-10T12:00:00Z",
  "plan": "free",
  "windows": {
    "monthly": {
      "used_pct": 12.5,
      "starts_at": "2026-01-01T00:00:00Z",
      "resets_at": "2026-02-01T00:00:00Z"
    },
    "session": null,
    "weekly": null
  },
  "credits": {
    "included": { "balance_usd": 4.375, "allowance_usd": 5.0, "spent_usd": 0.625 },
    "purchased_balance_usd": 0.0
  },
  "usage": {
    "range": "30d",
    "from": "2025-12-11T00:00:00Z",
    "until": "2026-01-10T12:00:00Z",
    "requests": 120,
    "cost_usd": 0.8,
    "input_tokens": 50000,
    "cached_input_tokens": 10000,
    "output_tokens": 20000,
    "models": [
      {
        "model": "model-a",
        "requests": 60,
        "cost_usd": 0.4,
        "input_tokens": 25000,
        "cached_input_tokens": 5000,
        "output_tokens": 10000,
        "share_pct": 50.0
      }
    ],
    "other": null
  },
  "warnings": []
}
```

When reading it:

- `usage` covers a fixed range ending now, not the quota period. What was used in
  the current period is `credits.included.spent_usd`.
- `share_pct` is a share of the cost, or of the requests when nothing was billed.
- `other` combines the models beyond the ten that `/api/usage` lists one by one.
- `warnings[].code` is stable: `balance_unavailable`, `usage_unavailable`,
  `plan_unavailable`, `monthly_allowance_missing`, `no_quota_window`. Later 1.x
  versions may add codes.

## Rate limits

The API allows 10 requests per minute per user, shared by every key and device.
A fetch makes two, plus one to `/api/me` the first time a client is used and then
once a day. When ollama.com rate-limits the key, the error says how long it asked
to wait.

## Privacy and security

- The key is sent only to `https://ollama.com`, redirects are not followed, and
  it never appears in logs, errors or debug output.
- `/api/me` also returns your name and e-mail address; only the plan name is read.
- Nothing is written to disk, and there is no telemetry.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).

## Disclaimer

This project is not affiliated with Ollama. `/api/me` is undocumented and may
change; if it does, `plan` becomes `null` and nothing else breaks. If something
else breaks, please [open an issue](https://github.com/florian-croiset/ollama-usage/issues).
