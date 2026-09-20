from copy import deepcopy
from scripts.astra_historical_news_catalyst_pilot_v1 import sec_event, cluster_events, replay_as_of


def event(**changes):
    raw={'accessionNumber':'0000000001-25-000001','form':'8-K','items':'2.02','acceptanceDateTime':'2025-09-15T15:00:00Z','filingDate':'2025-09-15','reportDate':'2025-06-30','primaryDocument':'a.htm','primaryDocDescription':'Results'}
    raw.update(changes)
    return sec_event('AAPL','1',raw,'2026-09-20T15:00:00Z','https://data.sec.gov/submissions/CIK0000000001.json')


def test_sec_acceptance_and_actual_receipt_are_distinct_and_never_backdated():
    e=event();c=cluster_events([e])
    assert not replay_as_of(c,'2025-09-15T14:59:59Z',basis='historical_source')
    assert len(replay_as_of(c,'2025-09-15T15:00:00Z',basis='historical_source'))==1
    assert not replay_as_of(c,'2025-09-15T15:00:00Z')
    assert e['raw_provenance']['reportDate']=='2025-06-30'
    assert e['available_to_astra_time']=='2026-09-20T15:00:00Z'


def test_missing_ambiguous_and_date_only_publication_fail_closed():
    for stamp in (None,'2025-09-15','2025-09-15T15:00:00'):
        e=event(acceptanceDateTime=stamp)
        assert not e['replay_safe']
        assert not replay_as_of(cluster_events([e]),'2026-10-01T00:00:00Z',basis='historical_source')


def test_duplicate_vendors_do_not_double_count_and_revisions_do_not_leak():
    first=event();duplicate=deepcopy(first)
    duplicate.update(source_provider='TEST_VENDOR',source_record_id='test-article',record_id='test-record')
    revised=event(acceptanceDateTime='2025-09-16T15:00:00Z',primaryDocDescription='Revised')
    clusters=cluster_events([first,duplicate,revised])
    assert len(clusters)==1 and len(clusters[0]['provenance_records'])==3
    before=replay_as_of(clusters,'2025-09-15T16:00:00Z',basis='historical_source')
    assert len(before)==1 and len(before[0]['provenance_records'])==2
    assert all(r['title']=='Results' for r in before[0]['provenance_records'])
    assert first['publication_time']=='2025-09-15T15:00:00Z'


def test_distinct_accessions_and_amendments_not_merged_by_titles():
    a=event();b=event(accessionNumber='0000000001-25-000002',form='8-K/A')
    assert len(cluster_events([a,b]))==2
    assert b['is_amendment'] and b['original_accession'] is None


def test_canonical_gate_and_safety_remain_authoritative():
    e=event();e['pit_metadata']['replay_safe']=False
    assert not replay_as_of(cluster_events([e]),'2026-10-01T00:00:00Z',basis='historical_source')
    e=event()
    for key in ('broker_truth_eligible','natural_truth_eligible','learning_ack_eligible','automatic_policy_promotion'):
        assert e[key] is False
    assert e['event_type']=='earnings'
    assert event(items='8.01')['event_type']=='sec_material_filing'


def test_cutoff_compares_instants_with_fractional_seconds():
    c=cluster_events([event()])
    assert replay_as_of(c,'2025-09-15T15:00:00.500Z',basis='historical_source')
    assert not replay_as_of(c,'2025-09-15T14:59:59.999Z',basis='historical_source')


def test_cofiled_accession_retains_unsafe_identity_provenance_without_double_count():
    a=event();b=deepcopy(a)
    b.update(record_id='other-issuer',replay_safe=False)
    b['pit_metadata']['replay_safe']=False
    c=cluster_events([b,a])
    assert len(c)==1 and len(c[0]['provenance_records'])==2
    assert c[0]['replay_safe'] is True
    view=replay_as_of(c,'2025-09-16T00:00:00Z',basis='historical_source')
    assert len(view)==1 and len(view[0]['provenance_records'])==1
