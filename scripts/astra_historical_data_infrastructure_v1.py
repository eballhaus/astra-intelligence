#!/usr/bin/env python3
"""Bounded historical acquisition and adapters under Phase 2; no trading authority.

Default manifests are DRY_RUN. No module import or CLI path starts acquisition.
Raw immutable response shards precede transactional version/checkpoint indexing.
"""
from __future__ import annotations

import fcntl
import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from email.utils import parsedate_to_datetime

from engine.astra_pit_metadata_contract_v1 import normalize_historical_record, historical_news_evidence_gate
from scripts.astra_historical_context_phase2_v1 import now_iso, worker_health
from scripts.astra_historical_news_catalyst_pilot_v1 import SAFETY, digest, precise_time, sec_event, MATERIAL

EVENT_TYPES = frozenset('''EARNINGS_RESULT EARNINGS_SURPRISE GUIDANCE_RAISE GUIDANCE_CUT
ANALYST_UPGRADE ANALYST_DOWNGRADE ANALYST_ESTIMATE_REVISION ANALYST_PRICE_TARGET_CHANGE
ANALYST_RECOMMENDATION_CHANGE ANALYST_CONSENSUS_REVISION M_AND_A FDA_REGULATORY LEGAL_REGULATORY
MANAGEMENT_CHANGE PRODUCT_LAUNCH CONTRACT_CUSTOMER_WIN FINANCING_CAPITAL_RAISE BUYBACK DIVIDEND SPLIT
SEC_MATERIAL_FILING MACRO_EVENT SECTOR_EVENT CRYPTO_REGULATORY CRYPTO_LISTING_DELISTING
CRYPTO_PROTOCOL_UPGRADE CRYPTO_HACK_SECURITY CRYPTO_TOKEN_UNLOCK CRYPTO_GOVERNANCE
UNCLASSIFIED_NEWS'''.split())
SUCCESS = {'COMPLETE_OBSERVED', 'EMPTY_OBSERVED', 'SPILL_PRESENT'}
CONTRACTS = {
    'macro_vintage': {'status': 'PROVIDER_REQUIRED', 'fields': ['observation_date', 'release_date', 'vintage_date', 'realtime_start', 'provider_availability', 'ingested_at', 'source_series', 'version_id', 'availability_proof', 'replay_safe'], 'rule': 'Current revised snapshots cannot be used at historical cutoffs; date-only vintage is insufficient for intraday admission.'},
    'analyst_revision': {'status': 'DATA_SOURCE_REQUIRED', 'fields': ['symbol', 'analyst', 'firm', 'old_value', 'new_value', 'effective_time', 'publication_time', 'source_provider', 'record_id', 'version_id', 'availability_proof', 'point_in_time_status'], 'rule': 'No reconstructed consensus vintage or keyword-derived factual events.'},
    'microstructure': {'status': 'PROVIDER_REQUIRED', 'fields': ['bid', 'ask', 'bid_size', 'ask_size', 'spread', 'trade_price', 'trade_size', 'venue', 'event_time', 'provider_receive_time', 'available_to_astra_time', 'sequence', 'record_id', 'version_id', 'point_in_time_status'], 'local_index': ['state/historical_context_phase2_v1/microstructure_context_v1.jsonl', 'state/historical_context_phase2_v1/execution_realism_v1.jsonl'], 'rule': 'Existing OHLCV proxies are not historical quotes/trades; receive clocks must not be inferred.'},
}


def daily_windows(start, end):
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if last < first:
        raise ValueError('reversed date range')
    while first <= last:
        yield first.isoformat(), first.isoformat()
        first += timedelta(days=1)


