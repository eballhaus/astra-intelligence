"""Tests ensuring learned-exit validation defaults fail closed."""
from __future__ import annotations

import os
import unittest

from engine.controlled_paper_learned_exit_validation_v1 import ControlledPaperLearnedExitValidationV1


class LearnedExitSafetyDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.validator = ControlledPaperLearnedExitValidationV1(state_dir="/tmp")
        # Clear environment variables to test defaults.
        for key in (
            "ASTRA_LEARNED_EXIT_VALIDATION_BUCKET_ENABLED",
            "ASTRA_LEARNED_EXIT_VALIDATION_KILL_SWITCH",
            "ASTRA_LEARNED_EXIT_VALIDATION_MAX_EXITS_PER_DAY",
        ):
            os.environ.pop(key, None)

    def tearDown(self):
        for key in (
            "ASTRA_LEARNED_EXIT_VALIDATION_BUCKET_ENABLED",
            "ASTRA_LEARNED_EXIT_VALIDATION_KILL_SWITCH",
            "ASTRA_LEARNED_EXIT_VALIDATION_MAX_EXITS_PER_DAY",
        ):
            os.environ.pop(key, None)

    def _config(self, paper_status=None, multi=None):
        return self.validator._config(paper_status or {}, multi or {})

    def test_default_bucket_is_disabled(self):
        config = self._config()
        self.assertFalse(config["bucket_configured"])
        self.assertTrue(config["kill_switch_enabled"])

    def test_default_max_exits_per_day_is_zero(self):
        config = self._config()
        self.assertEqual(config["max_learning_corrected_exits_per_day"], 0)

    def test_malformed_max_exits_defaults_to_zero(self):
        config = self._config(paper_status={"learned_exit_validation_max_exits_per_day": "not-a-number"})
        self.assertEqual(config["max_learning_corrected_exits_per_day"], 0)

    def test_malformed_kill_switch_defaults_to_enabled(self):
        config = self._config(paper_status={"learned_exit_validation_kill_switch": "not-a-boolean"})
        self.assertTrue(config["kill_switch_enabled"])

    def test_environment_cannot_enable_by_default(self):
        # Explicitly clear env in setUp; config should remain fail-closed.
        config = self._config()
        self.assertFalse(config["bucket_configured"])
        self.assertEqual(config["max_learning_corrected_exits_per_day"], 0)

    def test_zero_max_exits_keeps_bucket_empty(self):
        config = self._config(paper_status={"learned_exit_validation_bucket_configured": True, "learned_exit_validation_max_exits_per_day": 0})
        self.assertEqual(config["max_learning_corrected_exits_per_day"], 0)


if __name__ == "__main__":
    unittest.main()
