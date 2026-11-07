"""Print the requests, cost and tokens of each model, most expensive first.

Usage:
    OLLAMA_API_KEY=... python examples/models.py [24h|7d|30d]
"""

from __future__ import annotations

import argparse
import os
import sys

from ollama_usage import Client, OllamaUsageError

ROW = "{:<{width}}  {:>8}  {:>10}  {:>10}  {:>10}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("range", nargs="?", default="30d", choices=["24h", "7d", "30d"])
    args = parser.parse_args()

    key = os.environ.get("OLLAMA_API_KEY", "")
    if not key.strip():
        print("Set OLLAMA_API_KEY to a key from https://ollama.com/settings/keys", file=sys.stderr)
        return 1
    try:
        usage = Client(key).fetch(args.range).usage
    except OllamaUsageError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if usage is None:
        print("error: /api/usage did not answer", file=sys.stderr)
        return 1

    rows = [(m.model, m) for m in usage.models]
    if usage.other:
        rows.append(("(other models)", usage.other))
    rows.sort(key=lambda row: row[1].cost_usd, reverse=True)

    width = max(len("model"), *(len(name) for name, _ in rows)) if rows else len("model")
    print(ROW.format("model", "requests", "cost", "input tok", "output tok", width=width))
    for name, part in rows:
        cost = f"${part.cost_usd:.4f}"
        print(
            ROW.format(
                name, part.requests, cost, part.input_tokens, part.output_tokens, width=width
            )
        )
    print(f"{usage.requests} requests, ${usage.cost_usd:.2f} over the last {usage.range}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
