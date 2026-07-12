# Astra Broker Truth and Day-Lane Reconciliation V1

## Ownership

| Concern | Authoritative owner | Classification rule | Current scope/count |
| --- | --- | --- | --- |
| Platform broker truth | `state/broker_truth_records_v1.json`, normalized by `server_extend.py::_canonical_broker_truth_counts_v1` | `truth_quality == broker_confirmed_complete` (or the normalized closed + realized-P/L fallback) | 5 complete records; 97 broker records total |
| Canonical outcome audit | `server_extend.py::_canonical_outcome_audit_v1` | Consumes the broker registry and keeps advisory/lifecycle rows separate | 5 broker-linked outcomes |
| Historical lifecycle reconstruction | `engine/astra_historical_lifecycle_reconstruction_v1.py` | Stable identifier joins across bounded local lifecycle sources; symbol-only joins rejected | Newly reconstructed records only; not platform-wide broker truth |
| Paper evidence ladder | `engine/astra_pladeu_master_v1.py::PaperLearningEvidenceLadderV1` | Uses the authoritative broker count supplied by the truth owner | Broker tier reports 5, while reconstructed context remains diagnostic |
| Current DAY candidate feed | `_cached_candidate_rows_for_horizon_flow_v1()` | Bounded top-buys runtime snapshot, freshness-qualified | Current rows only when the cache is fresh; stale rows are historical/contextual |
| DAY pilot readiness | `server_extend.py::_day_lane_pilot_readiness_payload_v1` | Reuses `PaperOpportunityAllocationEngineV1.day_lane_governance()` and reports blockers | Pilot remains disabled and human-gated |

## Why five and zero disagreed

The five authoritative records live in the broker-truth registry and are produced by the broker-truth normalization path. Reconstruction reads only bounded tails of candidate, lifecycle, and outcome files. Those files did not contain explicit `BROKER_CONFIRMED_COMPLETE` rows, so reconstruction correctly returned zero records in that class. The old field name made that scoped result look like a platform-wide count.

The repair now exposes `authoritative_broker_confirmed_complete_count` separately from `newly_reconstructed_complete_count`, with `authoritative_truth_source` and `reconstruction_scope` on the reconstruction payload. Reconstructed rows are never promoted into the broker registry.

## DAY candidate semantics

The prior 14 DAY / 6 SWING figures came from the PLADEU audit summary/cache-era diagnostic snapshot, not a current selected-paper feed. The live bounded top-buys snapshot is the candidate source for current diagnostics. The DAY payload now separates classified, current, eligible, selected, rejected, open, and completed counts and includes cache age/freshness and market-session state. When the source is stale or absent, those rows are reported as historical/contextual rather than current pilot candidates.

## Candidate-to-paper path

The existing path remains authoritative:

`bounded candidate snapshot -> lane decoration -> day_lane_governance() -> existing eligibility/selection owners -> paper-autopilot handoff boundary`.

The readiness endpoint is diagnostic-only. It does not submit orders, activate the DAY lane, change ceilings, or bypass duplicate, sector, correlation, broker, or paper-safety gates. A missing live handoff trace is an explicit blocker rather than a false PASS.

## Safety

The repair preserves paper-only mode, `behavior_safe_to_apply=false`, `broker_live_endpoint_allowed=false`, `automatic_promotion_enabled=false`, `learned_exit_execution_enabled=false`, `human_review_required=true`, and zero provider, broker, and LLM actions during GET rendering.
