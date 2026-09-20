#!/usr/bin/env python3
"""Bounded SEC catalyst backfill; no execution or production truth authority.

Finnhub acquisition is deliberately blocked unless the separate tiny probe
proves historical records. This version supports the verified SEC fallback.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.astra_pit_metadata_contract_v1 import normalize_historical_record, require_replay_safe, UnsafeReplayRecord
from scripts.astra_historical_context_phase2_v1 import atomic_json, read_json, now_iso

START, END = '2025-09-12', '2026-09-11'
ARCHIVE = ROOT / 'state/historical_context_phase2_v1/news_catalyst_pilot_v1'
MANIFEST = ROOT / 'reports/astra_historical_news_catalyst_pilot_manifest_v1.json'
MATERIAL = {'8-K', '8-K/A', '6-K', '6-K/A', '10-K', '10-K/A', '10-Q', '10-Q/A', '20-F', '20-F/A', '40-F', '40-F/A'}
SAFETY = {'historical_replay_only': True, 'evidence_class': 'HISTORICAL_REPLAY', 'broker_truth_eligible': False, 'natural_truth_eligible': False, 'learning_ack_eligible': False, 'automatic_policy_promotion': False}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def precise_time(value):
    try:
        if not isinstance(value, str) or 'T' not in value:
            return None
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return dt.astimezone(UTC).isoformat().replace('+00:00', 'Z') if dt.tzinfo else None
    except ValueError:
        return None


def sec_event(symbol, cik, raw, ingested, endpoint):
    """Acceptance, never filing/period date, proves disclosure availability."""
    publication = precise_time(raw.get('acceptanceDateTime'))
    accession = raw.get('accessionNumber')
    form = raw.get('form', '')
    # Item 2.02 is explicit results-of-operations disclosure, not an EPS surprise.
    items = {v.strip() for v in str(raw.get('items', '')).split(',')}
    category = 'earnings' if form in {'8-K', '8-K/A'} and '2.02' in items else 'sec_material_filing'
    url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{str(accession).replace('-', '')}/{raw.get('primaryDocument', '')}"
    event = {'symbol': symbol, 'asset_class': 'EQUITY', 'event_type': category,
             'headline': raw.get('primaryDocDescription') or None, 'title': raw.get('primaryDocDescription') or None,
             'summary': None, 'publication_time': publication,
             'provider_timestamp': raw.get('acceptanceDateTime'),
             'available_to_astra_time': ingested, 'event_time': publication,
             'event_time_basis': 'filing disclosure itself; economic period retained only in raw provenance',
             'source_provider': 'SEC_EDGAR', 'source_record_id': accession,
             'source_url': url, 'source_endpoint': endpoint, 'ingested_at': ingested,
             'sentiment': None, 'raw_provenance': raw, 'raw_hash': digest(raw),
             'availability_basis': 'SEC acceptanceDateTime; historical source availability, not historical Astra receipt',
             'is_amendment': form.endswith('/A'), 'original_accession': None,
             'revision_policy': 'immutable accession and raw hash; amendments never overwrite earlier filings',
             'classification_basis': 'SEC form and explicit item 2.02 only', **SAFETY}
    pit = normalize_historical_record(event, dataset_type='catalyst')
    for key in ('point_in_time_status', 'lookahead_risk', 'replay_safe', 'replay_safe_reason'):
        event[key] = pit[key]
    if not accession or not publication:
        event.update(replay_safe=False, point_in_time_status='TIMESTAMP_INSUFFICIENT', lookahead_risk='UNKNOWN', replay_safe_reason='REJECTED: missing accession or timezone-qualified acceptance timestamp')
    event['pit_metadata'] = {**pit, **{k:event[k] for k in ('replay_safe','point_in_time_status','lookahead_risk','replay_safe_reason')}}
    event['historical_source_available_time'] = publication
    event['record_id'] = digest([symbol, 'SEC_EDGAR', accession, event['raw_hash']])
    return event


def same_catalyst(a, b):
    """Conservative dedup: identity + symbol/category + <=1h publication proximity."""
    if (a['symbol'], a['event_type']) != (b['symbol'], b['event_type']):
        return False
    if a['source_provider'] == b['source_provider'] and a['source_record_id'] == b['source_record_id']:
        return True  # revisions share identity, but retain their individual clocks
    ta, tb = precise_time(a.get('publication_time')), precise_time(b.get('publication_time'))
    if not ta or not tb or abs((datetime.fromisoformat(ta.replace('Z','+00:00'))-datetime.fromisoformat(tb.replace('Z','+00:00'))).total_seconds()) > 3600:
        return False
    def canonical_url(event):
        p = urlsplit(event.get('source_url') or '')
        return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path, '', '')) if p.netloc else None
    return bool(canonical_url(a)) and canonical_url(a) == canonical_url(b)


def cluster_events(events):
    clusters = []
    for event in sorted(events, key=lambda x:(x.get('publication_time') or '', x['record_id'])):
        target = next((c for c in clusters if same_catalyst(c['provenance_records'][0], event)), None)
        if target is None:
            target = {'canonical_event_id': digest([event['symbol'], event['event_type'], event['source_provider'], event['source_record_id']]), 'symbol':event['symbol'], 'event_type':event['event_type'], 'provenance_records':[], **SAFETY}
            clusters.append(target)
        target['provenance_records'].append(event)
    for cluster in clusters:
        records=cluster['provenance_records']
        # Top-level fields describe the first immutable version, never a later revision.
        first=next((r for r in records if r['replay_safe']),records[0])
        for k in ('headline','summary','publication_time','provider_timestamp','available_to_astra_time','event_time','source_provider','source_record_id','source_url','ingested_at','sentiment','point_in_time_status','lookahead_risk','replay_safe','replay_safe_reason'):
            cluster[k]=first[k]
        cluster['duplicate_cluster']=len(records)>1
    return clusters


def replay_as_of(clusters, cutoff, *, basis='actual_astra'):
    """Archive adapter calls the canonical admission owner before any as-of join.

    Consumers receive only versions visible at cutoff, not future revisions.
    Nothing is written to the historical learner, broker, or policy stores.
    """
    when=precise_time(cutoff)
    if when is None or basis not in {'actual_astra','historical_source'}:
        raise ValueError('explicit aware cutoff and supported availability basis required')
    output=[]
    for cluster in clusters:
        visible=[]
        for event in cluster['provenance_records']:
            try:
                require_replay_safe(event['pit_metadata'])
            except UnsafeReplayRecord:
                continue
            available=event['available_to_astra_time'] if basis=='actual_astra' else event['historical_source_available_time']
            if available and datetime.fromisoformat(available.replace('Z','+00:00')) <= datetime.fromisoformat(when.replace('Z','+00:00')) and datetime.fromisoformat(event['publication_time'].replace('Z','+00:00')) <= datetime.fromisoformat(when.replace('Z','+00:00')):
                visible.append(event)
        if visible:
            output.append({'canonical_event_id':cluster['canonical_event_id'], 'symbol':cluster['symbol'], 'event_type':cluster['event_type'], 'provenance_records':visible, 'availability_basis':basis, **SAFETY})
    return output


def write_jsonl(path, rows):
    tmp=path.with_suffix('.tmp')
    with tmp.open('w') as f:
        for row in rows:f.write(json.dumps(row,sort_keys=True,separators=(',',':'))+'\n')
        f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)


def collect(archive=ARCHIVE):
    from dotenv import dotenv_values
    for k,v in dotenv_values('/Users/Shared/AstraRuntime/.env').items():
        if k in {'ASTRA_SEC_USER_AGENT','SEC_USER_AGENT'} and v:os.environ[k]=v
    from engine.provider_router import ProviderRouter
    manifest=read_json(MANIFEST)
    symbols=[r['symbol'] for r in manifest['symbols']]
    assert len(symbols)==len(set(symbols))==25 and manifest['historical_window']==[START,END]
    probe=read_json(archive/'probe.json',{})
    if probe.get('SEC_EDGAR',{}).get('status')!='SUCCESS':raise ValueError('SEC access probe must succeed first')
    ua=os.getenv('ASTRA_SEC_USER_AGENT') or os.getenv('SEC_USER_AGENT')
    if not ua:raise ValueError('SEC identification missing')
    ciks={}
    with (ROOT/'state/historical_context_phase2_v1/sec_filings_context_v1.jsonl').open() as f:
        for line in f:
            r=json.loads(line)
            if r.get('symbol') in symbols and r.get('cik'):ciks[r['symbol']]=r['cik']
    router=ProviderRouter()
    for symbol in symbols:
        directory=archive/symbol;directory.mkdir(parents=True,exist_ok=True)
        checkpoint=read_json(directory/'checkpoint.json',{})
        identity_history=manifest.get('issuer_history',{}).get(symbol,[])
        identity_version=digest(['retain_out_of_identity_scope_v1',identity_history])
        if checkpoint.get('status')=='COMPLETED' and checkpoint.get('identity_version')==identity_version:continue
        cik=ciks.get(symbol)
        if not cik:
            atomic_json(directory/'checkpoint.json',{'status':'MISSING_CIK','symbol':symbol});continue
        base=f'https://data.sec.gov/submissions/CIK{str(cik).zfill(10)}.json'
        scopes={str(cik).zfill(10):(START,END)}
        for identity in identity_history:
            scopes[identity['cik']]=(identity['from'],identity['to'])
        pending=[base]+[f'https://data.sec.gov/submissions/CIK{other}.json' for other in scopes if other!=str(cik).zfill(10)]
        completed=[];events=[];failures=[]
        while pending:
            endpoint=pending.pop(0)
            endpoint_cik=endpoint.split('CIK')[-1][:10]
            scope_start,scope_end=scopes[endpoint_cik]
            cache=directory/(digest(endpoint)+'.response.json')
            saved=read_json(cache)
            if saved is None:
                time.sleep(1.1)  # below public SEC limit; canonical governor still owns permission
                data,status,error,_=router._request('SEC_EDGAR',endpoint,headers={'User-Agent':ua})
                at=now_iso()
                with (archive/'requests.jsonl').open('a') as f:
                    f.write(json.dumps({'at':at,'provider':'SEC_EDGAR','symbol':symbol,'endpoint':endpoint,'http_status':status,'error_class':('GOVERNOR_OR_RATE_LIMIT' if status==429 else 'HTTP_ERROR' if status else 'TRANSPORT_ERROR') if error else None})+'\n')
                if error or status!=200:
                    failures.append({'endpoint':endpoint,'http_status':status});break
                columns=data.get('filings',{}).get('recent',{}) if 'filings' in data else data
                rows=[]
                for i, date in enumerate(columns.get('filingDate',[])):
                    raw={k:v[i] for k,v in columns.items() if isinstance(v,list) and len(v)>i}
                    pub=precise_time(raw.get('acceptanceDateTime'))
                    date_key=pub[:10] if pub else date
                    if START<=date_key<=END and raw.get('form') in MATERIAL:rows.append(raw)
                children=[v['name'] for v in data.get('filings',{}).get('files',[]) if v.get('filingFrom','9999')<=END and v.get('filingTo','')>=START]
                # Persist only the authorized window/material records; metadata endpoint cannot filter server-side.
                saved={'endpoint':endpoint,'ingested_at':at,'rows':rows,'children':children,'http_status':status,'response_sha256':digest(data),'response_filing_date_range':[min(columns.get('filingDate') or ['']),max(columns.get('filingDate') or [''])]}
                atomic_json(cache,saved)
            completed.append(endpoint)
            for child in saved['children']:
                if '/' in child or not child.startswith('CIK'+endpoint_cik):raise ValueError('invalid SEC child identity')
                url='https://data.sec.gov/submissions/'+child
                if url not in completed and url not in pending:pending.append(url)
            for raw in saved['rows']:
                date_key=(precise_time(raw.get('acceptanceDateTime')) or raw.get('filingDate',''))[:10]
                event=sec_event(symbol,endpoint_cik,raw,saved['ingested_at'],endpoint)
                event['issuer_cik']=endpoint_cik
                event['issuer_identity_evidence']=identity_history or 'existing canonical SEC symbol/CIK context'
                event['record_id']=digest([event['record_id'],endpoint_cik])
                if not scope_start<=date_key<=scope_end:
                    event.update(replay_safe=False,point_in_time_status='PARTIALLY_POINT_IN_TIME',lookahead_risk='UNKNOWN',replay_safe_reason='REJECTED: source issuer outside proven symbol identity interval')
                    event['pit_metadata'].update({k:event[k] for k in ('replay_safe','point_in_time_status','lookahead_risk','replay_safe_reason')})
                events.append(event)
            if len(completed)+len(pending)>10:raise ValueError('SEC child request bound exceeded')
        # Immutable raw record versions; exact repeats from overlapping submissions are one observation.
        events=list({r['record_id']:r for r in events}.values())
        clusters=cluster_events(events)
        write_jsonl(directory/'raw.jsonl',events)
        write_jsonl(directory/'canonical.jsonl',clusters)
        atomic_json(directory/'checkpoint.json',{'symbol':symbol,'identity_version':identity_version,'status':'FAILED' if failures else 'COMPLETED','completed_endpoints':completed,'raw_records':len(events),'canonical_events':len(clusters),'failures':failures,'updated_at':now_iso()})
        print(symbol, 'FAILED' if failures else 'COMPLETED', len(events),flush=True)
        if failures:break  # fail closed on provider issues, no repeated denied requests


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collect',action='store_true')
    args=parser.parse_args()
    if args.collect:collect()
