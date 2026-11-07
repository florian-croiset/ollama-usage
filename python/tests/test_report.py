import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from ollama_cloud_usage import Report

REPORTS = Path(__file__).resolve().parents[2] / "fixtures" / "reports"


def load(name: str) -> dict:
    return json.loads((REPORTS / f"{name}.json").read_text(encoding="utf-8"))


class CurrentPlanTest(unittest.TestCase):
    def setUp(self) -> None:
        self.data = load("current")
        self.report = Report.from_dict(self.data)

    def test_the_monthly_window_is_read(self) -> None:
        monthly = self.report.windows.monthly
        self.assertIsNotNone(monthly)
        self.assertEqual(monthly.used_pct, 12.5)
        self.assertEqual(monthly.resets_at, datetime(2026, 2, 1, tzinfo=timezone.utc))
        self.assertIsNone(self.report.windows.session)

    def test_credits_and_usage_are_read(self) -> None:
        self.assertEqual(self.report.plan, "free")
        self.assertEqual(self.report.credits.included.spent_usd, 0.625)
        usage = self.report.usage
        self.assertEqual(usage.range, "30d")
        self.assertEqual(usage.requests, 120)
        self.assertEqual(usage.from_, datetime(2025, 12, 11, tzinfo=timezone.utc))
        self.assertEqual([m.model for m in usage.models], ["model-a", "model-b"])
        self.assertEqual(usage.other.share_pct, 12.5)

    def test_to_dict_gives_back_the_schema_form(self) -> None:
        self.assertEqual(self.report.to_dict(), self.data)

    def test_to_dict_cannot_alter_the_report(self) -> None:
        self.report.to_dict()["plan"] = "changed"
        self.assertEqual(self.report.to_dict()["plan"], "free")

    def test_the_report_is_read_only(self) -> None:
        with self.assertRaises(AttributeError):
            self.report.plan = "pro"  # type: ignore[misc]

    def test_a_complete_report_is_not_partial(self) -> None:
        self.assertFalse(self.report.is_partial)

    def test_a_failed_endpoint_makes_it_partial(self) -> None:
        self.data["usage"] = None
        self.data["warnings"] = [{"code": "usage_unavailable", "message": "/api/usage: HTTP 503"}]
        report = Report.from_dict(self.data)
        self.assertTrue(report.is_partial)
        self.assertIsNone(report.usage)


class LegacyPlanTest(unittest.TestCase):
    def test_session_and_weekly_windows_are_listed_in_order(self) -> None:
        report = Report.from_dict(load("legacy"))
        self.assertEqual([name for name, _ in report.windows.items()], ["session", "weekly"])
        self.assertIsNone(report.credits.included)
        self.assertEqual(report.credits.purchased_balance_usd, 2.5)


class TimestampTest(unittest.TestCase):
    def test_any_fraction_length_is_accepted(self) -> None:
        data = load("current")
        data["fetched_at"] = "2026-01-10T12:00:00.5Z"
        fetched_at = Report.from_dict(data).fetched_at
        self.assertEqual(fetched_at, datetime(2026, 1, 10, 12, 0, 0, 500000, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
