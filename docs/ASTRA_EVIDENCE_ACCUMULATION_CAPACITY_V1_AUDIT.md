# Astra Evidence Accumulation Capacity V1 Audit

## Scope

This audit covers the paper-only evidence reserve repair for the SWING core
book, DAY evidence reserve, and CRYPTO evidence reserve. It does not authorize
orders, exits, strategy changes, or global allocation changes.

## Canonical Ownership Map

| Concept | Authoritative owner | Runtime consumers | Repair status |
| --- | --- | --- | --- |
| Broker position state | Existing Alpaca paper snapshot and PaperAutopilot reconciliation | Capacity contract, lifecycle, reports | Reused; stale or incomplete state fails closed |
| Global capacity | `astra_evidence_accumulation_capacity_v1` | PaperAutopilot, daily report, governance, Copilot | Implemented |
| DAY reserve | Canonical capacity contract, `paper_day_learning` | PaperAutopilot and lane trace | Implemented; bounded to $15,000 and one position |
| CRYPTO reserve | Canonical capacity contract, `paper_crypto_separate` | PaperAutopilot and lane trace | Implemented; bounded to $10,000 and one position |
| SWING allocation | Existing PaperAutopilot and allocator | SWING runtime path | Preserved; reserves excluded |
| Position ownership | Existing lane metadata and lifecycle fields | Trace, reports, portfolio review | Reused; no reclassification |
| Capacity decision | Canonical capacity snapshot and `candidate_capacity_decision` | Allocation gate and trace ledger | Implemented |
| Loss Acceptance | Existing advisory foundation | Portfolio release review | Reused; no execution authority |
| Opportunity cost | Existing advisory diagnostics | Portfolio release review and governance | Reused; no sell-and-replace behavior |
| Portfolio release review | `astra_portfolio_capacity_release_review_v1` | Governance, Copilot, Learning Center payloads | Implemented; advisory only |

## Safe Repair Boundaries

- A lane reserve can bypass only the global position-count blocker when its
  own capital, position, duplicate, and account-risk checks pass.
- Stale broker state, missing buying power, missing position detail, and global
  account risk remain fail-closed conditions.
- Legacy trace summaries are migrated in memory with missing counters added;
  raw trace rows are not rewritten or deleted.
- Portfolio classifications never submit or schedule broker actions.
- Runtime state, broker snapshots, caches, and reports remain untracked.

## Runtime Findings

The persistent worker observed 39 open broker positions and wrote canonical
capacity decisions into its last execution trace. During the closed-session
validation cycle, DAY reserve capacity was available but no order was
submitted; CRYPTO reserve capacity was available for a candidate that did not
pass the remaining session/order gates. This is expected paper-only behavior.

The API process may have only a stale cached broker snapshot. In that case the
capacity endpoint reports the observed count separately and returns
`BROKER_STATE_STALE`; it never treats unavailable details or buying power as
zero and never authorizes a reserve from stale state.

## General Reserve Decision

`GENERAL_EVIDENCE_RESERVE_NOT_REQUIRED`: DAY and CRYPTO have isolated reserves,
so a third general reserve would duplicate ownership and increase accounting
risk without solving the current bottleneck.
