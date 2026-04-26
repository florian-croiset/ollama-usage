import argparse
import itertools
import json
import logging
import sys
import time
from typing import Optional
from importlib.metadata import version as get_version

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
from ollama_usage.scraper import get_usage

logger = logging.getLogger(__name__)

try:
    from colorama import Fore, Style, just_fix_windows_console
    _HAS_COLOR = True
except ImportError:
    _HAS_COLOR = False

def _sanitize_cookie(value: str) -> str:
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
    text = f"{pct}%"
    if not _HAS_COLOR:
        return text
    if pct < 50:
        color = Fore.GREEN
    elif pct < 80:
        color = Fore.YELLOW
    else:
        color = Fore.RED
    return color + text + Style.RESET_ALL


def display(data: dict, as_json: bool, quiet: bool) -> None:
    if quiet:
        return
    if as_json:
        print(json.dumps(data, indent=2))
    else:
        print(f"Plan    : {data['plan']}")
        print(f"Session : {_color_pct(data['session']['used_pct'])} used — reset at {data['session']['resets_at']}")
        print(f"Weekly  : {_color_pct(data['weekly']['used_pct'])} used — reset at {data['weekly']['resets_at']}")


def _check_alert(data: dict, threshold: Optional[float], quiet: bool) -> bool:
    """Return True if any quota exceeds the alert threshold."""
    if threshold is None:
        return False
    session_pct = data["session"]["used_pct"]
    weekly_pct = data["weekly"]["used_pct"]
    if session_pct > threshold or weekly_pct > threshold:
        if not quiet:
            msg = f"Warning: usage exceeds {threshold}%"
            if _HAS_COLOR:
                print(Fore.RED + "⚠️  " + msg + Style.RESET_ALL, file=sys.stderr)
            else:
                print(f"⚠️  {msg}", file=sys.stderr)
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
    parser.add_argument("--cookie", type=str, help="Manual __Secure-session cookie")
    parser.add_argument(
        "--browser", type=str, choices=BROWSERS.keys(), help="Force a specific browser"
    )
    parser.add_argument("--watch", action="store_true", help="Refresh continuously")
    parser.add_argument(
        "--interval", type=int, default=30,
        help="Refresh interval in seconds (default: 30, min: 10, max: 3600, requires --watch)"
    )
    parser.add_argument(
        "--alert", type=float, metavar="PCT",
        help="Exit with code 1 if session or weekly usage exceeds PCT%%"
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

    if _HAS_COLOR:
        just_fix_windows_console()

    if args.interval != 30 and not args.watch:
        print("Warning: --interval has no effect without --watch.", file=sys.stderr)

    try:
        if args.debug:
            logging.basicConfig(
                level=logging.DEBUG,
                format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
            )

        interval = max(10, min(3600, args.interval))

        if args.cookie:
            cookie = _sanitize_cookie(args.cookie)
        elif args.browser:
            cookie = _sanitize_cookie(BROWSERS[args.browser]())
        else:
            env_cookie = get_cookie_env()
            if env_cookie:
                cookie = _sanitize_cookie(env_cookie)
            else:
                cookie = _sanitize_cookie(get_cookie_auto())

        logger.debug("Cookie obtained (***)")

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
                    # Effacement terminal sans passer par un shell (évite os.system)
                    sys.stdout.write("\033[2J\033[H")
                    sys.stdout.flush()
                    try:
                        data = get_usage(cookie)
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
            data = get_usage(cookie)
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