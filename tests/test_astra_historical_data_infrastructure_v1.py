import json
from datetime import UTC, datetime

import pytest

from scripts import astra_historical_data_infrastructure_v1 as h
from engine.astra_pit_metadata_contract_v1 import historical_news_evidence_gate, normalize_historical_record, require_replay_safe, UnsafeReplayRecord

DAY = '2026-09-09'
RECEIPT = '2026-09-20T12:00:00Z'


def article(id=1, at='2026-09-09T12:00:00Z', **extra):
    return {'id': id, 'datetime': int(datetime.fromisoformat(at.replace('Z', '+00:00')).timestamp()), 'headline': 'test only', **extra}


@pytest.fixture
def archive(tmp_path):
    a = h.NewsArchive(tmp_path / 'archive')
    yield a
    a.close()


def retain(a, rows, day=DAY, status=200):
    return a.retain('NVDA', day, day, RECEIPT, RECEIPT, status, {'Retry-After': '60', 'Secret': 'excluded'}, json.dumps(rows).encode())


def test_daily_leap_and_end():
    assert list(h.daily_windows('2024-02-28', '2024-03-01')) == [(d, d) for d in ['2024-02-28', '2024-02-29', '2024-03-01']]
    with pytest.raises(ValueError):
        list(h.daily_windows('2024-03-01', '2024-02-01'))


def test_no_multiday_archive(archive):
    with pytest.raises(ValueError):
        archive.retain('NVDA', DAY, '2026-09-10', RECEIPT, RECEIPT, 200, {}, b'[]')
    with pytest.raises(ValueError):
        h.acquisition_manifest(window_size=7)


@pytest.mark.parametrize('count,status', [(0, 'EMPTY_OBSERVED'), (249, 'COMPLETE_OBSERVED'), (250, 'SATURATED_INCOMPLETE'), (251, 'SATURATED_INCOMPLETE')])
def test_saturation(archive, count, status):
    assert retain(archive, [article(i) for i in range(count)]) == status
    assert archive.completed('NVDA', DAY) == (count < 250)


def test_spill_dedup_and_versions(archive):
    spill = article(2, '2026-09-10T00:00:00Z')
    assert retain(archive, [article(), spill]) == 'SPILL_PRESENT'
    retain(archive, [spill], '2026-09-10')
    events = list(archive.events())
    assert len(events) == 2
    event = next(e for e in events if e['article_id'] == '2')
    assert event['canonical_day'] == '2026-09-10'
    assert [o['outside_requested_membership'] for o in event['observations']] == [1, 0]
    retain(archive, [article(headline='changed')])
    versions = [e for e in archive.events() if e['article_id'] == '1']
    assert len(versions) == 2
    assert len({e['version_id'] for e in versions}) == 2
    assert {e['first_observed_by_astra'] for e in versions} == {RECEIPT}


def test_derived_identity(archive):
    retain(archive, [article(None)])
    assert next(archive.events())['identity_status'] == 'DERIVED_IDENTITY'


def test_receipt_and_unknown_clocks(archive):
    retain(archive, [article()])
    e = next(archive.events())
    assert e['available_to_astra_time'] == RECEIPT != e['publication_time']
    assert e['provider_observed_time'] is None
    assert e['historical_source_available_time'] is None
    assert e['pit_metadata']['available_to_astra_time'] == RECEIPT
    assert not e['replay_safe']
    assert not historical_news_evidence_gate({**e, 'replay_safe': True}, RECEIPT)['replay_allowed']
    with pytest.raises(UnsafeReplayRecord):
        require_replay_safe(e['pit_metadata'])


def test_finnhub_cannot_bypass_gate_with_publication():
    e = normalize_historical_record({'source_provider': 'FINNHUB', 'event_time': RECEIPT, 'publication_time': RECEIPT}, dataset_type='news')
    assert not e['replay_safe']


def test_raw_response_and_provenance(archive):
    raw = article(source='Publisher', summary='Summary', url='https://example.test/a')
    retain(archive, [raw])
    e = next(archive.events())
    p = e['provenance']
    body = (archive.root / p['body_path']).read_bytes()
    assert json.loads(body) == [raw]
    assert h.hashlib.sha256(body).hexdigest() == p['response_sha256']
    assert p['rate_limit_headers'] == {'Retry-After': '60'}
    assert e['raw_hash'] == h.digest(raw)
    assert e['provider_native_timestamp'] == raw['datetime']
    assert e['summary'] == 'Summary'


