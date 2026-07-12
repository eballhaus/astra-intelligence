# Astra PLadeu Master V1 Pre-Build Audit

## Baseline

- Repository: `/Users/eric/Desktop/astra-intelligence-clean`
- Branch: `main`
- Starting commit: `670b650 Complete Astra master I-L adversarial validation`
- Runtime files under `state/` and `diagnostics/` are generated validation outputs and are excluded from this build's commits.
- Safety baseline: paper-only, advisory-first, no live endpoint, no automatic promotions, and no learned-exit execution.

## Ownership And Planned Action

| Capability | Authoritative owner | Inputs / outputs | Persistence / endpoint / consumers | Maturity and gap | Action | Safety / runtime impact |
| --- | --- | --- | --- | --- | --- | --- |
| Paper entry horizon and lifecycle metadata | `engine/paper_autopilot.py` | candidate -> order -> entry context -> lifecycle | `ai_trading_memory.db`, `trade_lifecycle_v1.jsonl`; broker truth, Copilot, lifecycle audit | Active, but has no canonical lane contract | EXTEND | Metadata-only; no entry-gate change |
| Paper opportunity allocation | `engine/paper_opportunity_allocation_engine_v1.py` | ranked candidates -> allocation decorations | cached payloads; paper autopilot / diagnostics | Active but general-purpose | EXTEND | Explanation and duplicate-exposure diagnostics only |
| Day-trading lifecycle worker | `server_extend.py:_apply_day_trading_lifecycle_rules_v1` | paper mode, day cutoff, active positions | worker heartbeat / lifecycle diagnostics | Active but not an isolated canonical book | CONSOLIDATE | Existing worker is not granted new sell authority |
| Horizon capacity and candidate flow | `server_extend.py:_capacity_lane_diagnostics_v1`, `_horizon_candidate_flow_v1` | cached candidates and broker truth | unified diagnostics, horizon audits | Active, fragmented into helper payloads | REUSE | No quota or capacity-policy mutation |
| Broker truth and lineage | broker-truth registry helpers plus `paper_autopilot.py` attribution | recommendations, orders, fills, lifecycle rows | broker truth registry, candidate decision ledger | Active, low natural round-trip sample | EXTEND | Broker-confirmed truth remains exclusive for official metrics |
| Historical lifecycle reconstruction | None | ledgers, orders, fills, lifecycle and outcome records | Missing dedicated manifest and incremental index | Missing | CREATE | Reconstruction is visibly non-authoritative and bounded |
| Evidence maturity | Build H Warehouse plus Build J active learning | broker, shadow, replay, lifecycle summaries | unified diagnostics, Warehouse, Librarian, Cortex | Active but no single lane-aware ladder | CONSOLIDATE | No cross-class performance aggregation |
| Lifecycle / profit-capture analysis | existing exit, opportunity-cost, MFE/MAE and Build L facades | lifecycle, excursion, exit-readiness, opportunity cost | lifecycle audit, Copilot, Cortex | Active but fragmented | CREATE FACADE | Advisory only, no sell execution |
| Shadow lifecycle retention | `engine/astra_build_j_active_learning_v1.py` | shadow / replay / broker summaries | canonical lifecycle lesson state | Active | REUSE | No destructive retention actions |
| Evidence gaps and teaching effectiveness | `engine/astra_build_j_active_learning_v1.py` | Warehouse, Librarian, effectiveness summary | Learning Center / Build J validation | Active but needs evidence-ladder consumer | EXTEND | Delivery remains distinct from influence |
| Copilot effectiveness | `engine/astra_build_i_decision_intelligence_v1.py` and `_astra_copilot_suite_v1` | canonical recommendation and broker truth | Ask Astra, Copilot, unified diagnostics | Active, linkage sample developing | REUSE | No recommendation behavior change |
| Safe repair and governance | `engine/astra_build_k_safe_repair_governance_v1.py` | cached governance / Warehouse | governance endpoints and unified diagnostics | Active | EXTEND | Repairs remain diagnostic or reversible derived-state only |
| Momentum, exit readiness and loss acceptance | `engine/astra_build_l_research_maturation_v1.py` plus server lifecycle audits | existing lifecycle and exit summaries | Copilot / Cortex / Learning | Active but no canonical satellite contract | CONSOLIDATE | Advisory only |
| Crypto evidence lane | Build L crypto facade and crypto readiness helpers | crypto candidate metadata and shadow summaries | crypto diagnostics / unified diagnostics | Active and separated | REUSE | No crypto execution activation |
| Warehouse / Librarian / Cortex | Build H Warehouse and Tier 2A / Cortex owners | bounded summary indexes and lessons | executive, learning, Ask Astra, governance | Active | EXTEND | Cache-first consumer integration only |