def acquisition_manifest(*, provider='FINNHUB', dataset='company_news', symbols=(), start=None, end=None,
                         mode='DRY_RUN', window_size=1, authorized_scale=False, rate_budget=20,
                         max_calls=10, max_bytes=80 * 1024 * 1024, checkpoint_path=None, resume_state=None):
    if mode not in {'DRY_RUN', 'BOUNDED_PILOT', 'AUTHORIZED_SCALE'}:
        raise ValueError('invalid acquisition mode')
    if mode == 'AUTHORIZED_SCALE' and not authorized_scale:
        raise ValueError('explicit scale authorization required')
    if provider == 'FINNHUB' and dataset == 'company_news' and window_size != 1:
        raise ValueError('Finnhub archive requires from=to daily windows')
    symbols = sorted(set(symbols))
    if any(not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-]{0,19}', s) for s in symbols):
        raise ValueError('explicit bounded symbols required')
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1 if start and end else 0
    if (days <= 0 and start is not None) or bool(start) != bool(end) or rate_budget <= 0 or max_calls <= 0 or max_bytes <= 0:
        raise ValueError('invalid acquisition budget/range')
    calls = len(symbols) * days
    if mode == 'BOUNDED_PILOT' and (calls > 10 or len(symbols) > 3):
        raise ValueError('pilot limited to ten daily windows and three symbols')
    return {'schema_version': 'astra_historical_acquisition_v1', 'provider': provider, 'dataset': dataset,
            'symbols': symbols, 'start': start, 'end': end, 'window_size': window_size, 'mode': mode,
            'scale_authorized': bool(authorized_scale), 'priority': 'LOW', 'estimated_calls': calls,
            'estimated_bytes': calls * 150000, 'estimate_basis': 'planning estimate, not guaranteed yield',
            'checkpoint_path': checkpoint_path, 'pit_requirement': 'HISTORICAL_NEWS_EVIDENCE_GATE',
            'rate_budget': {'calls_per_minute': min(rate_budget, 20)},
            'resource_budget': {'max_calls': max_calls, 'max_bytes': max_bytes, 'max_in_flight': 1, 'min_free_bytes': 256 * 1024 * 1024},
            'resume_state': resume_state or {}, 'acquisition_started': False, **SAFETY}


def durable_write(path, body):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)
    return hashlib.sha256(body).hexdigest()


def news_event(symbol, raw, receipt, provenance):
    raw_hash = digest(raw)
    article = str(raw['id']) if raw.get('id') not in (None, '') else 'derived:' + digest(raw)
    try:
        native = raw.get('datetime')
        publication = datetime.fromtimestamp(float(native), UTC).isoformat().replace('+00:00', 'Z') if not isinstance(native, bool) else None
    except (ValueError, TypeError, OverflowError, OSError):
        publication = None
    event = {'symbol': symbol, 'event_type': 'UNCLASSIFIED_NEWS', 'classification_basis': 'UNCLASSIFIED_NEWS',
             'article_id': article, 'source_record_id': article, 'source_provider': 'FINNHUB',
             'identity_status': 'NATIVE_IDENTITY' if raw.get('id') not in (None, '') else 'DERIVED_IDENTITY',
             'provider_native_timestamp': raw.get('datetime'), 'publication_time': publication, 'event_time': publication,
             'provider_observed_time': None, 'historical_source_available_time': None,
             'available_to_astra_time': receipt, 'ingested_at': now_iso(), 'raw_hash': raw_hash,
             'version_id': digest(['FINNHUB', article, raw_hash]), 'source': raw.get('source'),
             'headline': raw.get('headline'), 'summary': raw.get('summary'), 'url': raw.get('url'),
             'provider_record_identity': article, 'provenance': provenance, 'historical_news_contract': True, **SAFETY}
    pit = normalize_historical_record(event, dataset_type='news')
    event.update({key: pit[key] for key in ('point_in_time_status', 'lookahead_risk', 'replay_safe', 'replay_safe_reason')})
    event['pit_metadata'] = pit
    event['canonical_day'] = publication[:10] if publication else None
    start = datetime.combine(date.fromisoformat(provenance['requested_from']), datetime.min.time(), UTC)
    stamp = datetime.fromisoformat(publication.replace('Z', '+00:00')) if publication else None
    event['outside_requested_membership'] = not (stamp is not None and start <= stamp < start + timedelta(days=1))
    return event


