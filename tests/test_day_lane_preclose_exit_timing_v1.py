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
    def _row(
        *,
        lane: str = "DAY",
        same_session_exit_required: bool | None = None,
        expected_hold_minutes: float | None = None,
        expected_hold_window: str | None = None,
    ) -> dict[str, object]:
        row: dict[str, object] = {
            "position_id": f"life-{lane.lower()}",
            "symbol": lane,
            "lane_id": lane,
            "entry_timestamp": "2026-08-14T14:00:00Z",
            "same_session_exit_required": lane == "DAY" if same_session_exit_required is None else same_session_exit_required,
            "overnight_allowed": False,
        }
        if expected_hold_minutes is not None:
            row["expected_hold_minutes"] = expected_hold_minutes
        if expected_hold_window is not None:
            row["expected_hold_window"] = expected_hold_window
        return row

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

    def test_scalp_uses_its_explicit_same_session_contract_at_the_existing_deadline(self) -> None:
        engine, _ = self._engine()
        with self._at(datetime(2026, 8, 14, 15, 55, tzinfo=ET)):
            self.assertEqual(
                engine._lane_forced_exit_reason(
                    self._row(lane="SCALP", same_session_exit_required=True)
                ),
                "scalp_lane_session_close_required",
            )

    def test_scalp_max_hold_is_not_due_before_contract_deadline(self) -> None:
        engine, _ = self._engine()
        row = self._row(lane="SCALP", same_session_exit_required=True, expected_hold_minutes=60.0)
        with self._at(datetime(2026, 8, 14, 10, 59, tzinfo=ET)):
            self.assertEqual(engine._lane_forced_exit_reason(row), "")

    def test_scalp_max_hold_reaches_existing_forced_exit_owner(self) -> None:
        engine, _ = self._engine(session_allowed=True)
        row = self._row(lane="SCALP", same_session_exit_required=True, expected_hold_minutes=60.0)
        quote = {
            "symbol": "SCALP",
            "price": 10.0,
            "provider_quote_timestamp": "2026-08-14T15:01:00Z",
            "source": "ALPACA_WS_SIP_CANARY",
        }
        engine._fetch_open_positions = lambda: [row]
        engine._canonical_active_position_observations_v1 = Mock(return_value={"SCALP": quote})
        submit = Mock(return_value={"ok": True, "submitted": True})
        engine._submit_authorized_lane_exit = submit

        with self._at(datetime(2026, 8, 14, 11, 1, tzinfo=ET)):
            result = engine._run_due_day_lane_close_stage({"SCALP": {"qty_available": 1}})

        self.assertEqual(result["submitted"], 1)
        submit.assert_called_once_with(
            row,
            {"qty_available": 1},
            "scalp_lane_max_hold_expired",
            latest_quote=quote,
        )

    def test_scalp_max_hold_reaches_evaluate_exit_without_weakening_quote_gate(self) -> None:
        engine, _ = self._engine()
        engine.exit_engine = None
        engine.exit_learning = None
        row = self._row(lane="SCALP", same_session_exit_required=True, expected_hold_minutes=60.0)
        row.update({"entry_price": 10.0, "lifecycle_notes": "{}"})
        quote = {
            "symbol": "SCALP",
            "price": 10.0,
            "provider_quote_timestamp": "2026-08-14T15:01:00Z",
        }

        with patch(
            "engine.paper_autopilot.canonical_market_timestamp_v1",
            return_value={"executable_freshness": True},
        ):
            with self._at(datetime(2026, 8, 14, 10, 59, tzinfo=ET)):
                self.assertEqual(engine._evaluate_exit(row, quote), (False, "hold"))
            with self._at(datetime(2026, 8, 14, 11, 1, tzinfo=ET)):
                self.assertEqual(engine._evaluate_exit(row, quote), (True, "scalp_lane_max_hold_expired"))

    def test_scalp_max_hold_uses_specific_window_when_numeric_minutes_are_missing(self) -> None:
        engine, _ = self._engine()
        row = self._row(
            lane="SCALP",
            same_session_exit_required=True,
            expected_hold_window="30m-45m",
        )
        with self._at(datetime(2026, 8, 14, 10, 44, tzinfo=ET)):
            self.assertEqual(engine._lane_forced_exit_reason(row), "")
        with self._at(datetime(2026, 8, 14, 10, 46, tzinfo=ET)):
            self.assertEqual(engine._lane_forced_exit_reason(row), "scalp_lane_max_hold_expired")

    def test_due_scalp_exit_receives_current_canonical_quote_before_submission(self) -> None:
        engine, _ = self._engine(session_allowed=True)
        row = self._row(lane="SCALP", same_session_exit_required=True)
        quote = {
            "symbol": "SCALP",
            "price": 10.0,
            "provider_quote_timestamp": "2026-08-14T19:55:00Z",
            "source": "ALPACA_WS_SIP_CANARY",
        }
        engine._fetch_open_positions = lambda: [row]
        engine._canonical_active_position_observations_v1 = Mock(return_value={"SCALP": quote})
        submit = Mock(return_value={"ok": True, "submitted": True})
        engine._submit_authorized_lane_exit = submit

        with self._at(datetime(2026, 8, 14, 15, 55, tzinfo=ET)):
            result = engine._run_due_day_lane_close_stage({"SCALP": {"qty_available": 1}})

        self.assertEqual(result["submitted"], 1)
        engine._canonical_active_position_observations_v1.assert_called_once_with({"SCALP": row})
        submit.assert_called_once_with(
            row,
            {"qty_available": 1},
            "scalp_lane_session_close_required",
            latest_quote=quote,
        )

    def test_due_scalp_exit_after_hours_never_requests_quote_or_submits(self) -> None:
        engine, session = self._engine(session_allowed=False)
        row = self._row(lane="SCALP", same_session_exit_required=True)
        engine._fetch_open_positions = lambda: [row]
        engine._canonical_active_position_observations_v1 = Mock(side_effect=self.fail)
        submit = Mock(side_effect=self.fail)
        engine._submit_authorized_lane_exit = submit

        with self._at(datetime(2026, 8, 14, 16, 1, tzinfo=ET)):
            result = engine._run_due_day_lane_close_stage({"SCALP": {"qty_available": 1}})

        self.assertEqual(session.calls, 1)
        self.assertEqual(result["blocked"], 1)
        engine._canonical_active_position_observations_v1.assert_not_called()
        submit.assert_not_called()
        state = engine._runtime_state["native_lane_exit_lifecycle_v1"]["life-scalp"]
        self.assertIn("REGULAR_SESSION_REQUIRED", state["exact_blocker"])

    def test_non_contract_lanes_do_not_receive_same_session_preclose_reason(self) -> None:
        engine, _ = self._engine()
        with self._at(datetime(2026, 8, 14, 15, 55, tzinfo=ET)):
            for lane in ("SWING", "CRYPTO"):
                self.assertEqual(engine._lane_forced_exit_reason(self._row(lane=lane)), "")
            self.assertEqual(
                engine._lane_forced_exit_reason(
                    self._row(lane="SCALP", same_session_exit_required=False)
                ),
                "",
            )


if __name__ == "__main__":
    unittest.main()
