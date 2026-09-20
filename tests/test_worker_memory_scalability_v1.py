"""Offline fixtures only; no production state, providers, or broker calls."""
from datetime import UTC, datetime
from types import SimpleNamespace
import sys

import pytest

from engine.astra_runtime_governance_v1 import retained_size_lower_bound, worker_memory_owners
from scripts import astra_historical_context_phase2_v1 as phase2
from scripts import astra_historical_data_infrastructure_v1 as history


def test_inspection_is_bounded_even_with_repeated_references():
    value = [{}] * 100_000
    size, truncated = retained_size_lower_bound(value, max_nodes=8)
    assert size >= sys.getsizeof(value)
    assert truncated


def test_inspection_handles_cycles_without_retaining_payloads():
    value = {'identity': 'active-life'}
    value['self'] = value
    size, truncated = retained_size_lower_bound(value)
    assert size > 0 and not truncated
    worker = SimpleNamespace(autopilot=SimpleNamespace(_runtime_state={'lifecycles': value}))
    rows = worker_memory_owners(worker)
    assert rows[0]['truth_critical']
    assert rows[0]['item_count'] == 2
    assert 'identity' not in rows[0]
    assert value['self'] is value


@pytest.mark.parametrize('state', ['RESOURCE_MEMORY_PAUSE', 'RESOURCE_UNKNOWN_FAIL_CLOSED', 'RESOURCE_RECOVERY_COOLDOWN', 'RESOURCE_API_LATENCY_PAUSE', 'RESOURCE_HIGH_PAUSE', 'RESOURCE_ELEVATED', 'COMPACTION_REQUIRED', 'UNKNOWN', '', 'FUTURE_UNKNOWN_STATE'])
def test_acquisition_requires_positive_healthy_authorization(state, tmp_path, monkeypatch):
    health = {'worker_count': 1, 'last_error': '', 'updated_at': datetime.now(UTC).isoformat(), 'resource_state': state}
    monkeypatch.setattr(history, 'worker_health', lambda *_: health)
    monkeypatch.setattr(phase2, 'worker_health', lambda *_: health)
    assert not history.resource_ready(tmp_path, tmp_path, 0)
    assert not phase2.worker_safe(tmp_path)


def test_diagnostic_compaction_preserves_canonical_inputs(tmp_path):
    from engine.intelligence_quality_common_v1 import CachedDiagnosticModule
    canonical = {'truths': [{'truth_id': 't1'}], 'acks': [{'truth_id': 't1', 'acknowledged': True}],
                 'reconciliation': {'owner': 'broker'}, 'active': {'lifecycle_id': 'open'},
                 'unresolved': {'lifecycle_id': 'ambiguous', 'raw_evidence': ['retain']}}
    diagnostic = CachedDiagnosticModule(str(tmp_path))
    diagnostic._store({'references': canonical})
    before = repr(canonical)
    released = CachedDiagnosticModule.compact_worker_caches()
    assert released['items_released'] >= 1
    assert diagnostic._cache is None
    assert repr(canonical) == before
    assert (tmp_path / 'dashboard_cache' / 'diagnostic_module.json').exists()


def test_large_diagnostic_is_persisted_but_not_admitted_to_hot_cache(tmp_path):
    from engine.intelligence_quality_common_v1 import CachedDiagnosticModule
    diagnostic = CachedDiagnosticModule(str(tmp_path))
    for count in (20_000, 80_000):
        payload = {'rows': [{'id': i, 'evidence': 'synthetic'} for i in range(count)]}
        returned = diagnostic._store(payload)
        assert len(returned['rows']) == count
        assert diagnostic._cache is None
    assert (tmp_path / 'dashboard_cache' / 'diagnostic_module.json').exists()


def test_pressure_blocks_diagnostic_archive_reads_and_builds(tmp_path, monkeypatch):
    from engine import intelligence_quality_common_v1 as common
    diagnostic = common.CachedDiagnosticModule(str(tmp_path))
    monkeypatch.setattr(common.CachedDiagnosticModule, '_memory_backpressure', True)
    monkeypatch.setattr(common, 'read_json', lambda *_: pytest.fail('archive preload'))
    monkeypatch.setattr(diagnostic, '_build', lambda *_: pytest.fail('diagnostic build'))
    assert diagnostic.status(force=True)['degraded_reason'] == 'RESOURCE_MEMORY_BACKPRESSURE'


