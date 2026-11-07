"""Poll the quota and print a line whenever a window moves.

One client is kept for the whole run, so the plan name is fetched once. Each
poll makes two requests out of the 10 per minute the API allows; when it is
rate-limited anyway, the wait ollama.com asks for is respected.

Usage:
    OLLAMA_API_KEY=... python examples/watch.py [--every SECONDS]
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime

from ollama_usage import AuthError, Client, OllamaUsageError, RateLimitedError

MINIMUM_INTERVAL = 30


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--every", type=int, default=60, help="seconds between polls")
    args = parser.parse_args()
    interval = max(args.every, MINIMUM_INTERVAL)

    key = os.environ.get("OLLAMA_API_KEY", "")
    if not key.strip():
        print("Set OLLAMA_API_KEY to a key from https://ollama.com/settings/keys", file=sys.stderr)
        return 1
    client = Client(key)
    last: dict[str, float] = {}

    try:
        while True:
            wait = interval
            try:
                report = client.fetch("24h")
            except AuthError as error:
                print(f"error: {error}", file=sys.stderr)
                return 1
            except RateLimitedError as error:
                wait = max(interval, int(error.retry_after or 0))
                print(f"rate-limited, next poll in {wait} s", file=sys.stderr)
            except OllamaUsageError as error:
                print(f"{error}; retrying in {wait} s", file=sys.stderr)
            else:
                current = {name: window.used_pct for name, window in report.windows.items()}
                if current != last:
                    stamp = datetime.now().strftime("%H:%M:%S")
                    usage = ", ".join(f"{name} {pct:.1f}%" for name, pct in current.items())
                    print(f"{stamp}  {usage or 'no quota window'}")
                    last = current
            time.sleep(wait)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
