"""Tests for ollama_usage.notify."""

from __future__ import annotations

import pytest
from unittest.mock import patch, call

from ollama_usage.notify import NotifyState, check_and_notify


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_data(session_pct: float = 0.0, weekly_pct: float = 0.0) -> dict:
    """Build a minimal usage dict as returned by get_usage()."""
    return {
        "plan": "free",
        "session": {"used_pct": session_pct, "resets_at": "2026-04-04T17:00:00Z"},
        "weekly":  {"used_pct": weekly_pct,  "resets_at": "2026-04-06T00:00:00Z"},
    }


# ---------------------------------------------------------------------------
# NotifyState — warning level
# ---------------------------------------------------------------------------

class TestNotifyStateWarn:

    def test_fires_when_above_threshold(self) -> None:
        state = NotifyState()
        assert state.should_warn("session", 85.0, 80.0) is True

    def test_does_not_fire_when_below_threshold(self) -> None:
        state = NotifyState()
        assert state.should_warn("session", 50.0, 80.0) is False

    def test_does_not_fire_twice(self) -> None:
        state = NotifyState()
        state.should_warn("session", 85.0, 80.0)
        assert state.should_warn("session", 85.0, 80.0) is False

    def test_fires_again_after_recovery(self) -> None:
        state = NotifyState()
        state.should_warn("session", 85.0, 80.0)
        state.should_warn("session", 50.0, 80.0)  # recovery — resets flag
        assert state.should_warn("session", 85.0, 80.0) is True

    def test_session_and_weekly_are_independent(self) -> None:
        state = NotifyState()
        state.should_warn("session", 85.0, 80.0)
        assert state.should_warn("weekly", 85.0, 80.0) is True

    def test_exactly_at_threshold_fires(self) -> None:
        state = NotifyState()
        assert state.should_warn("session", 80.0, 80.0) is True

    def test_one_below_threshold_does_not_fire(self) -> None:
        state = NotifyState()
        assert state.should_warn("session", 79.9, 80.0) is False


# ---------------------------------------------------------------------------
# NotifyState — critical level
# ---------------------------------------------------------------------------

class TestNotifyStateCritical:

    def test_fires_when_above_critical_threshold(self) -> None:
        state = NotifyState()
        assert state.should_critical("session", 96.0, 95.0) is True

    def test_does_not_fire_when_below_critical_threshold(self) -> None:
        state = NotifyState()
        assert state.should_critical("session", 85.0, 95.0) is False

    def test_does_not_fire_twice(self) -> None:
        state = NotifyState()
        state.should_critical("session", 96.0, 95.0)
        assert state.should_critical("session", 96.0, 95.0) is False

    def test_session_and_weekly_are_independent(self) -> None:
        state = NotifyState()
        state.should_critical("session", 96.0, 95.0)
        assert state.should_critical("weekly", 96.0, 95.0) is True


# ---------------------------------------------------------------------------
# NotifyState — recovery
# ---------------------------------------------------------------------------

class TestNotifyStateRecovery:

    def test_recovery_resets_warn_flag(self) -> None:
        state = NotifyState()
        state.should_warn("weekly", 85.0, 80.0)
        state.should_warn("weekly", 50.0, 80.0)  # drops below → reset
        assert state._warned["weekly"] is False

    def test_recovery_resets_critical_flag(self) -> None:
        state = NotifyState()
        state.should_critical("weekly", 96.0, 95.0)
        state.should_warn("weekly", 50.0, 80.0)  # recovery resets both
        assert state._critical["weekly"] is False

    def test_no_reset_when_still_above_threshold(self) -> None:
        state = NotifyState()
        state.should_warn("session", 85.0, 80.0)
        state.should_warn("session", 82.0, 80.0)  # still above — no reset
        assert state._warned["session"] is True


# ---------------------------------------------------------------------------
# check_and_notify — notification dispatch
# ---------------------------------------------------------------------------

