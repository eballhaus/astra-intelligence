# Astra Point-in-Time Metadata Normalization V1

Generated 2026-09-20. Read-only normalization and validation. No provider downloads, source-archive rewrites, worker restart, broker action, or runtime-state mutation occurred.

## A. Canonical PIT Contract

Implementation owner: `engine/astra_pit_metadata_contract_v1.py` (`normalize_historical_record`, `replay_readiness`, `require_replay_safe`).

The helper returns additive metadata with:

- `schema_version`, deterministic `record_id`, `dataset_type`, `symbol`, `asset_class`
- `event_time`, `publication_time`, `provider_observed_time`, `available_to_astra_time`
- `ingested_at`, `stored_at`, provider/endpoint/file/provenance fields
- `timezone`, `timestamp_precision`, `original_timestamp_fields`
- `point_in_time_status`, `lookahead_risk`, `replay_safe`, and `replay_safe_reason`
- `normalization_method` and `normalization_confidence`

The helper never overwrites the input mapping. It does not use `ingested_at` as event time, does not use period end as availability, and does not mark a record replay-safe when publication/availability is missing. `require_replay_safe` raises `UnsafeReplayRecord` for any non-safe record.

Dataset rules:

| Dataset | Event time | Publication/provider time | Availability rule | Safe default |
|---|---|---|---|---|
| Market bars | Explicit bar end/event timestamp; validated completed-bar context required | Provider-native timestamp when present | Explicit completion/as-of timestamp or validated completed-bar contract | Fail closed without completion evidence |
| SEC filings | Period/event date | EDGAR accepted/filing timestamp | Accepted/filing timestamp | Fail closed without filing timestamp |
| Fundamentals | Period end | `acceptedDate`/filing timestamp | Filing/publication timestamp; never period end | Fail closed when filing time absent |
| Earnings | Earnings event/date | Release/publication timestamp | Release/publication timestamp | Fail closed when release time absent |
| Macro/FRED | Observation/reference period | Release, vintage, or realtime timestamp | Vintage/release timestamp | Fail closed without vintage/release time |
| Corporate actions | Effective/action date | Announcement/publication timestamp | Announcement/publication timestamp | Partial unless both sides are preserved |
| News/catalyst | Underlying event time | `published_at`/provider publication timestamp | Publication/provider timestamp | Fail closed without publication time |
| Feature/forecast snapshot | Source/as-of timestamp | Source/provider timestamp | Explicit as-of/availability timestamp | Fail closed without as-of evidence |

Statuses are exactly `POINT_IN_TIME_SAFE`, `PARTIALLY_POINT_IN_TIME`, `CURRENT_SNAPSHOT_ONLY`, `TIMESTAMP_INSUFFICIENT`, and `UNKNOWN`. Replay admission requires both `POINT_IN_TIME_SAFE` and `replay_safe=true`.

## B. Dataset-by-Dataset Mapping

