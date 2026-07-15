# Astra Candidate Intelligence Enrichment V1 Audit

## Active ownership

| Concept | Canonical owner | Runtime consumer | Repair |
| --- | --- | --- | --- |
| Candidate normalization | `engine.paper_autopilot.normalize_operational_candidate` | PaperAutopilot and certification | Preserved identity-only normalization. |
| Candidate enrichment | `engine.astra_premarket_certification_v1.enrich_candidate_for_pretrade_contract` | PaperAutopilot trace and certification | Added as the only active enrichment owner. |
| Decision contract | `build_pretrade_decision_contract` | Existing qualification and order-ready gate | Builder now invokes the canonical enrichment owner if needed. |
| Qualification and order readiness | `PaperAutopilot._candidate_trace_row` | PaperAutopilot | Preserved existing gates; consumes the enriched contract. |
| Candidate diagnostics | `candidate_intelligence_enrichment_contract_diagnostic_v1` | Governance/read-only clients | Added bounded dry-run visibility only. |

## Evidence contract

The precedence order is current candidate direct, current symbol direct, current
context direct, historical/reconstructed, replay, shadow, aggregate advisory,
then explicit bounded policy defaults. Lower-tier evidence cannot overwrite a
candidate-local value. Every populated plan field carries source system, source
field, timestamp, evidence class, confidence, freshness, symbol/candidate scope,
and derived status in `field_provenance_v1`.

## Bounded sources

The enrichment owner accepts only caller-supplied, bounded cached packets. The
certification adapter uses existing ranking rows, paper opportunity allocation,
opportunity discovery, and edge-development decorations. Replay, shadow, and
aggregate stores remain separately labeled and cannot become broker-confirmed
truth. No provider, broker, LLM, or full-history operation is performed.

## Safety

The implementation is side-effect free. It does not change ranking, selection,
thresholds, sizing, capital allocation, capacity, exits, or broker behavior.
Incomplete or conflicting contracts remain fail-closed before the existing order
boundary. The diagnostic endpoint performs an operational dry run with
`submit_order=false` and `broker_actions_used=0`.