@pytest.mark.parametrize('fraction,state,resource', [(.59, 'NORMAL', 'RESOURCE_NORMAL'), (.60, 'ELEVATED', 'RESOURCE_ELEVATED'), (.75, 'COMPACTION_REQUIRED', 'RESOURCE_ELEVATED'), (.85, 'MEMORY_PAUSE', 'RESOURCE_MEMORY_PAUSE'), (1, 'HARD_FAIL_CLOSED', 'RESOURCE_MEMORY_PAUSE')])
def test_memory_thresholds_scale_with_configured_budget(fraction, state, resource):
    from engine.astra_runtime_governance_v1 import RuntimeLimits, classify_resource_signals
    limits = RuntimeLimits(maximum_worker_memory_mb=1000)
    sample = classify_resource_signals({'logical_cpu_count': 8, 'host_load_1m': 1, 'host_load_5m': 1, 'host_load_15m': 1,
                                       'cpu_idle_percent': 90, 'memory_pressure_state': 'normal', 'available_memory_mb': 20000,
                                       'backend_health_latency_ms': 1, 'worker_process': {'memory_mb': fraction * 1000}}, limits=limits, require_complete=True)
    assert sample['memory_state'] == state
    assert sample['resource_candidate_state'] == resource


def test_compaction_precedes_pause_and_recovery_requires_healthy_samples(monkeypatch):
    from engine import paper_autopilot_worker as module
    from engine.astra_runtime_governance_v1 import RuntimeLimits, classify_resource_signals
    from engine.intelligence_quality_common_v1 import CachedDiagnosticModule
    monkeypatch.setattr(module, 'read_snapshot', lambda: {})
    autopilot = SimpleNamespace(_runtime_state={}, get_crypto_candidate_rows_fn=lambda: [])
    worker = module.PaperAutopilotWorker(autopilot)
    worker.limits = RuntimeLimits(maximum_worker_memory_mb=1000)
    facts = {'logical_cpu_count': 8, 'host_load_1m': 1, 'host_load_5m': 1, 'host_load_15m': 1, 'cpu_idle_percent': 90,
             'memory_pressure_state': 'normal', 'available_memory_mb': 20000, 'backend_health_latency_ms': 1,
             'worker_process': {'memory_mb': 900}}
    monkeypatch.setattr(module, 'resource_snapshot', lambda **_: classify_resource_signals(facts, limits=worker.limits))
    monkeypatch.setattr(worker, '_backend_health_latency_ms', lambda: 1)
    monkeypatch.setattr(module, 'process_info', lambda *_: {'running': True, 'memory_mb': 500})
    monkeypatch.setattr(CachedDiagnosticModule, '_memory_backpressure', False)
    sample, policy = worker._sample_resource()
    assert sample['worker_process']['memory_mb'] == 500
    assert policy['resource_state'] == 'RESOURCE_NORMAL'
    assert worker._memory_compactions_attempted == 1
    assert worker._memory_background_suspended
    facts['worker_process']['memory_mb'] = 500
    for _ in range(2):
        worker._sample_resource()
        assert worker._memory_background_suspended
    worker._sample_resource()
    assert not worker._memory_background_suspended
    assert not CachedDiagnosticModule._memory_backpressure
    assert autopilot._runtime_state == {}
    assert worker._memory_last_compaction_result['protected_owner_counts_unchanged']
    # A deliberately faulty synthetic compactor must never authorize resume.
    worker._memory_last_compaction = 0
    facts['worker_process']['memory_mb'] = 900
    monkeypatch.setattr(module, 'release_unused_native_memory', lambda: autopilot._runtime_state.update({'native_lane_exit_lifecycle_v1': {'unexpected': {}}}) or 0)
    sample, policy = worker._sample_resource()
    assert policy['resource_state'] == 'RESOURCE_UNKNOWN_FAIL_CLOSED'
    assert not worker._memory_last_compaction_result['protected_owner_counts_unchanged']