def test_checkpoint_checksum_and_resume(archive):
    retain(archive, [article()])
    assert archive.completed('NVDA', DAY)
    e = next(archive.events())
    (archive.root / e['provenance']['body_path']).write_bytes(b'corrupt')
    assert not archive.completed('NVDA', DAY)


def test_failed_raw_write_never_checkpoints(archive, monkeypatch):
    def broken(*a):
        raise OSError('test disk failure')
    monkeypatch.setattr(h, 'durable_write', broken)
    with pytest.raises(OSError):
        retain(archive, [article()])
    assert archive.db.execute('SELECT count(*) FROM checkpoints').fetchone()[0] == 0


@pytest.mark.parametrize('code,state', [(401, 'AUTH_BLOCKED'), (403, 'AUTH_BLOCKED'), (429, 'RATE_LIMITED'), (503, 'TRANSIENT_FAILURE')])
def test_failure_retains_response(archive, code, state):
    assert retain(archive, {'error': 'test'}, status=code) == state
    assert not archive.completed('NVDA', DAY)
    assert archive.db.execute('SELECT count(*) FROM requests').fetchone()[0] == 1


def sec():
    return h.normalized_sec_event('ABC', '123', {'accessionNumber': '000123-26-000001', 'form': '8-K', 'items': '2.02',
        'acceptanceDateTime': '2026-09-09T20:00:00Z', 'filingDate': DAY, 'reportDate': '2026-06-30', 'primaryDocument': 'a.htm'}, RECEIPT, 'https://data.sec.gov/submissions/CIK0000000123.json')


def test_sec_acceptance_and_cutoffs():
    e = sec()
    assert e['economic_event_time'] == '2026-06-30'
    assert e['historical_source_available_time'] == '2026-09-09T20:00:00Z'
    assert e['available_to_astra_time'] == RECEIPT
    assert e['pit_metadata']['available_to_astra_time'] == RECEIPT
    assert e['replay_safe']
    assert not historical_news_evidence_gate(e, '2026-09-09T19:59:59Z')['replay_allowed']
    assert historical_news_evidence_gate(e, '2026-09-09T20:00:00Z')['replay_allowed']
    assert not historical_news_evidence_gate(e, '2026-09-09T20:00:00Z', basis='actual_astra')['replay_allowed']


@pytest.mark.parametrize('field', ['source_provider', 'article_id', 'version_id', 'raw_hash', 'publication_time', 'historical_source_available_time'])
def test_gate_missing_evidence(field):
    e = sec()
    e[field] = None
    if field == 'article_id':
        e['source_record_id'] = None
    assert not historical_news_evidence_gate(e, RECEIPT)['replay_allowed']


def test_gate_temporal_contradiction():
    e = sec()
    e['temporal_contradiction'] = True
    assert not historical_news_evidence_gate(e, RECEIPT)['replay_allowed']


def test_current_fred_cannot_leak_backward():
    e = h.normalize_existing_event({'observation_date': '2020-01-01', 'value': 123, 'series_id': 'TEST'}, provider='FRED', family='macro', source_file='fixture', receipt=RECEIPT)
    assert not e['replay_safe']
    assert e['readiness'] == 'PROVIDER_REQUIRED'
    assert e['point_in_time_status'] == 'CURRENT_SNAPSHOT_ONLY'


def test_fmp_envelope_preserved():
    raw = {'family': 'earnings', 'symbol': 'ABC', 'retrieved_at': RECEIPT, 'record': {'date': DAY, 'epsActual': 2, 'epsEstimated': 1, 'revenueActual': 100, 'lastUpdated': DAY}, 'endpoint': '/stable/earnings'}
    e = h.normalize_existing_event(raw, provider='FMP', family='earnings', source_file='retained.gz')
    assert e['epsActual'] == 2 and e['epsEstimated'] == 1
    assert e['available_to_astra_time'] == RECEIPT
    assert e['raw_hash'] == h.digest(raw)
    assert e['original_provider_fields']['lastUpdated'] == DAY
    assert not e['replay_safe']


