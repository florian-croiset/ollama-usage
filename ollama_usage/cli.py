import argparse
import itertools
import json
import logging
import sys
import time
from typing import Optional
from importlib.metadata import version as get_version

from ollama_usage.ansi import GREEN, RED, YELLOW, colorize, enable_windows_ansi
from ollama_usage.api import get_api_key_env, get_usage_api
from ollama_usage.cookie import (
    get_cookie_auto,
    get_cookie_env,
    get_cookie_firefox,
    get_cookie_chrome,
    get_cookie_edge,
    get_cookie_brave,
    get_cookie_opera,
)
from ollama_usage.exceptions import OllamaUsageError, NetworkError
from ollama_usage.notify import check_and_notify, notify_available, NotifyState
from ollama_usage.scraper import get_usage, iter_periods

logger = logging.getLogger(__name__)


def _sanitize_cookie(value: str) -> str:
    if value is None:
        raise OllamaUsageError(
            "No Ollama session cookie found.\n"
            "Make sure you are logged in to ollama.com in your browser,\n"
            "or pass the cookie manually with --cookie."
        )
    return value.strip().replace("\r", "").replace("\n", "").replace("\0", "")


BROWSERS = {
    "firefox": get_cookie_firefox,
    "chrome": get_cookie_chrome,
    "edge": get_cookie_edge,
    "brave": get_cookie_brave,
    "opera": get_cookie_opera,
}


def _color_pct(pct: float) -> str:
    """Return the percentage string colored by severity."""
    if pct < 50:
        color = GREEN
    elif pct < 80:
        color = YELLOW
    else:
        color = RED
    return colorize(f"{pct}%", color)


def _fmt_model_line(model: str, requests: int, share_pct: Optional[float]) -> str:
    """Format one model breakdown line, padded for alignment."""
    max_name = 22
    name = model if len(model) <= max_name else model[: max_name - 1] + "…"
    line = f"    {name:<{max_name}}  {requests:>4} req"
    if share_pct is None:
        return line
    return f"{line}  ({share_pct:5.1f}%)"


def display(data: dict, as_json: bool, quiet: bool) -> None:
    if quiet:
        return
    if as_json:
        print(json.dumps(data, indent=2))
        return

    if data.get("plan"):
        print(f"Plan    : {data['plan']}")

    for key, period in iter_periods(data):
        line = f"{key.capitalize():<7} : {_color_pct(period['used_pct'])} used"
        if period.get("resets_at"):
            line += f" — reset at {period['resets_at']}"
        print(line)
        for m in period.get("models", []):
            print(_fmt_model_line(m["model"], m["requests"], m.get("share_pct")))

    if data.get("credits_balance") is not None:
        print(f"Credits : ${data['credits_balance']:.2f}")
    spend = data.get("spend")
    if spend:
        period = (spend.get("period") or "").replace("_", " ")
        print(f"Spend   : ${spend['cost_usd']:.2f}" + (f" ({period})" if period else ""))


def _check_alert(data: dict, threshold: Optional[float], quiet: bool) -> bool:
    """Return True if any quota exceeds the alert threshold."""
    if threshold is None:
        return False
    if any(period["used_pct"] > threshold for _, period in iter_periods(data)):
        if not quiet:
            msg = f"⚠️  Warning: usage exceeds {threshold}%"
            print(colorize(msg, RED, sys.stderr), file=sys.stderr)
        return True
    return False