def test_historical_manifest_size_does_not_preload_archive(tmp_path, monkeypatch):
    from engine.astra_knowledge_warehouse_v1 import AstraKnowledgeWarehouseV1
    warehouse = AstraKnowledgeWarehouseV1(str(tmp_path))
    row = {'path': 'candidate_decision_ledger_v1.jsonl', 'store': 'candidate_decision_ledger',
           'exists': True, 'index_available': True, 'index': 'summary.json', 'size_bytes': 100 * 1024 ** 3}
    monkeypatch.setattr(warehouse, '_catalog', lambda: [row])
    monkeypatch.setattr('builtins.open', lambda *a, **k: pytest.fail('manifest lookup opened archive'))
    refs = warehouse.source_references(max_sources=1)
    assert len(refs) == 1
    assert refs[0]['size_bytes'] == 100 * 1024 ** 3
    assert 'payload' not in refs[0]


def test_background_learning_yields_to_pressure_and_active_trading():
    from engine.astra_historical_learning_compression_helpers_v1 import adaptive_throughput_v1
    for facts in ({'resource_state': 'RESOURCE_ELEVATED'}, {'resource_state': 'RESOURCE_MEMORY_PAUSE'},
                  {'resource_state': 'RESOURCE_NORMAL', 'background_work_suspended': True},
                  {'resource_state': 'RESOURCE_NORMAL', 'trading_priority_active': True}):
        result = adaptive_throughput_v1({'healthy_successful_cycles': 100}, facts)
        assert result['mode'] == 'PAUSED'
        assert result['budget']['bytes'] == 0
        assert not result['execution_behavior_changed']



def test_cache_admission_counts_large_dictionary_keys(tmp_path):
    from engine.intelligence_quality_common_v1 import CachedDiagnosticModule
    from engine.astra_runtime_governance_v1 import RuntimeLimits
    diagnostic = CachedDiagnosticModule(str(tmp_path))
    budget = RuntimeLimits.from_env().maximum_worker_memory_mb * 1024 * 1024 // 128
    diagnostic._admit_memory_cache({'x' * (budget + 1): None})
    assert diagnostic._cache is None


def test_native_relief_delegates_only_free_page_selection(monkeypatch):
    from engine import astra_runtime_governance_v1 as resource
    calls = []
    monkeypatch.setattr(resource, '_native_allocator_api', lambda: (None, None, lambda zone, goal: calls.append((zone, goal)) or 4096))
    assert resource.release_unused_native_memory() == 4096
    assert calls == [(None, 0)]
    monkeypatch.setattr(resource, '_native_allocator_api', lambda: None)
    assert resource.release_unused_native_memory() == 0
    assert resource.native_allocator_snapshot() == {'supported': False}


@pytest.mark.parametrize('resource', ['RESOURCE_ELEVATED', 'RESOURCE_MEMORY_PAUSE', 'RESOURCE_RECOVERY_COOLDOWN', 'FUTURE_UNKNOWN_STATE'])
def test_canonical_historical_owner_does_not_convert_pause_to_one_row(resource, tmp_path, monkeypatch):
    from engine import astra_incremental_historical_learning_governor_v1 as governor
    monkeypatch.setattr(governor, '_warehouse_sources', lambda *_: pytest.fail('paused owner located history'))
    checkpoint = tmp_path / governor.CHECKPOINT_FILE
    checkpoint.write_text(__import__('json').dumps({'throughput': {'healthy_successful_cycles': 100}}))
    result = governor.run_incremental_historical_learning_cycle_v1(str(tmp_path), resource_facts={'worker_health': 'HEALTHY', 'resource_state': resource})
    assert result['status'] == 'DEFERRED_RESOURCE_PRESSURE'
    assert result['partitions_processed'] == []
    assert __import__('json').loads(checkpoint.read_text())['throughput']['healthy_successful_cycles'] == 0