def test_planner_default_and_scale_authorization(tmp_path):
    m = h.acquisition_manifest(symbols=['NVDA'], start=DAY, end=DAY)
    assert m['mode'] == 'DRY_RUN'
    assert h.acquire(m, tmp_path / 'unused', None, tmp_path)['requests'] == 0
    assert not (tmp_path / 'unused').exists()
    with pytest.raises(ValueError):
        h.acquisition_manifest(mode='AUTHORIZED_SCALE')
    with pytest.raises(ValueError):
        h.acquisition_manifest(mode='BOUNDED_PILOT', symbols=['NVDA'], start='2025-09-09', end=DAY)


def test_acquire_daily_resume_and_pressure(tmp_path, monkeypatch):
    monkeypatch.setattr(h, 'resource_ready', lambda *a: True)
    calls = []
    class Router:
        def _key_for(self, *a):
            return 'test-only'
        def _request(self, provider, url, *, params, evidence_sink):
            calls.append(params)
            evidence_sink(200, {}, json.dumps([article()]).encode())
            return {}, 200, '', 0
    m = h.acquisition_manifest(mode='BOUNDED_PILOT', symbols=['NVDA'], start=DAY, end=DAY)
    assert h.acquire(m, tmp_path / 'archive', Router(), tmp_path)['requests'] == 1
    assert calls[0]['from'] == calls[0]['to'] == DAY
    assert h.acquire(m, tmp_path / 'archive', Router(), tmp_path)['requests'] == 0
    monkeypatch.setattr(h, 'resource_ready', lambda *a: False)
    assert h.acquire(m, tmp_path / 'other', Router(), tmp_path)['status'] == 'RESOURCE_WAIT'
    assert len(calls) == 1


def test_safety_and_taxonomy(archive):
    retain(archive, [article(headline='FDA approves acquisition and upgrade')])
    e = next(archive.events())
    assert e['event_type'] == 'UNCLASSIFIED_NEWS'
    for field in ('broker_truth_eligible', 'natural_truth_eligible', 'learning_ack_eligible', 'automatic_policy_promotion'):
        assert e[field] is False
    assert 'CRYPTO_TOKEN_UNLOCK' in h.EVENT_TYPES
    assert h.CONTRACTS['analyst_revision']['status'] == 'DATA_SOURCE_REQUIRED'
    assert h.CONTRACTS['microstructure']['status'] == 'PROVIDER_REQUIRED'


def test_cooldown_survives_reopen(archive):
    retain(archive, [], status=429)
    assert archive.cooling_down()
    other = h.NewsArchive(archive.root)
    try:
        assert other.cooling_down()
    finally:
        other.close()


def test_truncated_body_cannot_complete(archive):
    state = archive.retain('NVDA', DAY, DAY, RECEIPT, RECEIPT, 200, {'X-Astra-Truncated': 'true'}, b'[]')
    assert state == 'RETRYABLE'
    assert not archive.completed('NVDA', DAY)


def test_sec_version_and_subsecond_cutoff():
    raw = {'accessionNumber': 'test', 'form': '8-K', 'acceptanceDateTime': '2026-09-09T20:00:00.500Z'}
    e = h.normalized_sec_event('ABC', 123, raw, RECEIPT, 'SEC')
    assert e['replay_safe']
    assert not historical_news_evidence_gate(e, '2026-09-09T20:00:00.100Z')['replay_allowed']
    assert historical_news_evidence_gate(e, '2026-09-09T20:00:00.500Z')['replay_allowed']
    require_replay_safe(e['pit_metadata'])
    e['version_id'] = 'wrong-version'
    assert not historical_news_evidence_gate(e, RECEIPT)['replay_allowed']


def test_raw_hash_tampering_rejected():
    e = sec()
    e['raw_provenance']['acceptanceDateTime'] = '2026-09-10T20:00:00Z'
    assert not historical_news_evidence_gate(e, RECEIPT)['replay_allowed']


def test_existing_reader_skips_bars_and_unwraps(tmp_path):
    path = tmp_path / 'existing.jsonl'
    rows = [{'family': 'tier3_intraday_1min', 'record': {'close': 1}},
            {'family': 'corporate_actions_dividends', 'symbol': 'ABC', 'retrieved_at': RECEIPT, 'record': {'date': DAY, 'dividend': 1}}]
    path.write_text('\n'.join(json.dumps(r) for r in rows))
    events = list(h.iter_existing_events(path, provider='FMP'))
    assert len(events) == 1
    assert events[0]['event_type'] == 'DIVIDEND'
    assert events[0]['dividend'] == 1
    assert events[0]['original_provider_fields'] == rows[1]['record']
    assert list(h.iter_existing_events(path, provider='FMP', max_records=1)) == []


