"""Print how much of each quota window is used and when it resets.

Usage:
    OLLAMA_API_KEY=... python examples/quota.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from ollama_usage import Client, OllamaUsageError


def main() -> int:
    key = os.environ.get("OLLAMA_API_KEY", "")
    if not key.strip():
        print("Set OLLAMA_API_KEY to a key from https://ollama.com/settings/keys", file=sys.stderr)
        return 1
    # fetch() raises only when no report can be built: a rejected key, a rate
    # limit, or both endpoints down. Otherwise the report may be partial.
    try:
        report = Client(key).fetch()
    except OllamaUsageError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if report.plan:
        print(f"plan: {report.plan}")
    now = datetime.now(timezone.utc)
    # Only the plan's windows are listed: monthly on current plans, session and
    # weekly on plans from before the 2026-08-31 pricing change.
    for name, window in report.windows.items():
        line = f"{name}: {window.used_pct:.1f}% used"
        if window.resets_at:
            hours = (window.resets_at - now).total_seconds() / 3600
            line += f", resets in {hours:.0f} h"
        print(line)
    # warning.code is stable for scripts; the message is for people.
    for warning in report.warnings:
        print(f"warning: {warning.message}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
