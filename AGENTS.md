# Astra Codex Operating Contract

## Mission

Astra is a PAPER-only, evidence-driven, multi-lane trading research and
automation platform. Engineering work must preserve reliable end-to-end
operation, correct truth and learning, measurable improvement, and safe,
bounded autonomy.

## Paper-Only Safety

- Never enable live trading.
- Never force or fabricate trades, entries, exits, candidates, fills, broker facts, P&L, MFE/MAE, truths, evidence, learning, or performance.
- Never loosen entry, exit, risk, sizing, capacity, freshness, session, reconciliation, or truth requirements to create activity or make a test pass.
- Keep Shadow, replay, hypothetical, and counterfactual evidence separate from broker truth and natural strict truth.
- Uncertainty fails closed.
- Automatic trading-policy promotion remains disabled unless separately proven and explicitly authorized.

## Repair Until Clean

For a technical defect:

1. Identify the first causal blocker.
2. Repair the lowest competent authoritative owner.
3. Run focused tests.
4. Verify runtime when runtime behavior is affected.
5. Rerun the affected chain and inspect the next handoff.
6. Continue while the next issue is safely correctable within scope.
7. Stop only at a valid terminal classification.

Do not stop at a downstream symptom or at dispatch of a recovery action.

Valid terminal classifications include:

- `TECHNICALLY_CLEAN`
- `NATURAL_WAIT`
- `SESSION_WAIT`
- `VALID_CAPACITY_WAIT`
- `POLICY_REJECTION`
- `PROVIDER_EXTERNAL`
- `BROKER_EXTERNAL`
- `CODE_REPAIR_REQUIRED`

## End-to-End Contract

Preserve and reason about:

`market data -> discovery -> candidate -> qualification -> eligibility -> ORDER_READY -> entry -> fill -> lifecycle -> observation -> management -> exit -> reconciliation -> strict truth -> learning -> capacity release -> reevaluation`

When diagnosing a stall, compare adjacent authoritative handoffs and report
the first broken transition, not only a later symptom.

## Lane Isolation

The lanes are `SCALP`, `DAY`, `SWING`, and `CRYPTO`.

- Keep lane-local faults lane-local unless evidence proves a shared fault.
- Do not globally disable unrelated lanes for one lifecycle or lane.
- Respect SCALP same-session behavior, DAY session/day-trade behavior, legitimate SWING multi-day carry, and CRYPTO 24/7 semantics.
- Do not apply equity-session assumptions to CRYPTO.

## Truth and Learning Integrity

- Canonical broker completion and reconciliation own strict trading truth.
- Preserve exactly-once identity semantics where applicable: entry fill -> lifecycle -> exit fill -> reconciliation -> truth -> learning acknowledgement.
- Synthetic tests, certification, Shadow results, replay, and counterfactuals must not enter production truth or broker history.
- Learning is lane-specific: SCALP learns SCALP, DAY learns DAY, SWING learns SWING, and CRYPTO learns CRYPTO.
- Cross-lane learning requires independent supporting evidence.

## Reuse Existing Architecture

Audit the relevant canonical owner before writing code. Strengthen the
canonical path instead of creating parallel authorities. Do not create
replacement or equal-authority versions of existing Warehouse/retrieval,
satellite, compression/Librarian, Teacher, memory, lane-monitor, Sentinel,
Governance, Cortex, continuous-integrity/watchdog, truth-registry, execution,
or worker-supervisor systems unless a proven gap explicitly requires it.

Cortex is synthesis and adaptive coordination, not execution authority.
Governance gates policy-sensitive actions. Technical self-repair may be
automatic only when deterministic, policy-neutral, bounded, evidence-backed,
and rollback-safe. Do not grant autonomous source-code editing or deployment.

## Evidence Priority

When sources disagree, prefer:

1. Current live runtime.
2. Current readiness and certification.
3. Canonical worker execution trace.
4. Canonical lifecycle and truth state.
5. Deployed source at the actual running revision.
6. Recent repair reports.
7. Historical logs as background only.

Verify process revision, module identity, and source path when source and
runtime disagree. A revision string alone is not proof of loaded code.

## Rate and Credit Efficiency

- Treat supplied `PROVEN STATE` as authoritative unless current evidence directly contradicts it.
- Start with the smallest relevant files and functions; expand scope only when a concrete dependency requires it.
- Prefer targeted `rg`, `grep`, `jq`, bounded SQL, and `tail` over full-file, log, or JSON dumps.
- Reuse persisted findings and repair packages.
- Do not restart broad audits from scratch or repeat completed audits without regression evidence.
- Search narrowly around the proven gap and use the smallest bounded task that can resolve it.
- Reuse existing contracts, helpers, owners, and tests before creating new ones.
- Avoid duplicate provider/API calls, full-history scans, repeated architecture summaries, and unnecessary runtime restarts.
- Prefer focused tests first and expand only when a bounded dependency warrants it.
- For long deterministic jobs, use checkpoint/resume and compact saved reports instead of streaming large output through Codex.
- Keep commands and reports bounded: summarize counts, limit samples, and save large deterministic output to files.
- Use the least expensive capable model or tool for bounded audits and simple verification when model selection is available.
- Final reports should be concise and separate `PROVEN`, `CHANGED`, `VALIDATED`, `UNRESOLVED`, `SAFETY`, and `GIT`.
- PAPER ONLY: never fabricate candidates, orders, fills, ownership, lifecycle completion, truth, learning, P&L, or evidence.
- Historical, replay, and Shadow evidence remains separate from natural broker truth.

## Established Areas

Treat these as completed and do not reinvestigate them absent current
regression evidence:

- Alpaca websocket ownership is worker-only.
- Worker lifecycle JSONL latency repair is complete.
- Stale/legacy discovery false-positive repairs are complete.
- DAY entry false-positive repair is complete.
- Runtime identity repair is complete.
- GEHC monitoring classification and lifecycle persistence repairs are complete.
- Lane activity, truth starvation, and readiness upgrades are complete.
- Hierarchical lane operations and learning-utilization architecture are complete.
- CRYPTO canonical capacity classification is repaired.
- CRYPTO active-position quote handoff, alias, and recovery-ledger management repairs are complete.
- Four-lane end-to-end certification work is complete.
- Permanent end-to-end integrity watchdog and Sentinel/Governance/Cortex integration are complete.
- Session waits and valid capacity waits are intentionally distinct from technical faults.

These are not guarantees that defects can never recur. Current evidence wins.

## Git Discipline

- Never use `git add .`.
- Stage only intended source, test, and documentation files.
- Never stage runtime/state/log/diagnostic files unless explicitly part of the task.
- Inspect `git status` and `git diff --cached` before committing.
- Preserve unrelated user changes.
- Do not reset, delete, or rewrite migration backups or unrelated state.

## Test and Runtime Verification

For source repairs, run focused tests, relevant adjacent regression tests, and
`py_compile` or an equivalent syntax check where appropriate. Run
`git diff --check`. Verify source/running revision alignment and live runtime
behavior when affected. Separate structural verification from natural PAPER
proof.

Do not force a trade or exit to prove capability. Do not manually clear
readiness or truth faults. Report provider/broker external conditions and
natural waits explicitly.

## Completion Reports

Keep reports concise and separate:

- `PROVEN`
- `NOT PROVEN`
- `WHAT WAS WRONG`
- `WHAT CHANGED`
- `TESTS / RUNTIME VERIFICATION`
- `REMAINING FIRST BLOCKER`
- `FINAL STATUS`
