"""Tests for ollama_usage.notify."""

from __future__ import annotations

import pytest
from unittest.mock import patch

from ollama_usage.notify import NotifyState, check_and_notify


def make_data(session_pct: float = 0.0, weekly_pct: float = 0.0) -> dict:
    return {
        "plan": "free",
        "session": {"used_pct": session_pct, "resets_at": "2026-04-04T17:00:00Z"},
        "weekly":  {"used_pct": weekly_pct,  "resets_at": "2026-04-06T00:00:00Z"},
    }


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
        state.should_warn("session", 50.0, 80.0)
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


class TestNotifyStateRecovery:

    def test_recovery_resets_warn_flag(self) -> None:
        state = NotifyState()
        state.should_warn("weekly", 85.0, 80.0)
        state.should_warn("weekly", 50.0, 80.0)
        assert state._warned["weekly"] is False

    def test_recovery_resets_critical_flag(self) -> None:
        state = NotifyState()
        state.should_critical("weekly", 96.0, 95.0)
        state.should_warn("weekly", 50.0, 80.0)
        assert state._critical["weekly"] is False

    def test_no_reset_when_still_above_threshold(self) -> None:
        state = NotifyState()
        state.should_warn("session", 85.0, 80.0)
        state.should_warn("session", 82.0, 80.0)
        assert state._warned["session"] is True


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
        check_and_notify(make_data(session_pct=50.0), threshold=80.0, state=state)
        check_and_notify(make_data(session_pct=85.0), threshold=80.0, state=state)
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


class TestSendFallback:

    def test_no_crash_when_plyer_missing(self) -> None:
        with patch("ollama_usage.notify._HAS_PLYER", False):
            from ollama_usage.notify import _send
            _send(title="test", message="test")

    def test_no_crash_when_plyer_raises(self) -> None:
        with patch("ollama_usage.notify._HAS_PLYER", True):
            with patch("ollama_usage.notify._plyer_notification") as mock_notif:
                mock_notif.notify.side_effect = RuntimeError("OS error")
                from ollama_usage.notify import _send
                _send(title="test", message="test")


class TestMonthlyNotify:

    @staticmethod
    def _data(pct: float) -> dict:
        return {
            "plan": "pro",
            "session": None,
            "weekly": None,
            "monthly": {"used_pct": pct, "resets_at": "2026-10-01T00:00:00Z"},
        }

    @patch("ollama_usage.notify._send")
    def test_monthly_warning_sent(self, mock_send) -> None:
        check_and_notify(self._data(85.0), threshold=80.0, state=NotifyState())
        mock_send.assert_called_once()
        assert "monthly" in mock_send.call_args[1]["title"].lower()

    @patch("ollama_usage.notify._send")
    def test_monthly_below_threshold_silent(self, mock_send) -> None:
        check_and_notify(self._data(10.0), threshold=80.0, state=NotifyState())
        mock_send.assert_not_called()

    @patch("ollama_usage.notify._send")
    def test_no_reset_date_from_api(self, mock_send) -> None:
        data = self._data(85.0)
        data["monthly"]["resets_at"] = None
        check_and_notify(data, threshold=80.0, state=NotifyState())
        assert "None" not in mock_send.call_args[1]["message"]
        assert "resets" not in mock_send.call_args[1]["message"]


class TestNotifyStateKeys:

    def test_tracks_every_period(self) -> None:
        from ollama_usage.scraper import PERIOD_KEYS
        state = NotifyState()
        assert set(state._warned) == set(PERIOD_KEYS)
        assert set(state._critical) == set(PERIOD_KEYS)

    def test_starts_unflagged(self) -> None:
        state = NotifyState()
        assert not any(state._warned.values())
        assert not any(state._critical.values())

    def test_states_are_independent_instances(self) -> None:
        a, b = NotifyState(), NotifyState()
        a.should_warn("monthly", 90.0, 80.0)
        assert b.should_warn("monthly", 90.0, 80.0) is True