| Dataset | Existing fields observed | Normalized result | PIT classification |
|---|---|---|---|
| Equity daily | `ts`, `o/h/l/c/v`, `provider`, `ingested_at` | Event/ingestion can be mapped; completion/availability and adjustment vintage are not per-row | Partial; replay-safe only with validated archive context |
| Equity intraday | `ts`/`timestamp`, provider-native timestamp in raw context, `ingested_at`, validated archive windows | Completed-bar context can deterministically supply availability for validated 1m/5m/15m archives | Safe for declared validated subsets; 1h remains partial due progress inconsistency |
| ETF | Same bar fields plus FMP ETF profile/action context | Same bar adapter; profile/action records use their own event/publication rules | Partial overall; declared validated intraday subsets safe |
| Crypto bars | `ts`, provider, `ingested_at`, canonical pair aliases, replay-only manifest | Completed-bar adapter; never natural-truth eligible | Safe only for validated 1m/5m subsets; 1h partial, 1d unavailable |
| Macro/FRED | Derived Phase 2 `source_timestamp`, reference/value context; FRED ownership contract | Source/as-of only unless release/vintage is present | Partial/unsafe for causal replay without vintage |
| SEC/EDGAR | `cik`, normalized facts, `retrieved_at`; sampled `filing_provenance` is empty | Period can be separated from publication only where accepted/filing time exists | Partial; sampled Phase 2 context fails closed |
| Fundamentals | FMP `date`, `period`, `acceptedDate`, `filingDate`, `retrieved_at` | Period end separated from filing time | Partial; records with accepted timestamp can normalize safely |
| Earnings | `date`, `lastUpdated`, actual/estimated values, `retrieved_at` | Event date is preserved; `lastUpdated` is not treated as release time | Partial; future calendar rows without release time fail closed |
| Corporate actions | `date`, `declarationDate`, `recordDate`, `paymentDate`, `retrieved_at` | Effective/action date preserved separately from declaration/publication | Partial |
| News/catalyst | No historical archive; current/advisory catalyst rows | Adapter exists but no source records are available | Missing; external data required |
| Analyst estimates | No PIT adapter or archive | No records to normalize | Missing; external data required |
| Options/volatility | Realized-volatility proxy only; no historical option-chain fields | Proxy remains distinct from IV/skew/OI | Missing for options history; external data required |
| Short/ownership | No historical time-series fields | No records to normalize | Missing; external data required |
| Execution/microstructure | Phase 2 OHLCV proxy, `quote_data=NOT_AVAILABLE` | Proxy is marked replay-only and not upgraded to quote truth | Partial; true quote/trade data requires external archive |
| Historical feature/forecast | `source_timestamp`, feature value, provenance, `historical_replay_only`, `lookahead_rejected` | Explicit source/as-of mapping; no inferred publication | Partial |

## C. Normalized Datasets

Five declared archive subsets are deterministically normalizable as safe when the existing validation contract is supplied:

1. Equity 1-minute FMP archive, 300 symbols.
2. Equity 5-minute FMP archive, 100 symbols.
3. Equity 15-minute FMP archive, 300 symbols.
4. Crypto 1-minute FMP replay archive, 4 pairs.
5. Crypto 5-minute FMP replay archive, 8 pairs.

The historical evidence producer now attaches `pit_metadata` to each bounded replay evidence item. Compression admits only records whose normalized metadata is safe. This is an on-demand normalization path; no duplicate normalized archive was written.

## D. Partially Normalized Datasets

Eleven dataset groups have deterministic mappings for some records but not all: equity daily, equity 1-hour, ETF overall, crypto 1-hour, macro/regime, SEC/EDGAR, fundamentals, earnings, corporate actions, execution/microstructure proxies, and feature/forecast snapshots. Their original fields remain authoritative and records without availability proof remain rejected for causal replay.

## E. Replay-Unsafe Datasets

Five dataset groups remain unavailable or unsafe for causal replay because the historical source itself is absent: news/catalyst, analyst revisions, options/IV/skew/OI, short/ownership time series, and crypto specialized institutional metrics. The existing microstructure proxy is also not equivalent to true quote/trade history and is advisory/replay-only.

## F. Anti-Lookahead Rules Implemented

- A record must have explicit or contract-proven availability before it can be replay-safe.
- Event time is never substituted for publication or availability time.
- Ingestion/storage time is retained but never promoted to event time.
- Period end is never treated as filing/publication time.
- A bar needs explicit or validated completed-bar evidence; incomplete/future bars fail closed.
- Release/vintage time is required for causal macro/FRED use.
- News requires provider publication time.
- `replay_readiness` produces an explicit admission decision; `require_replay_safe` raises on unsafe records.
- Original timestamp fields remain under `original_timestamp_fields`.
- Replay, shadow, counterfactual, and natural broker truth remain separate.

## G. Validation Samples