class TestCheckAndNotify:

    @patch("ollama_usage.notify._send")
    def test_warning_notification_sent(self, mock_send) -> None:
        state = NotifyState()
        check_and_notify(make_data(session_pct=85.0), threshold=80.0, state=state)
        mock_send.assert_called_once()
        title, message = mock_send.call_args[1]["title"], mock_send.call_args[1]["message"]
        assert "warning" in title.lower()
        assert "85" in message

    @patch("ollama_usage.notify._send")
    def test_critical_notification_sent(self, mock_send) -> None:
        state = NotifyState()
        # critical threshold = 80 + 15 = 95
        check_and_notify(make_data(session_pct=96.0), threshold=80.0, state=state)
        title = mock_send.call_args[1]["title"]
        assert "critical" in title.lower()

    @patch("ollama_usage.notify._send")
    def test_no_notification_below_threshold(self, mock_send) -> None:
        state = NotifyState()
        check_and_notify(make_data(session_pct=50.0), threshold=80.0, state=state)
        mock_send.assert_not_called()

    @patch("ollama_usage.notify._send")
    def test_no_spam_on_second_call(self, mock_send) -> None:
        state = NotifyState()
        check_and_notify(make_data(session_pct=85.0), threshold=80.0, state=state)
        check_and_notify(make_data(session_pct=85.0), threshold=80.0, state=state)
        assert mock_send.call_count == 1

    @patch("ollama_usage.notify._send")
    def test_both_session_and_weekly_notify(self, mock_send) -> None:
        state = NotifyState()
        check_and_notify(make_data(session_pct=85.0, weekly_pct=85.0), threshold=80.0, state=state)
        assert mock_send.call_count == 2

    @patch("ollama_usage.notify._send")
    def test_notifies_again_after_recovery(self, mock_send) -> None:
        state = NotifyState()
        check_and_notify(make_data(session_pct=85.0), threshold=80.0, state=state)
        check_and_notify(make_data(session_pct=50.0), threshold=80.0, state=state)  # recovery
        check_and_notify(make_data(session_pct=85.0), threshold=80.0, state=state)  # fires again
        assert mock_send.call_count == 2

    @patch("ollama_usage.notify._send")
    def test_weekly_label_in_notification(self, mock_send) -> None:
        state = NotifyState()
        check_and_notify(make_data(weekly_pct=85.0), threshold=80.0, state=state)
        title = mock_send.call_args[1]["title"]
        assert "weekly" in title.lower()

    @patch("ollama_usage.notify._send")
    def test_session_label_in_notification(self, mock_send) -> None:
        state = NotifyState()
        check_and_notify(make_data(session_pct=85.0), threshold=80.0, state=state)
        title = mock_send.call_args[1]["title"]
        assert "session" in title.lower()

    @patch("ollama_usage.notify._send")
    def test_resets_at_present_in_message(self, mock_send) -> None:
        state = NotifyState()
        check_and_notify(make_data(session_pct=85.0), threshold=80.0, state=state)
        message = mock_send.call_args[1]["message"]
        assert "2026-04-04T17:00:00Z" in message


# ---------------------------------------------------------------------------
# _send — plyer unavailable
# ---------------------------------------------------------------------------

class TestSendFallback:

    def test_no_crash_when_plyer_missing(self) -> None:
        """_send should log a warning but never raise if plyer is not installed."""
        with patch("ollama_usage.notify._HAS_PLYER", False):
            from ollama_usage.notify import _send
            _send(title="test", message="test")  # must not raise

    def test_no_crash_when_plyer_raises(self) -> None:
        """_send should swallow plyer exceptions and log them."""
        with patch("ollama_usage.notify._HAS_PLYER", True):
            with patch("ollama_usage.notify._plyer_notification.notify", side_effect=RuntimeError("OS error")):
                from ollama_usage.notify import _send
                _send(title="test", message="test")  # must not raise