class NewsArchive:
    """SQLite is an index of immutable raw shards, not a new truth authority."""
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / 'index.sqlite3')
        self.db.executescript('''
        PRAGMA synchronous=FULL;
        CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY, metadata TEXT, body_path TEXT, checksum TEXT);
        CREATE TABLE IF NOT EXISTS versions(provider TEXT, article TEXT, hash TEXT, first_observed TEXT, event TEXT,
          PRIMARY KEY(provider,article,hash));
        CREATE TABLE IF NOT EXISTS observations(request_id TEXT, provider TEXT, article TEXT, hash TEXT, symbol TEXT, day TEXT, outside INTEGER,
          PRIMARY KEY(request_id,provider,article,hash,symbol));
        CREATE TABLE IF NOT EXISTS checkpoints(provider TEXT,symbol TEXT,day TEXT,status TEXT,request_id TEXT,
          PRIMARY KEY(provider,symbol,day));
        ''')

    def close(self):
        self.db.close()

    def completed(self, symbol, day):
        row = self.db.execute('SELECT status,body_path,checksum FROM checkpoints JOIN requests ON request_id=id WHERE provider=? AND symbol=? AND day=?', ('FINNHUB', symbol, day)).fetchone()
        if not row or row[0] not in SUCCESS:
            return False
        path = self.root / row[1]
        return path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == row[2]

    def retain(self, symbol, start, end, requested_at, received_at, status, headers, body):
        if start != end:
            raise ValueError('archive requests must use from=to')
        date.fromisoformat(start)
        request_id = uuid.uuid4().hex
        relative = f'raw/{request_id}.body'
        checksum = durable_write(self.root / relative, body)
        metadata = {'provider': 'FINNHUB', 'symbol': symbol, 'requested_from': start, 'requested_to': end,
                    'request_timestamp': requested_at, 'response_timestamp': received_at, 'http_status': status,
                    'response_bytes': len(body), 'response_sha256': checksum, 'body_path': relative,
                    'rate_limit_headers': {k: v for k, v in headers.items() if k.lower().startswith(('x-ratelimit', 'ratelimit')) or k.lower() == 'retry-after'}}
        metadata['response_complete'] = headers.get('X-Astra-Truncated') != 'true'
        retry = next((v for k, v in headers.items() if k.lower() == 'retry-after'), None)
        try:
            delay = max(0, float(retry))
        except (TypeError, ValueError):
            try:
                delay = max(0, parsedate_to_datetime(retry).timestamp() - time.time())
            except (TypeError, ValueError, AttributeError):
                delay = 60 if status == 429 else 30 if status and status >= 500 else 0
        reset = next((v for k, v in headers.items() if k.lower() == 'x-ratelimit-reset'), None)
        remaining = next((v for k, v in headers.items() if k.lower() == 'x-ratelimit-remaining'), None)
        if str(remaining) == '0':
            try:
                delay = max(delay, float(reset) - time.time(), 60)
            except (TypeError, ValueError):
                delay = max(delay, 60)
        metadata['retry_not_before_epoch'] = time.time() + delay
        durable_write(self.root / f'raw/{request_id}.json', json.dumps(metadata, sort_keys=True).encode())
        rows = []
        state = 'AUTH_BLOCKED' if status in (401, 403) else 'RATE_LIMITED' if status == 429 else 'TRANSIENT_FAILURE'
        if status == 200:
            try:
                rows = json.loads(body)
                if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
                    raise ValueError('invalid record collection')
                state = 'SATURATED_INCOMPLETE' if len(rows) >= 250 else 'COMPLETE_OBSERVED' if rows else 'EMPTY_OBSERVED'
            except (ValueError, UnicodeDecodeError):
                rows = []
                state = 'RETRYABLE'
        if not metadata['response_complete']:
            state = 'RETRYABLE'
        # A later smaller response cannot prove an earlier capped day exhaustive.
        prior = self.db.execute('SELECT status FROM checkpoints WHERE provider=? AND symbol=? AND day=?', ('FINNHUB', symbol, start)).fetchone()
        saturated = self.db.execute(
            "SELECT 1 FROM requests WHERE json_extract(metadata, '$.symbol')=? AND json_extract(metadata, '$.requested_from')=? AND json_extract(metadata, '$.saturated')=1 LIMIT 1",
            (symbol, start)).fetchone()
        metadata['saturated'] = len(rows) >= 250 or bool(saturated) or bool(prior and prior[0] == 'SATURATED_INCOMPLETE')
        if metadata['saturated']:
            state = 'SATURATED_INCOMPLETE'
        durable_write(self.root / f'raw/{request_id}.json', json.dumps(metadata, sort_keys=True).encode())
        with self.db:
            self.db.execute('INSERT INTO requests VALUES (?,?,?,?)', (request_id, json.dumps(metadata), relative, checksum))
            for raw in rows:
                event = news_event(symbol, raw, received_at, {**metadata, 'request_id': request_id})
                if state == 'COMPLETE_OBSERVED' and event['outside_requested_membership']:
                    state = 'SPILL_PRESENT'
                if not event['publication_time'] and state != 'SATURATED_INCOMPLETE':
                    state = 'PIT_BLOCKED'
                key = ('FINNHUB', event['article_id'], event['raw_hash'])
                self.db.execute('INSERT OR IGNORE INTO versions VALUES (?,?,?,?,?)', (*key, received_at, json.dumps(event)))
                self.db.execute('INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?,?)', (request_id, *key, symbol, event['canonical_day'], event['outside_requested_membership']))
            self.db.execute('INSERT OR REPLACE INTO checkpoints VALUES (?,?,?,?,?)', ('FINNHUB', symbol, start, state, request_id))
        return state

    def cooling_down(self):
        row = self.db.execute('SELECT metadata FROM requests ORDER BY rowid DESC LIMIT 1').fetchone()
        return bool(row and json.loads(row[0]).get('retry_not_before_epoch', 0) > time.time())

    def failure(self, symbol, day, status):
        request_id = uuid.uuid4().hex
        body = json.dumps({'provider': 'FINNHUB', 'symbol': symbol, 'requested_from': day,
                           'requested_to': day, 'at': now_iso(), 'status': status, 'http_response_received': False, 'retry_not_before_epoch': time.time() + (60 if status == 'RATE_LIMITED' else 30)}).encode()
        relative = f'raw/{request_id}.failure.json'
        checksum = durable_write(self.root / relative, body)
        with self.db:
            self.db.execute('INSERT INTO requests VALUES (?,?,?,?)', (request_id, body.decode(), relative, checksum))
            self.db.execute('INSERT OR REPLACE INTO checkpoints VALUES (?,?,?,?,?)', ('FINNHUB', symbol, day, status, request_id))

    def events(self):
        # One provider/article/raw version, all request and symbol associations.
        for provider, article, raw_hash, first, payload in self.db.execute('SELECT * FROM versions ORDER BY provider,article,first_observed'):
            event = json.loads(payload)
            event['first_observed_by_astra'] = self.db.execute('SELECT MIN(first_observed) FROM versions WHERE provider=? AND article=?', (provider, article)).fetchone()[0]
            event['version_first_observed_by_astra'] = first
            event['observations'] = [dict(zip(('request_id', 'symbol', 'canonical_day', 'outside_requested_membership'), row)) for row in self.db.execute('SELECT request_id,symbol,day,outside FROM observations WHERE provider=? AND article=? AND hash=?', (provider, article, raw_hash))]
            yield event


