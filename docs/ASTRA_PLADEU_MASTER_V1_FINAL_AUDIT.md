# Astra PLADEU Master V1 Final Audit

## Final Status

`ASTRA_PLADEU_MASTER_PASS_WITH_DEFERRED_EVIDENCE`

The implementation, consumer wiring, safety checks, bounded-read runtime path,
and focused regression suite passed. The remaining limits are natural evidence
limits, not code or safety failures.

## Authoritative Ownership And Wiring

| Concern | Authoritative owner | PLADEU action | Consumer proof |
| --- | --- | --- | --- |
| Candidate allocation | `PaperOpportunityAllocationEngineV1` | Extended with a diagnostic DAY-lane governance view; no second allocator | `day_lane_diversity_governor_v1` reads the allocator's decorated candidates and governance report |
| Paper entry | `PaperAutopilotEngine` | Carries the pre-trade lane contract into its existing request/context path | contract is added before the existing submission call; broker payload strips unknown metadata rather than changing broker behavior |
| Lifecycle truth | `trade_lifecycle_tracker` | Preserves lane metadata in append-only lifecycle rows | `create_lifecycle_record` and `update_lifecycle_progress` retain the contract |
| Broker truth | Existing Alpaca/broker-truth owners | Preserved as the only source eligible for official performance | reconstruction marks all reconstructed records `official_performance_eligible=false` |
| Historical reconstruction | `AstraHistoricalLifecycleReconstructionV1` | New, bounded diagnostic owner because no equivalent existed | evidence ladder and master validator consume its explicit classes |
| Exit and profit capture | Existing exit-readiness, turnover, Build L owners | Consolidated through an advisory satellite facade | satellite exposes source owners and keeps learned-exit execution disabled |
| Learning / governance / executive consumers | Unified diagnostics, existing Warehouse/Librarian/Cortex/Governance | Receives an advisory packet only | unified payload has the PLADEU statuses and consumer packet |
| Copilot | Existing `_astra_copilot_suite_v1` | Enriched with canonical lane/context fields only | `lane_id`, cohort, intended horizon and capital-book metadata are display context, not recommendation inputs |

## Adversarial Checks And Repairs

| Check | Result | Repair where required |
| --- | --- | --- |
| Duplicate general allocator | Pass | Reused `PaperOpportunityAllocationEngineV1`; the governor is a facade over it. |
| Duplicate lifecycle / exit owner | Pass | Satellite documents existing owners and adds no execution path. |
| Symbol-only reconstruction | Pass | Rejected; no stable identifier produces `AMBIGUOUS_REJECTED`. |
| Reconstructed evidence in official PF | Pass | Only `BROKER_CONFIRMED_COMPLETE` is marked official-performance eligible. |
| Legacy intraday lane inference | Repaired | Added `trade_horizon_style` and `best_horizon_style` to canonical style inference. |
| Endpoint cache path | Repaired | Removed unnecessary Build I-L composition and forced cache rebuilding from normal PLADEU GETs. |
| Render-time provider, broker, LLM or full-history calls | Pass | All PLADEU endpoint payloads report `0`; reconstruction reads 250 rows / 1 MB per source. |
| Day-lane quota behavior | Pass | `ceiling_is_not_a_quota=true`; zero qualifying trades is explicitly valid. |
| Swing / day / crypto evidence mixing | Pass | Separate lane classes; crypto remains its own lane and reconstructed evidence is non-authoritative. |
| Silent degraded PASS | Pass | The evidence ladder is `warming_up` and final status is deferred-evidence rather than an unqualified PASS. |

## Runtime Results

Normal cached endpoint latency after the cache repair:

| Endpoint | Measured latency |
| --- | ---: |
| `astra_trade_lane_registry_v1` | 0.590 s |
| `day_trading_paper_learning_lane_v1` | 0.098 s |
| `historical_lifecycle_reconstruction_v1` | 1.085 s |
| `paper_learning_evidence_ladder_v1` | 0.114 s |
| `trade_lifecycle_profit_capture_satellite_v1` | 0.568 s |
| `pladeu_master_validation_v1` | 0.049 s |

The historical reconstruction endpoint is intentionally the slowest because it
performs bounded local lineage inspection. It performs no full-history scan,
provider request, broker action, or LLM call.

## Observed Evidence

- Candidate lane registry: 14 `DAY`, 6 `SWING`, 0 `CRYPTO`; active cached
  positions had no lane-labelled open rows at validation time.
- DAY diagnostic lane: 14 candidates, 14 eligible, 0 existing selections;
  the lane is disabled for execution and same-session close remains advisory.
- Reconstruction inspected 750 bounded rows, linked 21 medium-confidence
  reconstructed lifecycles, and rejected 500 ambiguous records. It reported
  zero broker-confirmed complete records, zero lane conflicts, zero asset-class
  conflicts, and zero timestamp conflicts.
- Evidence ladder: 0 broker-truth round trips, 21 reconstructed context rows,
  and `NO_EVIDENCE` broker-truth maturity for DAY, SWING, and CRYPTO.

## Validation Evidence

- Python: `compileall` passed for `engine`, `server_extend.py`, and `tests`.
- Tests: 34 focused PLADEU and Build H-L / master I-L contract tests passed.
- Frontend: `npm run build` passed. Vite emitted its existing large-chunk
  warning only.
- Service restart: backend and frontend both started; `/api/health` returned
  HTTP 200.
- Endpoint smoke: all required PLADEU and reused Build J-L endpoints returned
  valid JSON and HTTP 200. Unified diagnostics reported
  `failed_sources_count=0` and `initial_learning_tab_endpoint_count=1`.
- Browser: Dashboard, Learning Center, and Copilot rendered successfully; the
  Learning Center contained the collapsed PLADEU panel and both pages had zero
  browser console errors.

## Safety Proof

Every new PLADEU endpoint reports:

- `behavior_safe_to_apply=false`
- `paper_mode_verified=true`
- `broker_live_endpoint_allowed=false`
- `automatic_promotion_enabled=false`
- `learned_exit_execution_enabled=false`
- `human_review_required=true`
- provider, broker-action, LLM, and full-history scan counts of zero

No ranking, entry, exit, sizing, allocation, capacity, broker, paper-execution,
or live-trading policy was changed. The only paper-autopilot change is durable
lane metadata propagation along its existing entry/lifecycle path.

## Deferred Evidence And Human Decisions

1. Broker-confirmed complete round trips are currently zero; no official
   performance, exit, or promotion claim is available.
2. DAY entries and completed DAY lifecycles must accumulate naturally under the
   existing safety gates before day-specific performance can be evaluated.
3. Crypto remains separate and needs independent eligible lifecycle evidence.
4. Automatic same-session close, learned-exit activation, promotion, ceilings,
   and any policy changes remain human-approval decisions.

## Runtime File Policy

Validation regenerated data under `state/` and `diagnostics/`. Those files are
runtime artifacts and are explicitly excluded from this build's commit.