def _watch_countdown(interval: int) -> None:
    """Animated countdown before next refresh."""
    spinner = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
    for remaining in range(interval, 0, -1):
        for _ in range(10):
            sys.stdout.write(f"\r{next(spinner)} Refreshing in {remaining}s — Ctrl+C to quit  ")
            sys.stdout.flush()
            time.sleep(0.1)
    sys.stdout.write("\r" + " " * 50 + "\r")
    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(
        description="Display your Ollama Cloud quota usage"
    )
    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"ollama-usage {get_version('ollama-usage')}"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument(
        "--api-key", type=str,
        help="ollama.com API key — uses the official /api/usage endpoint "
             "(default: $OLLAMA_API_KEY)"
    )
    parser.add_argument("--cookie", type=str, help="Manual __Secure-session cookie")
    parser.add_argument(
        "--browser", type=str, choices=BROWSERS.keys(),
        help="Read the session cookie from a specific browser "
             "(only firefox is supported: Chromium-based browsers encrypt their cookies)"
    )
    parser.add_argument("--watch", action="store_true", help="Refresh continuously")
    parser.add_argument(
        "--interval", type=int, default=30,
        help="Refresh interval in seconds (default: 30, min: 10, max: 3600, requires --watch)"
    )
    parser.add_argument(
        "--alert", type=float, metavar="PCT",
        help="Exit with code 1 if any usage quota (session, weekly or monthly) exceeds PCT%%"
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress all output — only set exit code (useful with --alert)"
    )
    parser.add_argument(
        "--notify", action="store_true",
        help="Send desktop notifications when quota exceeds threshold (requires plyer)"
    )
    parser.add_argument(
        "--notify-threshold", type=float, default=80.0, metavar="PCT",
        help="Threshold for desktop notifications in %% (default: 80, requires --notify)"
    )
    parser.add_argument(
        "--widget",
        action="store_true",
        help="Launch desktop widget"
    )
    parser.add_argument(
        "--theme",
        default="dark",
        choices=["dark", "light", "minimal"]
    )
    parser.add_argument(
        "--size",
        default="full",
        choices=["compact", "full"]
    )
    parser.add_argument(
        "--opacity",
        type=float,
        default=0.92,
        metavar="0.0-1.0"
    )
    parser.add_argument(
        "--position",
        default="top-left",
        choices=["top-left", "top-right", "bottom-left", "bottom-right"]
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logs"
    )
    args = parser.parse_args()

    enable_windows_ansi()  # also needed for --watch screen clearing

    if args.interval != 30 and not args.watch:
        print("Warning: --interval has no effect without --watch.", file=sys.stderr)
    if args.alert is not None and not (0 <= args.alert <= 100):
        parser.error("--alert must be between 0 and 100")
    if not (0 <= args.notify_threshold <= 100):
        parser.error("--notify-threshold must be between 0 and 100")
    if not (0.0 <= args.opacity <= 1.0):
        parser.error("--opacity must be between 0.0 and 1.0")

    try:
        if args.debug:
            logging.basicConfig(
                level=logging.DEBUG,
                format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
            )

        interval = max(10, min(3600, args.interval))

        # Explicit options first, then OLLAMA_API_KEY, then cookie sources.
        api_key = None
        cookie = None
        if args.api_key:
            api_key = _sanitize_cookie(args.api_key)
        elif args.cookie:
            cookie = _sanitize_cookie(args.cookie)
        elif args.browser:
            raw = BROWSERS[args.browser]()
            if raw is None:
                print(
                    f"Error: No Ollama session cookie found in {args.browser}.\n"
                    "Make sure you are logged in to ollama.com in that browser,\n"
                    "or pass the cookie manually with --cookie.",
                    file=sys.stderr,
                )
                raise SystemExit(1)
            cookie = _sanitize_cookie(raw)
        elif get_api_key_env():
            api_key = _sanitize_cookie(get_api_key_env())
        else:
            env_cookie = get_cookie_env()
            if env_cookie:
                cookie = _sanitize_cookie(env_cookie)
            else:
                cookie = _sanitize_cookie(get_cookie_auto())

        if api_key:
            logger.debug("API key obtained (***) — using %s", "ollama.com/api/usage")
        else:
            logger.debug("Cookie obtained (***) — scraping ollama.com/settings")

        def fetch() -> dict:
            return get_usage_api(api_key) if api_key else get_usage(cookie or "")

        alert_triggered = False

        notify_state = NotifyState()

        if args.notify and not notify_available():
            print(
                "Warning: --notify requires plyer. Install it with: "
                "pip install ollama-usage[notify]",
                file=sys.stderr,
            )

        if args.widget:
            from ollama_usage.widget import launch_widget
            launch_widget(
                cookie=cookie,
                api_key=api_key,
                interval=interval,
                theme=args.theme,
                size=args.size,
                opacity=args.opacity,
                position=args.position,
            )
            return

        if args.watch:
            try:
                while True:
                    sys.stdout.write("\033[2J\033[H")
                    sys.stdout.flush()
                    try:
                        data = fetch()
                        display(data, args.json, args.quiet)
                        if args.notify:
                            check_and_notify(data, args.notify_threshold, notify_state)
                        if _check_alert(data, args.alert, args.quiet):
                            alert_triggered = True
                    except NetworkError as e:
                        print(f"Network error: {e} — retrying in {interval}s", file=sys.stderr)
                    _watch_countdown(interval)
            except KeyboardInterrupt:
                print("\nStopped.")
        else:
            data = fetch()
            display(data, args.json, args.quiet)
            if args.notify:
                check_and_notify(data, args.notify_threshold, notify_state)
            if _check_alert(data, args.alert, args.quiet):
                alert_triggered = True

        if alert_triggered:
            raise SystemExit(1)

    except OllamaUsageError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()