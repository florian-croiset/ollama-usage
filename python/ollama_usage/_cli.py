"""Entry point of the ``ollama-usage`` command installed with the package."""

from __future__ import annotations

import sys
from typing import NoReturn

from . import _ollama_usage


def main() -> NoReturn:
    """Runs the command-line tool with the process arguments and exits with its code."""
    sys.exit(_ollama_usage.run_cli(["ollama-usage", *sys.argv[1:]]))
