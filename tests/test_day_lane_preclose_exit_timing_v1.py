from __future__ import annotations

from datetime import datetime, timezone
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from engine.paper_autopilot import PaperAutopilotEngine


ET = ZoneInfo("America/New_York")


class _FixedDatetime(datetime):
    current: datetime

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        return cls.current.astimezone(tz) if tz is not None else cls.current.replace(tzinfo=None)


class _SessionTiming:
    def __init__(self, *, allowed: bool) -> None:
        self.allowed = allowed
        self.calls = 0

    def session_status(self):
        self.calls += 1
        return {
            "market_session_mode": "regular_market" if self.allowed else "after_hours",
            "paper_order_submission_allowed": self.allowed,
        }


class DayLanePrecloseExitTimingTests(unittest.TestCase):
    def _engine(self, *, session_allowed: bool = True) -> tuple[PaperAutopilotEngine, _SessionTiming]:
        engine = object.__new__(PaperAutopilotEngine)
        engine._runtime_state = {}
        session = _SessionTiming(allowed=session_allowed)
        engine.market_session_timing_suite = session
        return engine, session

    @staticmethod
    def _row(*, lane: str = "DAY") -> dict[str, object]:
        return {
            "position_id": f"life-{lane.lower()}",
            "symbol": lane,
            "lane_id": lane,
            "entry_timestamp": "2026-08-14T14:00:00Z",
            "same_session_exit_required": lane == "DAY",
            "overnight_allowed": False,
        }

    def _at(self, value: datetime):
        _FixedDatetime.current = value
        return patch("engine.paper_autopilot.datetime", _FixedDatetime)

    def test_day_before_existing_preclose_cutoff_has_no_forced_reason(self) -> None:
        engine, _ = self._engine()
        with self._at(datetime(2026, 8, 14, 15, 54, tzinfo=ET)):
            self.assertEqual(engine._lane_forced_exit_reason(self._row()), "")

    def test_day_at_existing_preclose_cutoff_uses_canonical_session_and_authorized_writer(self) -> None:
        engine, session = self._engine(session_allowed=True)
        row = self._row()
        submit = Mock(return_value={"ok": True, "submitted": True})
        engine._fetch_open_positions = lambda: [row]
        engine._submit_authorized_lane_exit = submit

        with self._at(datetime(2026, 8, 14, 15, 55, tzinfo=ET)):
            result = engine._run_due_day_lane_close_stage({"DAY": {"qty_available": 1}})

        self.assertEqual(session.calls, 1)
        self.assertEqual(result["reviewed"], 1)
        self.assertEqual(result["submitted"], 1)
        submit.assert_called_once_with(row, {"qty_available": 1}, "day_lane_session_close_required")

    def test_day_after_hours_records_block_without_submission(self) -> None:
        engine, session = self._engine(session_allowed=False)
        row = self._row()
        submit = Mock(side_effect=self.fail)
        engine._fetch_open_positions = lambda: [row]
        engine._submit_authorized_lane_exit = submit

        with self._at(datetime(2026, 8, 14, 16, 1, tzinfo=ET)):
            result = engine._run_due_day_lane_close_stage({"DAY": {"qty_available": 1}})

        self.assertEqual(session.calls, 1)
        self.assertEqual(result["blocked"], 1)
        submit.assert_not_called()
        state = engine._runtime_state["native_lane_exit_lifecycle_v1"]["life-day"]
        self.assertEqual(state["closure_state"], "EXIT_BLOCKED_EXECUTION")
        self.assertIn("REGULAR_SESSION_REQUIRED", state["exact_blocker"])

    def test_non_day_lanes_do_not_receive_day_preclose_reason(self) -> None:
        engine, _ = self._engine()
        with self._at(datetime(2026, 8, 14, 15, 55, tzinfo=ET)):
            for lane in ("SWING", "SCALP", "CRYPTO"):
                self.assertEqual(engine._lane_forced_exit_reason(self._row(lane=lane)), "")


if __name__ == "__main__":
    unittest.main()
