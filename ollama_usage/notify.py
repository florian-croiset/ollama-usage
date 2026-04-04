"""Desktop notifications for Ollama quota alerts."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_CRITICAL_OFFSET = 15  # trigger a second "critical" notif this many % above threshold

try:
    from plyer import notification as _plyer_notification
    _HAS_PLYER = True
except ImportError:
    _HAS_PLYER = False


class NotifyState:
    """
    Tracks which notification levels have already been fired.
    Prevents spamming the same notification on every --watch tick.
    Resets automatically when usage drops back below a threshold.
    """

    def __init__(self) -> None:
        self._warned: dict[str, bool] = {"session": False, "weekly": False}
        self._critical: dict[str, bool] = {"session": False, "weekly": False}

    def _reset_if_recovered(self, key: str, pct: float, threshold: float) -> None:
        """Clear flags when usage drops back under the threshold."""
        if pct < threshold:
            if self._warned[key]:
                logger.debug("Notify: %s recovered below %.0f%% — resetting state", key, threshold)
            self._warned[key] = False
            self._critical[key] = False

    def should_warn(self, key: str, pct: float, threshold: float) -> bool:
        self._reset_if_recovered(key, pct, threshold)
        if pct >= threshold and not self._warned[key]:
            self._warned[key] = True
            return True
        return False

    def should_critical(self, key: str, pct: float, critical_threshold: float) -> bool:
        if pct >= critical_threshold and not self._critical[key]:
            self._critical[key] = True
            return True
        return False


def _send(title: str, message: str) -> None:
    """Send a desktop notification via plyer."""
    if not _HAS_PLYER:
        logger.warning(
            "plyer is not installed — install it with: pip install ollama-usage[notify]"
        )
        return
    try:
        _plyer_notification.notify(
            title=title,
            message=message,
            app_name="ollama-usage",
            timeout=8,
        )
        logger.debug("Notification sent: %s — %s", title, message)
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to send notification: %s", e)


def _label(key: str) -> str:
    return key.capitalize()


def check_and_notify(data: dict, threshold: float, state: NotifyState) -> None:
    """
    Check quota levels and fire desktop notifications when thresholds are crossed.

    Args:
        data:      Usage dict returned by get_usage().
        threshold: Warning threshold in percent (e.g. 80.0).
        state:     NotifyState instance shared across watch-loop iterations.
    """
    critical_threshold = min(threshold + _CRITICAL_OFFSET, 100.0)

    for key in ("session", "weekly"):
        pct: float = data[key]["used_pct"]
        resets_at: str = data[key]["resets_at"]
        label = _label(key)

        # Critical check first (higher bar, only after warning already set)
        if state.should_critical(key, pct, critical_threshold):
            _send(
                title=f"🔴 Ollama {label} quota critical",
                message=(
                    f"{label} usage at {pct:.1f}% — resets at {resets_at}"
                ),
            )

        # Warning check
        elif state.should_warn(key, pct, threshold):
            _send(
                title=f"⚠️ Ollama {label} quota warning",
                message=(
                    f"{label} usage at {pct:.1f}% (threshold: {threshold:.0f}%)"
                    f" — resets at {resets_at}"
                ),
            )


def notify_available() -> bool:
    """Return True if plyer is installed and notifications can be sent."""
    return _HAS_PLYER