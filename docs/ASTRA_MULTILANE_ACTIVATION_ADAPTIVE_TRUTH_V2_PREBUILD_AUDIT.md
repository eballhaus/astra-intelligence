# Astra Multi-Lane Activation Adaptive Truth V2: Prebuild Audit

## Scope and source ownership

The active runtime is the `main` branch at `74da56461361922b3d8e4b25452d352c46d4b008`.
Generated state, caches, diagnostics, snapshots, and local environment files
are deliberately excluded from version control and from this build's staging
set.

| System | Active owner | Status before V2 | Defect to repair |
| --- | --- | --- | --- |
| Runtime environment | `engine/runtime_environment.py` | EXISTS | Lane limits were not configured or bounded against approved ceilings. |
| Candidate freshness | `server_extend.py:_pladeu_candidate_source_metadata_v1` | PARTIAL | Used `TOP_BUYS_TTL_SECONDS` rather than a separate operational age. |
| Lane classification | `engine/astra_trade_lane_registry_v1.py` | EXISTS | Metadata is present; ownership and capital proof were not complete. |
| Paper selection | `PaperAutopilotEngine.per_candidate_decision_trace` | PARTIAL | Status consumers inferred handoff rather than validating authoritative trace fields. |
| DAY session policy | `server_extend.py:_day_lane_pilot_readiness_payload_v1` | BROKEN | Pre- and post-market were treated as order-capable for a regular-hours lane. |
| DAY exit posture | `paper_opportunity_allocation_engine_v1` | PARTIAL | Advisory posture was exposed instead of an explicit authorized worker contract. |
| CRYPTO execution | `PaperAutopilotEngine._crypto_paper_activation_status` | PARTIAL | Existing paper path exists, but capital and lane enablement must be bounded and reported separately from shadow evidence. |
| Strict broker truth | Existing broker truth registry | PARTIAL | Strict counts require paired fills and must remain distinct from legacy diagnostics. |
| Learning delivery | Existing canonical outcome/learning stores | PARTIAL | Need explicit delivery acknowledgement, never a payload-string proxy. |

## Safety classification

The following are safe infrastructure repairs: bounded configuration parsing,
freshness separation, authoritative trace validation, lane ownership
validation, read-only status reporting, strict truth classification, and
focused tests.

Any modification to ranking, entry/exit thresholds, sizing, allocation, live
broker endpoints, learned exits, strategy promotion, or global SWING policy is
outside this build.  The approved DAY and CRYPTO paper lane contracts may only
operate within their owner, capital, session, and paired-fill boundaries.

## Runtime observations

`engine/runtime_environment.py` loads repository `.env` with exported
environment precedence. `start_astra_backend.sh` is the persistent backend
owner and starts the existing paper worker. `start_astra_persistent.sh` routes
the dashboard to the same configured backend port.

The five legacy complete diagnostics do not carry verified entry and exit fill
IDs. They remain diagnostic-only and cannot be counted as strict broker truth.
