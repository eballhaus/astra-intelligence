# Astra Controlled DAY-Lane Pilot Activation V1 Prebuild Audit

## Exact blocker for eligible-to-selected

The DAY diversity endpoint's `selected_day_candidates` is a diagnostic count derived from candidate row fields (`selected` or `paper_ready`). It is not the paper-autopilot selection counter and does not submit orders. The existing allocator is intentionally advisory (`day_lane_execution_enabled=false`) and the explicit pilot switch is off.

The live paper-autopilot trace independently records `market_open_cycle_detected=false` and `final_blocker_reason=session_order_submission_blocked` during the observed weekend/closed-market cycle. Therefore no candidate was allowed to reach the paper-order boundary. This is a valid safety block, not a missing trade quota.

## Candidate path

The authoritative path remains:

`bounded top-buys snapshot -> lane decoration -> PaperOpportunityAllocationEngineV1.day_lane_governance() -> existing PaperAutopilotEngine gates -> paper order boundary`.

The new readiness payload adds a bounded `candidate_stage_trace` with candidate ID, symbol, lane, cohort, eligibility, allocation, diversity, duplicate, capital, session, selection, autopilot result, and exact blocker. It does not create a second allocator.

## Controlled pilot contract

The pilot is explicit and disabled by default. It uses `ASTRA_DAY_LANE_PILOT_ENABLED` and `ASTRA_DAY_LANE_PILOT_DISABLE_SWITCH`; capital is not inferred and requires `ASTRA_DAY_LANE_CAPITAL_LIMIT`. Initial limits are one open DAY position and two completed DAY trades per session. Regular-hours-only, no overnight, exact cross-lane duplicate blocking, same-session exit requirement, rollback readiness, and human approval are explicit.

`/api/day_lane_pilot_control_status_v1` is read-only. It exposes `activation_mutation_endpoint=None`, zero broker actions, and does not enable the pilot.

## Same-session ownership repair

The existing DAY lifecycle worker now filters to rows with both `lane_id == "DAY"` and `same_session_exit_required is True`. SWING, CRYPTO, manual, and legacy rows remain untouched. Natural-exit preservation remains unchanged.

## Broker truth and learning

No new broker-truth owner was introduced. Only actual paper fills can create authoritative broker truth. Reconstruction remains bounded diagnostic evidence and remains excluded from official broker metrics. Consumer notification remains cache/background-owned; dashboard GETs perform zero broker/provider/LLM actions.

## Remaining human approval

Pilot activation is not complete until a human configures an approved capital limit, explicitly enables the pilot through configuration, and reviews the readiness/control status during a regular tradable session. No code path activates it automatically.
