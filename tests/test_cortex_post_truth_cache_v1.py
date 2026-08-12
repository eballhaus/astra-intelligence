from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine.intelligence_quality_common_v1 import CachedDiagnosticModule


class _CacheProbe(CachedDiagnosticModule):
    module_name = "cache_probe"

    def __init__(self, state_dir: str, ttl_seconds: float = 30.0) -> None:
        super().__init__(state_dir=state_dir, ttl_seconds=ttl_seconds)
        self.builds = 0

    def _build(self, statuses):
        self.builds += 1
        return {"status": "ok", "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "builds": self.builds}


class CortexPostTruthCacheTests(unittest.TestCase):
    def test_old_generated_cache_is_not_refreshed_by_read_time(self):
        with tempfile.TemporaryDirectory() as root:
            probe = _CacheProbe(root)
            path = Path(probe.cache_path)
            path.parent.mkdir(parents=True)
            stale = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
            path.write_text(json.dumps({"status": "ok", "generated_at": stale, "builds": 0}), encoding="utf-8")
            os.utime(path, None)  # A recent mtime cannot hide an old payload timestamp.
            result = probe.status()

        self.assertEqual(probe.builds, 1)
        self.assertEqual(result["builds"], 1)

    def test_current_disk_cache_still_uses_persisted_freshness(self):
        with tempfile.TemporaryDirectory() as root:
            probe = _CacheProbe(root)
            path = Path(probe.cache_path)
            path.parent.mkdir(parents=True)
            fresh = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            path.write_text(json.dumps({"status": "ok", "generated_at": fresh, "cached": True}), encoding="utf-8")
            result = probe.status()

        self.assertEqual(probe.builds, 0)
        self.assertTrue(result["cached"])

    def test_normal_cortex_endpoint_returns_before_attachment_builders(self):
        source = Path("server_extend.py").read_text(encoding="utf-8")
        start = source.index('def cortex_lifecycle_evidence_master_truth_v1')
        end = source.index('@router.get("/api/astra_integration_completion_consumption_v1")', start)
        endpoint = source[start:end]
        cached_return = endpoint.index("if cached_payload_healthy and not force:")
        return_index = endpoint.index("return cached_payload", cached_return)

        self.assertNotIn("_attach_astra_integration_completion", endpoint)
        self.assertNotIn("_attach_astra_paper_provider_cortex_completion", endpoint)
        self.assertIn("return payload", endpoint)
        self.assertIn("invoking\n    # them here made a diagnostic refresh wait on unrelated builders", endpoint)


if __name__ == "__main__":
    unittest.main()
