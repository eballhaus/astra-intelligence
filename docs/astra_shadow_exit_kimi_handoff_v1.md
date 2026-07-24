# Astra Shadow Exit Kimi Handoff V1

Codex owns lifecycle identity, worker scheduling, durable state, advisory integration,
Sentinel/Governance, provider and broker safety, and final integration.

Kimi may create only the five analysis modules and their focused tests listed in
[`astra_shadow_exit_module_contract_v1.json`](../contracts/astra_shadow_exit_module_contract_v1.json).
Kimi must not edit `paper_autopilot.py`, `server_extend.py`, the canonical shadow
owner, advisory owners, Sentinel, Governance, or broker/provider code.

Every callable accepts plain dictionaries and returns a deterministic dictionary with
`status`, `blockers`, `sample_size`, `shadow_evaluation_id`, and `position_identity`.
Inputs use provider-native timestamps and real observation prices only. A function
must return `INSUFFICIENT_SAMPLE`, `PENDING_OBSERVATION`, or `EXTERNALLY_BLOCKED`
instead of raising for missing, stale, or zero-denominator inputs. No function may
look beyond an observation target timestamp, mutate input state, create orders, or
promote a policy. Codex alone consumes module outputs into the advisory contract.
