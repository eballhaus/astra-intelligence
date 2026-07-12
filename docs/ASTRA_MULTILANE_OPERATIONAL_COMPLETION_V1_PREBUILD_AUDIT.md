# Astra Multi-Lane Paper Trading Operational Completion V1

## Scope

This completion work reuses the existing ranking cache, `AstraTradeLaneRegistryV1`,
`PaperOpportunityAllocationEngineV1`, `PaperAutopilot`, Alpaca paper client, and
broker-truth registry. It adds no execution owner and does not alter ranking,
entry, exit, sizing, allocation, or broker behavior.

## Authoritative Owners

| Function | Owner |
| --- | --- |
| Candidate generation | Existing ranking/top-buys cache |
| Lane and instrument contract | `AstraTradeLaneRegistryV1` |
| Allocation | `PaperOpportunityAllocationEngineV1` |
| Actual selection | `PaperAutopilot.per_candidate_decision_trace` |
| Paper-order handoff | Existing `PaperAutopilot` action path |
| Broker client | Existing Alpaca paper broker |
| Completed truth | Existing `broker_truth_records_v1` registry |
| Reconstruction | `AstraHistoricalLifecycleReconstructionV1`, diagnostic only |

## Root Causes Addressed

- ETF metadata was represented as an asset class in some paths. The canonical
  contract now uses `asset_class=equity` and `instrument_type=ETF`; ETF remains
  a cohort within DAY or SWING, never a lane.
- DAY's old `selected_day_candidates` was a diagnostic allocation result. The
  readiness payload now exposes `diagnostic_selected_day_candidates` separately
  from `actual_selected_day_candidates`, owned by the autopilot trace.
- Crypto aggregate raw records were capable of being interpreted as completed
  truths. Strict lane-scoped truth now requires `BROKER_CONFIRMED_COMPLETE` plus
  both entry and exit fill identifiers.
- Existing lane operational evidence was distributed across unrelated endpoint
  payloads. `/api/multilane_paper_operational_status_v1` consolidates the bounded
  operational stages without refreshing providers or invoking brokers.

## Human Configuration Boundaries

DAY remains safely blocked until a human configures `ASTRA_DAY_LANE_CAPITAL_LIMIT`
and enables `ASTRA_DAY_LANE_PILOT_ENABLED`. Crypto remains `SHADOW_ONLY` until its
existing broker capability and `ASTRA_CRYPTO_PAPER_CAPITAL_LIMIT` are verified.
No configuration is written by this build.

## Evidence Boundary

The current legacy broker registry has five records labeled
`broker_confirmed_complete`, but its stored rows contain only an exit-side
`fill_id`, not paired entry and exit fill identifiers. They remain visible as
legacy broker-complete diagnostics but are excluded from the new lane-scoped
strict truth totals. This is an evidence-lineage limitation, not a fabricated
completion: future paper entries must persist both fill identifiers before they
qualify for lane-scoped learning.

## Safety

The status endpoint and all simulations are read-only: `submit_order=false`,
`broker_actions_used=0`, provider calls are zero, and fixture truth is excluded
from official broker-truth totals.