- Validated 5-minute market-bar sample: `POINT_IN_TIME_SAFE`, replay-safe when `completed_bar_proven=true`.
- SEC Phase 2 sample: `filing_provenance={}` and no accepted/filing timestamp in the normalized record; `TIMESTAMP_INSUFFICIENT`, replay rejected.
- FMP fundamentals sample: `date=2026-06-30` and `acceptedDate=2026-07-23 07:02:13`; period and filing time are separated and can be normalized.
- FMP earnings sample: `date=2026-10-22` with no release timestamp; replay rejected rather than treating `lastUpdated` as publication.
- Macro sample with explicit observation date but no vintage/release: replay rejected. A sample with `vintage_timestamp` is safe.
- News sample with event time but no publication time: replay rejected.
- Existing intraday historical evidence tests verify future-window exclusion and completed-window behavior.

## H. Counts and Coverage

Counts are dataset-level plus bounded source estimates; no normalized sidecar was written, so overlapping compressed context and canonical DB rows are not falsely summed as independent records.

- Safe datasets: 5 declared archive subsets.
- Partially normalized datasets: 11.
- Replay-unsafe datasets: 5 missing historical source groups.
- `POINT_IN_TIME_SAFE` record estimate: approximately 8,166,526 validated 1m/5m/15m bar rows across the declared equity/crypto subsets; estimate only, not a new archive.
- `PARTIALLY_POINT_IN_TIME` record estimate: approximately 19,072,783 canonical daily/1-hour bar rows lacking uniformly materialized per-row availability/completion metadata; overlapping derived rows excluded.
- `TIMESTAMP_INSUFFICIENT`: exact global count not materialized; representative SEC, earnings, macro, news, feature, and raw-bar records are explicitly classified and fail closed where availability is absent.
- `CURRENT_SNAPSHOT_ONLY`: no historical archive-wide count; profile/current-context records without event history are classified this way by the adapter when source context marks them current-only.
- `UNKNOWN`: no archive-wide count; reserved for records with no usable timestamp fields at all.
- Replay-safe coverage is measurable only for the validated bar subset: approximately 8.17M of 27.24M canonical market-bar rows, or about 30.0%, before excluding overlaps and before any new materialized sidecar. This is an estimate of source-contract coverage, not a claim that all records were rewritten.

## I. Remaining Metadata Gaps

- SEC Phase 2 normalized rows need accepted/filing timestamps and non-empty filing provenance where available.
- FRED raw release/vintage records are not locally archived.
- Earnings records need release timestamps distinct from event dates and provider update dates.
- Corporate actions need explicit announcement/publication timestamps distinct from effective dates.
- Existing 1-hour archive progress metadata must be reconciled with its validation result.
- Daily bars need a documented bar-completion/availability contract and adjustment-vintage linkage.
- Feature snapshots need explicit `available_to_astra_time` rather than only `source_timestamp`.

## J. External Data Required

Normalization cannot create historical facts absent from Astra. New external historical data is required for timestamped news/catalysts, point-in-time analyst revisions, option chains/IV/skew/OI, short/ownership time series, crypto funding/open interest/liquidations/basis/on-chain metrics, and true quote/trade/SIP/NBBO history.

## K. Recommended Next Acquisition Phase

First perform a metadata-only repair over existing SEC/FMP/FRED-compatible records and reconcile 1-hour archive completion metadata; only then acquire one narrowly scoped historical catalyst and true quote/trade cohort if replay requirements still show a material gap.

## Change and Safety Record

- Files changed: `engine/astra_pit_metadata_contract_v1.py`, `engine/astra_historical_evidence_production_v1.py`, `tests/test_astra_pit_metadata_contract_v1.py`, and the three requested report artifacts.
- Trading, risk, sizing, capacity, entry, exit, forecast, truth, learning, and reconciliation logic: unchanged.
- Worker/runtime state: unchanged; no restart.
- Broker actions, forced orders/exits, and live trading changes: 0.