def test_microstructure_no_invented_clocks():
    e = h.normalize_microstructure({'bid': 10, 'ask': 11, 'event_time': RECEIPT}, provider='TEST', source_file='fixture')
    assert e['bid'] == 10
    assert e['provider_receive_time'] is None
    assert e['available_to_astra_time'] is None
    assert not e['replay_safe']


def test_manifest_cli_cannot_acquire(tmp_path):
    path = tmp_path / 'manifest.json'
    assert h.main(['--output', str(path)]) == 0
    assert json.loads(path.read_text())['mode'] == 'DRY_RUN'
    assert not json.loads(path.read_text())['acquisition_started']


def test_router_raw_sink_and_unchanged_default(monkeypatch):
    from engine import provider_router as p
    calls, captures, accounting = [], [], []
    monkeypatch.setattr(p, 'get_call_permission', lambda *a, **k: True)
    monkeypatch.setattr(p, 'record_call', lambda *a, **k: accounting.append('call'))
    monkeypatch.setattr(p, 'record_error', lambda *a, **k: None)
    class Response:
        status_code = 200
        headers = {'X-RateLimit-Remaining': '1'}
        _content = b'[{"id":1}]'
        @property
        def content(self):
            return self._content
        def iter_content(self, size):
            yield self._content
        def close(self):
            pass
        def json(self):
            return json.loads(self.content)
    def get(*a, **kw):
        calls.append(kw)
        return Response()
    monkeypatch.setattr(p.requests, 'get', get)
    router = p.ProviderRouter()
    sink = lambda status, headers, body: captures.append((status, headers, body))
    for _ in range(2):
        assert router._request('FINNHUB', 'https://example.test/news', evidence_sink=sink)[1] == 200
    assert len(captures) == len(accounting) == 2
    assert captures[0][2] == b'[{"id":1}]'
    assert calls[0]['stream'] is True and calls[0]['allow_redirects'] is False
    router._request('FINNHUB', 'https://example.test/default')
    assert 'stream' not in calls[-1] and 'allow_redirects' not in calls[-1]
    router._request('FINNHUB', 'https://example.test/default')
    assert len(calls) == 3  # existing coalescing unchanged


def test_router_governor_denial_no_network(monkeypatch):
    from engine import provider_router as p
    monkeypatch.setattr(p, 'get_call_permission', lambda *a, **k: False)
    def forbidden(*a, **k):
        raise AssertionError('network must not run')
    monkeypatch.setattr(p.requests, 'get', forbidden)
    assert p.ProviderRouter()._request('FINNHUB', 'https://example.test', evidence_sink=forbidden)[1] == 429


def test_canonical_fred_publication_without_vintage_is_not_proof():
    raw = {'observation_date': DAY, 'publication_time': RECEIPT}
    assert not normalize_historical_record(raw, dataset_type='fred')['replay_safe']
    raw['vintage_timestamp'] = RECEIPT
    assert not normalize_historical_record(raw, dataset_type='fred', source_context={'current_snapshot_only': True})['replay_safe']


def test_evidence_gate_does_not_override_canonical_veto():
    assert not normalize_historical_record(sec(), dataset_type='catalyst', source_context={'replay_contract_valid': False})['replay_safe']


def test_resource_unknown_and_stale_fail_closed(tmp_path, monkeypatch):
    base = {'worker_count': 1, 'last_error': '', 'updated_at': RECEIPT, 'resource_state': 'UNKNOWN'}
    monkeypatch.setattr(h, 'worker_health', lambda *_: base)
    assert not h.resource_ready(tmp_path, tmp_path, 0)
    base.update(resource_state='RESOURCE_NORMAL', updated_at='2000-01-01T00:00:00Z')
    assert not h.resource_ready(tmp_path, tmp_path, 0)


def test_saturated_day_never_downgraded(archive):
    assert retain(archive, [article(i) for i in range(250)]) == 'SATURATED_INCOMPLETE'
    assert retain(archive, []) == 'SATURATED_INCOMPLETE'
    assert not archive.completed('NVDA', DAY)


def test_duplicate_receipt_does_not_backdate(archive):
    retain(archive, [article()])
    archive.retain('NVDA', DAY, DAY, RECEIPT, '2026-09-19T12:00:00Z', 200, {}, json.dumps([article()]).encode())
    assert next(archive.events())['available_to_astra_time'] == RECEIPT