## Duplication Findings

- No existing module exposes the requested `SWING`, `DAY`, and `CRYPTO` pre-trade lane contract, so the contract is a new canonical metadata layer rather than a second allocator or broker path.
- No dedicated, timestamp-valid, confidence-scored historical lifecycle reconstruction owner exists. The new reconstruction engine is required and will not overwrite broker truth.
- Existing day-trading, capacity, exit, shadow retention, active learning, Copilot attribution, safe repair, and crypto systems are retained as authoritative inputs. New endpoints will be facades over them.
- The existing allocation engine remains the only general candidate allocator. Day-lane diversity controls will be added to it as diagnostics, not as a replacement selector.

## Consumer Wiring Target

```text
candidate / ranking
  -> canonical lane contract
  -> existing allocation decoration
  -> existing paper autopilot metadata persistence
  -> broker truth / lifecycle evidence
  -> reconstruction and evidence ladder
  -> lifecycle profit-capture facade
  -> Warehouse / Librarian / Cortex / Copilot / Governance / Learning Center
```

## Known Evidence Blockers

- Official paper performance remains gated by the small broker-confirmed complete lifecycle sample.
- Existing day candidates may be validly rejected by the unchanged safety gates; a daily ceiling will never become a quota.
- Historical reconstruction can increase diagnostic coverage only. It cannot upgrade reconstructed rows into broker-confirmed truth.

## Scope And Consumer Verification

| Capability | Source inputs | Generated outputs | Persistence | Endpoint | Direct consumers | Tests | Current maturity | Duplicate / overlap | Planned action |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Canonical lane contract | candidate horizon metadata, asset class, recommendation identity | `SWING` / `DAY` / `CRYPTO` contract fields | candidate/order JSON, append-only lifecycle rows | `astra_trade_lane_registry_v1` | paper autopilot, allocation, Copilot, lifecycle tracker | `test_trade_lane_registry_contract.py` | Missing prior to build | no prior canonical owner | CREATE |
| Day lane diversity | cached candidates and cached open broker positions | candidate supply, duplicate/cluster review, explanations | none; diagnostic only | `day_trading_paper_learning_lane_v1`, `day_lane_diversity_governor_v1` | allocation diagnostics, Learning Center, governance packet | `test_day_*_contract.py` | Existing day worker, incomplete reporting | allocation was already authoritative | EXTEND |
| Reconstruction | bounded candidate ledger, lifecycle and outcome tails | classified reconstructed/partial/rejected records with lineage | reversible reconstruction manifest only | `historical_lifecycle_reconstruction_v1` | evidence ladder, Warehouse/Librarian/Cortex packet, Learning Center | `test_historical_lifecycle_reconstruction_contract.py` | Missing prior to build | none | CREATE |
| Evidence ladder | reconstruction classes plus Build J shadow evidence | lane-aware maturity tiers and official-truth gate | dashboard cache only | `paper_learning_evidence_ladder_v1` | Learning Center, governance packet, Copilot context | `test_paper_learning_evidence_ladder_contract.py` | Fragmented prior to build | Build J/H evidence summaries | CONSOLIDATE |
| Lifecycle/profit capture satellite | existing lifecycle tracker, exit readiness, turnover, Build L research | ownership-preserving advisory facade | no new authoritative store | `trade_lifecycle_profit_capture_satellite_v1` | Learning Center, governance packet, Copilot context | `test_trade_lifecycle_profit_capture_satellite_contract.py` | Fragmented prior to build | existing exit/research systems remain owners | CREATE FACADE |
| Master/phase validation | all preceding compact summaries | wiring, safety, deferred-evidence result | dashboard cache only | `pladeu_master_validation_v1` | unified diagnostics, governance, final audit | `test_pladeu_master_contract.py` | Missing prior to build | no competing validator | CONSOLIDATE |

All new reads are bounded to 300 candidate rows, 100 cached positions, and 250 rows / 1 MB per reconstruction source. Runtime files remain excluded from source control.
