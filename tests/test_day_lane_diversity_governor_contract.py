import tempfile
import unittest

from engine.astra_pladeu_master_v1 import DayLaneDiversityGovernorV1
from engine.paper_opportunity_allocation_engine_v1 import PaperOpportunityAllocationEngineV1


class DayLaneDiversityGovernorContractTests(unittest.TestCase):
    def test_governor_reports_existing_allocator_output_without_displacing_candidates(self):
        rows = [
            {"symbol": "AAA", "paper_entry_horizon_style": "day_trade", "confidence": 85, "sector": "Technology", "paper_ready": True},
            {"symbol": "BBB", "paper_entry_horizon_style": "day_trade", "confidence": 72, "sector": "Technology"},
        ]
        allocator = PaperOpportunityAllocationEngineV1(state_dir="/tmp/astra-diversity-contract")
        decorated = allocator.decorate_candidates(rows)
        allocation = allocator.day_lane_governance(decorated, [])
        with tempfile.TemporaryDirectory() as state_dir:
            payload = DayLaneDiversityGovernorV1(state_dir=state_dir).status(
                statuses={"pladeu_candidate_rows": decorated, "pladeu_open_positions": [], "pladeu_day_lane_allocation": allocation},
                force=True,
            )
        self.assertEqual(payload["candidate_supply"], 2)
        self.assertTrue(payload["quality_over_mechanical_diversity"])
        self.assertTrue(payload["no_candidate_displacement"])
        self.assertFalse(payload["behavior_safe_to_apply"])