class TestCheckAndNotifyEdgeCases:

    @staticmethod
    def _monthly(pct: float, resets_at: str | None = "2026-10-01T00:00:00Z") -> dict:
        return {"plan": "free", "session": None, "weekly": None,
                "monthly": {"used_pct": pct, "resets_at": resets_at}}

    @patch("ollama_usage.notify._send")
    def test_warning_and_critical_same_tick(self, mock_send) -> None:
        check_and_notify(self._monthly(99.0), threshold=80.0, state=NotifyState())
        titles = [c.kwargs["title"] for c in mock_send.call_args_list]
        assert len(titles) == 2
        assert "warning" in titles[0] and "critical" in titles[1]

    @patch("ollama_usage.notify._send")
    def test_critical_threshold_capped_at_100(self, mock_send) -> None:
        state = NotifyState()
        check_and_notify(self._monthly(99.0), threshold=95.0, state=state)
        assert mock_send.call_count == 1  # critical would be 110 → capped at 100
        check_and_notify(self._monthly(100.0), threshold=95.0, state=state)
        assert mock_send.call_count == 2

    @patch("ollama_usage.notify._send")
    def test_critical_not_repeated(self, mock_send) -> None:
        state = NotifyState()
        for _ in range(3):
            check_and_notify(self._monthly(99.0), threshold=80.0, state=state)
        assert mock_send.call_count == 2

    @patch("ollama_usage.notify._send")
    def test_none_periods_skipped(self, mock_send) -> None:
        check_and_notify(self._monthly(10.0), threshold=80.0, state=NotifyState())
        mock_send.assert_not_called()

    @patch("ollama_usage.notify._send")
    def test_empty_data(self, mock_send) -> None:
        check_and_notify({}, threshold=80.0, state=NotifyState())
        mock_send.assert_not_called()

    @patch("ollama_usage.notify._send")
    def test_message_format(self, mock_send) -> None:
        check_and_notify(self._monthly(85.25), threshold=80.0, state=NotifyState())
        kwargs = mock_send.call_args.kwargs
        assert kwargs["title"] == "⚠️ Ollama Monthly quota warning"
        assert kwargs["message"] == "Monthly usage at 85.2% (threshold: 80%) — resets at 2026-10-01T00:00:00Z"

    @patch("ollama_usage.notify._send")
    def test_threshold_zero(self, mock_send) -> None:
        check_and_notify(self._monthly(0.0), threshold=0.0, state=NotifyState())
        assert mock_send.call_count == 1


class TestSendAndAvailability:

    def test_send_calls_plyer(self) -> None:
        from ollama_usage.notify import _send
        with patch("ollama_usage.notify._HAS_PLYER", True), \
             patch("ollama_usage.notify._plyer_notification") as plyer:
            _send(title="T", message="M")
        plyer.notify.assert_called_once_with(title="T", message="M", app_name="ollama-usage", timeout=8)

    def test_send_without_plyer_logs_warning(self, caplog) -> None:
        from ollama_usage.notify import _send
        with patch("ollama_usage.notify._HAS_PLYER", False), caplog.at_level("WARNING"):
            _send(title="T", message="M")
        assert "plyer is not installed" in caplog.text

    def test_send_failure_logs_warning(self, caplog) -> None:
        from ollama_usage.notify import _send
        with patch("ollama_usage.notify._HAS_PLYER", True), \
             patch("ollama_usage.notify._plyer_notification") as plyer, \
             caplog.at_level("WARNING"):
            plyer.notify.side_effect = RuntimeError("dbus down")
            _send(title="T", message="M")
        assert "dbus down" in caplog.text

    @pytest.mark.parametrize("available", [True, False])
    def test_notify_available(self, available: bool) -> None:
        from ollama_usage.notify import notify_available
        with patch("ollama_usage.notify._HAS_PLYER", available):
            assert notify_available() is available

    @pytest.mark.parametrize("key,label", [("session", "Session"), ("weekly", "Weekly"), ("monthly", "Monthly")])
    def test_label(self, key: str, label: str) -> None:
        from ollama_usage.notify import _label
        assert _label(key) == label