def resource_ready(state_dir, archive_root, minimum_free):
    health = worker_health(Path(state_dir))
    stamp = precise_time(health.get('updated_at'))
    if not stamp:
        return False
    age = (datetime.now(UTC) - datetime.fromisoformat(stamp.replace('Z', '+00:00'))).total_seconds()
    return bool(health['worker_count'] == 1 and health['resource_state'] == 'RESOURCE_NORMAL'
                and not health.get('background_work_suspended')
                and not health['last_error'] and 0 <= age <= 120 and shutil.disk_usage(archive_root).free >= minimum_free)


def acquire(manifest, archive, router, state_dir):
    """Explicit invocation only. Stops on denial, pressure or any incomplete day.

    Governor remains ProviderRouter's owner; conservative spacing and worker
    headroom are extra gates, not a claim of global API budget coordination.
    """
    if manifest['mode'] == 'DRY_RUN':
        return {'requests': 0, 'status': 'DRY_RUN'}
    checked = acquisition_manifest(provider=manifest['provider'], dataset=manifest['dataset'], symbols=manifest['symbols'],
        start=manifest['start'], end=manifest['end'], mode=manifest['mode'], window_size=manifest['window_size'],
        authorized_scale=manifest.get('scale_authorized', False))
    if checked['provider'] != 'FINNHUB' or checked['dataset'] != 'company_news':
        raise ValueError('only verified Finnhub daily acquisition implemented')
    budget = manifest['resource_budget']
    if budget['max_calls'] <= 0 or budget['max_bytes'] <= 0 or manifest['rate_budget']['calls_per_minute'] <= 0:
        raise ValueError('invalid budget')
    count = total_bytes = 0
    archive = NewsArchive(archive)
    lock = (archive.root / '.acquisition.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for symbol in checked['symbols']:
            for start, end in daily_windows(checked['start'], checked['end']):
                if archive.completed(symbol, start):
                    continue
                if archive.cooling_down():
                    return {'requests': count, 'status': 'RATE_LIMITED'}
                if count >= budget['max_calls'] or total_bytes + 8 * 1024 * 1024 > budget['max_bytes']:
                    return {'requests': count, 'status': 'BUDGET_WAIT'}
                if not resource_ready(state_dir, archive.root, budget['min_free_bytes']):
                    return {'requests': count, 'status': 'RESOURCE_WAIT'}
                key = router._key_for('FINNHUB', 'stock')
                if not key:
                    archive.failure(symbol, start, 'AUTH_BLOCKED')
                    return {'requests': count, 'status': 'AUTH_BLOCKED'}
                if count:
                    time.sleep(max(3, 60 / min(20, manifest['rate_budget']['calls_per_minute'])))
                    if not resource_ready(state_dir, archive.root, budget['min_free_bytes']):
                        return {'requests': count, 'status': 'RESOURCE_WAIT'}
                requested = now_iso()
                captured = {}
                def retain(status, headers, body):
                    nonlocal total_bytes
                    captured['status'] = archive.retain(symbol, start, end, requested, now_iso(), status, headers, body)
                    total_bytes += len(body)
                _, status, error, _ = router._request('FINNHUB', 'https://finnhub.io/api/v1/company-news',
                    params={'symbol': symbol, 'from': start, 'to': end, 'token': key}, evidence_sink=retain)
                count += 1
                outcome = captured.get('status', 'RATE_LIMITED' if status == 429 else 'TRANSIENT_FAILURE')
                if not captured:
                    archive.failure(symbol, start, outcome)
                if outcome not in SUCCESS or error:
                    return {'requests': count, 'status': outcome}
        return {'requests': count, 'status': 'COMPLETE_OBSERVED', 'exhaustive_coverage_proven': False}
    finally:
        lock.close()
        archive.close()


def normalized_sec_event(symbol, cik, raw, receipt, endpoint):
    if raw.get('form') not in MATERIAL:
        raise ValueError('unsupported material SEC form')
    event = sec_event(symbol, cik, raw, receipt, endpoint)
    event.update(cik=cik, accession_number=raw.get('accessionNumber'), filing_type=raw.get('form'),
                 filing_acceptance_timestamp=raw.get('acceptanceDateTime'), filing_date=raw.get('filingDate'),
                 issuer_symbol_mapping={'cik': cik, 'symbol': symbol}, retrieval_time=receipt,
                 economic_event_time=raw.get('reportDate'), provider_observed_time=None,
                 article_id=raw.get('accessionNumber'), version_id=digest(['SEC_EDGAR', raw.get('accessionNumber'), digest(raw)]),
                 historical_news_contract=True, provider_native_timestamp=raw.get('acceptanceDateTime'),
                 event_type='EARNINGS_RESULT' if event['event_type'] == 'earnings' else 'SEC_MATERIAL_FILING',
                 classification_basis='STRUCTURED_SOURCE_EVENT')
    event['availability_proof'] = {'basis': 'SEC_ACCEPTANCE', 'accession': event['article_id'], 'acceptance_time': event['publication_time'], 'raw_hash': event['raw_hash']}
    event['pit_metadata'] = normalize_historical_record(event, dataset_type='catalyst')
    event.update({k: event['pit_metadata'][k] for k in ('replay_safe', 'point_in_time_status', 'lookahead_risk', 'replay_safe_reason')})
    return event


def normalize_existing_event(raw, *, provider, family, source_file, receipt=None):
    """One retained structured row. No fetch, raw duplication, inferred timezone or publication."""
    envelope = raw if isinstance(raw.get('record'), dict) else None
    if envelope is not None:
        receipt = receipt or envelope.get('retrieved_at')
        family = envelope.get('family', family)
        raw = envelope['record']
    family = {'corporate_actions_dividends': 'dividends', 'etf_dividends': 'dividends',
              'corporate_actions_splits': 'splits', 'etf_splits': 'splits'}.get(family, family)
    event_type = {'earnings': 'EARNINGS_RESULT', 'earnings_surprise': 'EARNINGS_SURPRISE',
                  'dividends': 'DIVIDEND', 'splits': 'SPLIT', 'macro': 'MACRO_EVENT'}.get(family, 'UNCLASSIFIED_NEWS')
    raw_hash = digest(envelope if envelope is not None else raw)
    identity = raw.get('id') or raw.get('record_id') or 'derived:' + raw_hash
    publication = precise_time(raw.get('publication_time') or raw.get('published_at'))
    event = {'symbol': raw.get('symbol') or (envelope.get('symbol') if envelope else None), 'event_type': event_type, 'source_provider': provider,
             'classification_basis': 'STRUCTURED_SOURCE_EVENT' if event_type != 'UNCLASSIFIED_NEWS' else 'UNCLASSIFIED_NEWS',
             'source_record_id': str(identity), 'record_id': str(identity), 'version_id': digest([provider, identity, raw_hash]),
             'raw_hash': raw_hash, 'event_time': raw.get('date') or raw.get('observation_date') or raw.get('period_end'),
             'publication_time': publication, 'provider_observed_time': None, 'historical_source_available_time': None,
             'available_to_astra_time': receipt or raw.get('retrieved_at') or raw.get('ingested_at'), 'ingested_at': now_iso(),
             'source_file': source_file, 'provenance': {'source_file': source_file, 'raw_hash': raw_hash, 'family': family, 'endpoint': envelope.get('endpoint') if envelope else None, 'requested_params': envelope.get('requested_params') if envelope else None},
             'original_provider_fields': dict(raw), **SAFETY}
    for key in ('epsActual', 'epsEstimated', 'revenueActual', 'revenueEstimated', 'eps', 'epsEstimate', 'revenue', 'revenueEstimate', 'surprise', 'dividend', 'split', 'analyst', 'firm', 'old_value', 'new_value', 'effective_time', 'observation_date', 'release_date', 'vintage_date', 'realtime_start', 'series_id'):
        event[key] = raw.get(key)
    event['pit_metadata'] = normalize_historical_record(event, dataset_type='fred' if family == 'macro' else 'earnings' if family.startswith('earnings') else 'corporate_action', source_context={'replay_contract_valid': False, 'current_snapshot_only': family == 'macro'})
    event.update(replay_safe=False, point_in_time_status='CURRENT_SNAPSHOT_ONLY' if family == 'macro' and not raw.get('realtime_start') else 'PARTIALLY_POINT_IN_TIME', lookahead_risk='HIGH', replay_safe_reason='REJECTED: version-specific historical publication availability unproven')
    event['pit_metadata'].update({k: event[k] for k in ('replay_safe', 'point_in_time_status', 'lookahead_risk', 'replay_safe_reason')})
    event['readiness'] = 'PROVIDER_REQUIRED' if family == 'macro' else 'DATA_SOURCE_REQUIRED' if family == 'analyst_revision' else 'PARTIAL'
    return event


def iter_existing_events(path, *, provider, family=None, max_records=100):
    """Bounded streaming view of existing storage, never reacquires or writes raw."""
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rt') as stream:
        for index, line in enumerate(stream):
            if index >= max_records:
                break
            raw = json.loads(line)
            actual_family = raw.get('family', family)
            if actual_family not in {'earnings', 'earnings_surprise', 'dividends', 'splits', 'corporate_actions_dividends', 'corporate_actions_splits', 'etf_dividends', 'etf_splits', 'income_statement', 'balance_sheet', 'cash_flow', 'symbol_changes', 'delistings', 'macro', 'analyst_revision'}:
                continue
            yield normalize_existing_event(raw, provider=provider, family=actual_family, source_file=str(path))


def normalize_microstructure(raw, *, provider, source_file):
    """Future retained quote/trade adapter; no receive-time inference or fetch."""
    event = normalize_existing_event(raw, provider=provider, family='microstructure', source_file=source_file)
    for key in CONTRACTS['microstructure']['fields']:
        if key not in {'point_in_time_status', 'record_id', 'version_id', 'available_to_astra_time'}:
            event[key] = raw.get(key)
    event['available_to_astra_time'] = raw.get('available_to_astra_time')
    event['pit_metadata']['available_to_astra_time'] = event['available_to_astra_time']
    event['readiness'] = 'PROVIDER_REQUIRED'
    return event


def main(argv=None):
    """Generate a manifest only. Acquisition is never launched by this CLI."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbols', nargs='*', default=[])
    parser.add_argument('--start')
    parser.add_argument('--end')
    parser.add_argument('--mode', choices=['DRY_RUN', 'BOUNDED_PILOT', 'AUTHORIZED_SCALE'], default='DRY_RUN')
    parser.add_argument('--authorize-scale', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = acquisition_manifest(symbols=args.symbols, start=args.start, end=args.end,
                                    mode=args.mode, authorized_scale=args.authorize_scale)
    durable_write(args.output, (json.dumps(manifest, indent=2) + '\n').encode())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
