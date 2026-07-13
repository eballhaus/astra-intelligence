# Astra Multi-Lane Live Handoff Activation V3 Audit

## Scope

This repair completes the bounded, paper-only handoff from cached candidate
snapshots into the existing `PaperAutopilot` decision boundary for SWING, DAY,
and CRYPTO lanes. It does not alter ranking, entry thresholds, sizing,
allocation, live brokerage access, or learned-exit execution.

## Root Causes

- Candidate snapshots reached lane diagnostics before stable lineage was added,
  leaving executable-path IDs and source fields blank.
- Existing execution diagnostics performed broad status fan-out and broker
  reads, so they were not a suitable zero-action proof source.
- CRYPTO configuration-disabled state was presented as broker capability
  unavailable, and an empty cached ranking set had no explicit operational
  rejection trace.

## Repair Contract

- `PaperAutopilot.operational_dry_run` evaluates a bounded caller-provided
  snapshot and returns a per-candidate trace for both selected and rejected
  rows. It never submits an order or calls a provider/broker endpoint.
- Candidate IDs, recommendation IDs, selection IDs, source, snapshot, lane,
  capital book, position owner, and exit owner are deterministic metadata from
  the existing source snapshot and lane contract.
- DAY produces a `BLOCKED_MARKET_SESSION` trace outside regular hours. That is
  handoff proof, not a pipeline defect.
- CRYPTO uses the existing cached crypto ranking source. When it is empty, a
  bounded `BTC/USD` source probe records
  `NO_CURRENT_CACHED_CRYPTO_RANKING_SIGNAL`; it is explicitly non-tradable and
  excluded from current-candidate counts.
- Capability, configuration, source availability, and paper order-boundary
  availability remain independent status fields.

## Safety Invariants

- All diagnostics are dry-run only: `submit_order=false` and
  `broker_actions_used=0`.
- Paper mode and existing live-endpoint blocking remain authoritative.
- Strict broker truth can only be persisted after actual paired broker fills;
  no diagnostics or fixtures create official truth records.
- Runtime-generated `state/`, `diagnostics/`, logs, caches, snapshots, and
  `.env` are excluded from source control.

## Remaining Evidence Boundary

The runtime can prove lineage and the final paper-order boundary without
submitting trades. Actual strict broker truth and consumer acknowledgements
remain correctly pending until an ordinary, eligible paper round trip receives
both confirmed broker fills. No fixture is counted as live evidence.
