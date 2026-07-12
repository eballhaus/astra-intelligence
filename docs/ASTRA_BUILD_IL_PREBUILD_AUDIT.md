# Astra Build I-L Pre-Build Audit

Date: 2026-07-11

This audit is intentionally source- and index-first. It does not recursively
scan runtime state or diagnostics content.

## Canonical Owners

| Capability | Canonical owner | Classification | Build action |
| --- | --- | --- | --- |
| Bounded knowledge retrieval and lineage | `engine/astra_knowledge_warehouse_v1.py` | COMPLETE_AND_ACTIVE | Reuse for every new read path. |
| Copilot recommendations | `server_extend.py:_astra_copilot_suite_v1` | COMPLETE_AND_ACTIVE | Keep as the single recommendation authority. |
| Ask Astra answer path | `server_extend.py:ask_astra_v1` and `_ask_astra_context_compression_v1` | ACTIVE_BUT_WEAK | Add deterministic route/lineage diagnostics without replacing response generation. |
| Broker truth accounting | `engine/astra_paper_provider_cortex_completion_v1.py` and `broker_truth_records_v1` | ACTIVE_BUT_WEAK | Add linkage/completeness scorecards; never fabricate history. |
| Copilot outcome attribution | `server_extend.py:_de_copilot_effectiveness_v1_payload` | PARTIALLY_WIRED | Extend attribution and evidence gating through one v2 facade. |
| Shadow experiment governance | `engine/astra_shadow_experiment_governance_v1.py` | COMPLETE_AND_ACTIVE | Reuse for retention, promotion, and shadow-only safeguards. |
| Replay and counterfactual learning | `engine/replay_counterfactual_learning_v2.py` | COMPLETE_AND_ACTIVE | Reuse for bounded multi-horizon research. |
| Crypto shadow learning | `engine/crypto_shadow_learning_v1.py` | DIAGNOSTIC_ONLY | Keep separately labelled from equity broker truth. |
| Autonomous governance | `engine/astra_autonomous_optimization_governance_core_v1.py` | ACTIVE_BUT_WEAK | Add safe repair plans and rollback evidence, not trading controls. |
| Horizon/capacity diagnostics | `engine/astra_horizon_lifecycle_capacity_promotion_readiness_bundle_v1.py` | COMPLETE_AND_ACTIVE | Consume only as research/advisory evidence. |

## Active Call Paths

* Ask Astra: request -> `ask_astra_v1` -> cached unified/Copilot context ->
  structured fallback or optional user-triggered local Qwen wording.
* Copilot: cached state -> `_astra_copilot_suite_v1` -> dashboard, Ask Astra,
  and attribution helpers.
* Broker truth: broker-derived registry -> canonical outcome audit -> Paper
  performance summaries. Replay and shadow evidence remain separately labelled.
* Build H warehouse: bounded summary/index reads -> lineage-bearing retrieval ->
  diagnostic consumers.

## Duplicated or Incomplete Responsibilities

* Ask Astra has several question-specific response branches, but no explicit
  canonical route record or per-answer source-state contract.
* Existing Copilot attribution declares recommendation-to-outcome linkage
  unavailable; it correctly avoids inventing results but lacks a consolidated
  v2 scorecard and disagreement analysis.
* Broker truth has maturity guards and forward-capture safeguards, but needs a
  compact root-cause/completeness presentation for the Build I contract.
* Existing shadow, replay, governance, and crypto modules expose diagnostics;
  their lifecycle compression, learning-gap, repair, and research conclusions
  are not yet tied together through a bounded Build I-L facade.

## Existing Test and Endpoint Coverage

* `tests/test_build_h_contract.py` covers warehouse ownership, bounded reads,
  and Build H safety contracts.
* Existing endpoints include `/api/ask_astra_v1`, `/api/ask_astra_status_v1`,
  `/api/broker_truth_accumulation_v2`, `/api/copilot_effectiveness_attribution_v1`,
  `/api/replay_counterfactual_learning_v2`, and `/api/crypto_shadow_learning_v1`.
* Build I-L will add focused contract tests that use isolated fixture state and
  do not read or write live runtime records.

## Current Constraints and Expected Outcomes

* Complete broker-confirmed lifecycles are below the maturity threshold, so
  paper performance claims must remain `WARMING_UP` or deferred.
* Shadow coverage is substantial but remains observational until repeatability,
  broker linkage, and human review conditions are satisfied.
* All new endpoints must use cached/index-first source summaries, report zero
  provider, broker-action, and dashboard LLM calls, and preserve paper-only,
  advisory-only behavior.
