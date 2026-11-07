"""Warn when a quota window is nearly used, or the included credits run low.

``ollama-usage --alert PCT`` covers the percentage; this also watches what is
left of the included credits, in dollars. Exits with 1 when either is reached,
so it fits a cron job; replace ``notify`` with whatever should reach you.

Usage:
    OLLAMA_API_KEY=... python examples/alert.py --percent 80 --credits 0.50
"""

from __future__ import annotations

import argparse
import os
import sys

from ollama_usage import Client, OllamaUsageError


def notify(message: str) -> None:
    print(f"alert: {message}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--percent", type=float, default=80.0, help="window usage, in percent")
    parser.add_argument("--credits", type=float, default=0.5, help="included credits left, in $")
    args = parser.parse_args()

    key = os.environ.get("OLLAMA_API_KEY", "")
    if not key.strip():
        print("Set OLLAMA_API_KEY to a key from https://ollama.com/settings/keys", file=sys.stderr)
        return 1
    try:
        report = Client(key).fetch()
    except OllamaUsageError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    reached = False
    for name, window in report.windows.items():
        if window.used_pct >= args.percent:
            notify(f"{name} usage at {window.used_pct:.1f}%")
            reached = True
    included = report.credits.included if report.credits else None
    if included and included.balance_usd <= args.credits:
        notify(f"${included.balance_usd:.2f} of included credits left")
        reached = True
    return 1 if reached else 0


if __name__ == "__main__":
    sys.exit(main())
