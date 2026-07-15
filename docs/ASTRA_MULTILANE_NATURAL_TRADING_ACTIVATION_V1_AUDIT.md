# Astra Multi-Lane Natural Trading Activation V1 Audit

## Canonical Owners

| Concern | Canonical owner | Runtime store / join key | Consumer |
| --- | --- | --- | --- |
| Candidate identity and lane contract | `engine/astra_trade_lane_registry_v1.py::apply_trade_lane_contract` | `candidate_id`, `recommendation_id`, `lane_id`, `symbol` | PaperAutopilot, certification, trace ledger |
| Candidate enrichment and decision contract | `engine/astra_premarket_certification_v1.py::enrich_candidate_for_pretrade_contract` | normalized candidate identity and candidate snapshot | PaperAutopilot and pre-market certification |
| Qualification, selection, and paper submission | `engine/paper_autopilot.py::PaperAutopilot` | `per_candidate_decision_trace` | existing approved paper worker only |
| Session, capital, lane activation, and strict truth envelope | `engine/astra_multilane_activation_v2.py` | lane ID, capital-book ID, paired fill IDs | PaperAutopilot and runtime status |
| ETF cohort identity | `engine/astra_trade_lane_registry_v1.py` | authoritative candidate/broker metadata, then existing canonical ETF registry | lane attribution and performance reports |
| Capacity and reserve decision | `engine/astra_evidence_accumulation_capacity_v1.py::build_capacity_snapshot` | capacity snapshot ID, lane ID, symbol | allocator, PaperAutopilot, reports |
| Execution observation | `engine/lane_execution_trace_ledger_v1.py` | candidate/recommendation/symbol trace identity | daily report and Governance |
| Market-hours audit schedule | existing `PaperAutopilot` worker cycle plus FastAPI startup hook | bounded runtime audit registry | Governance, Action Center, mobile consumers |
| Broker truth registry | `state/broker_truth_records_v1.json`, written only after paired paper fills | entry/exit fill IDs, lifecycle ID, stable key | strict truth and natural attribution |

## Repair Boundaries

The market-hours audit observes existing worker traces only. It does not call a
provider or broker, submit/cancel/close an order, change qualification, or
mutate a broker record. ETF remains an equity asset class with `ETF` as the
instrument/performance cohort. Strict natural performance accepts only a
paired-fill record carrying its matching `NATURAL_PAPER_*` lane/cohort label.

## Remaining Evidence Limitation

Candidates without an existing current downside/risk-envelope source remain
`CONTRACT_INCOMPLETE`. This is intentional fail-closed behavior, not a reason
to lower qualification or synthesize a risk range.
