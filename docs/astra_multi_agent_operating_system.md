# Astra Multi-Agent Operating System V1

## 1. Purpose and Scope

The Multi-Agent OS (MAOS) is a repository-local coordination layer that lets
multiple agents work on the Astra code base in parallel without colliding.
It enforces:

- **File and contract ownership** per workstream.
- **Forbidden paths** that protect live state, secrets, and the live Astra checkout.
- **Worktree isolation** so every agent works in its own branch/worktree.
- **Dependency ordering** before integration.
- **Model routing** that matches task risk to the smallest sufficient model.
- **Acceptance ledger** that blocks completion until every criterion is
  evidenced or externally blocked.
- **Integration queue** that serializes merge-ready workstreams under human
  integrator control.

The OS is **advisory-only**: it never restarts Astra, never submits broker
orders, never writes to the live checkout, and never merges or pushes to
`main` on its own.

## 2. Repository Layout

```text
ops/multi_agent/
  schema_version.yaml          # Data format version
  model_roles.yaml             # Model capabilities and rate policy inputs
  rate_policy.yaml             # Relative rate cost and policy rules
  active_workstreams.yaml        # Currently running workstreams
  completed_workstreams.yaml     # Finished workstreams
  file_ownership.yaml          # Derived file -> workstream map
  contract_ownership.yaml      # Derived contract -> workstream map
  integration_queue.yaml         # Merge-ready queue
  forbidden_paths.yaml         # Paths that may never be owned
  examples/                    # Sample workstream records
  templates/                   # Workstream and prompt templates
  common.py                    # Shared utilities
  registry.py                  # Registry load/save and ownership builders
  validator.py               # Schema, ownership, forbidden path, dependency,
                               # worktree, and status transition validation
  routing.py                 # Model recommendation and rate policy
  ledger.py                  # Acceptance-criteria validation
  queue.py                   # Integration queue logic
  prompt.py                  # Model-specific prompt generation

scripts/
  astra_agent_register.py      # Register a workstream from a YAML file
  astra_agent_validate.py      # Validate one or all workstreams
  astra_agent_status.py        # Show active workstreams and queue
  astra_agent_prompt.py        # Generate a prompt for a workstream
  astra_agent_finish.py        # Validate workstream completion
  astra_agent_review.py        # Pass/fail review and transition to ready
  astra_integration_queue.py # Manage the integration queue
  astra_agent_lock_check.py  # Check whether a file or contract is locked

tests/
  test_astra_multi_agent_os.py # Comprehensive focused test suite
```

## 3. Workstream Lifecycle

| Status | Meaning | Allowed next statuses |
|---|---|---|
| `proposed` | Idea recorded | `validated`, `active`, `blocked`, `cancelled` |
| `validated` | Schema and ownership checks pass | `active`, `blocked`, `cancelled` |
| `active` | Agent is implementing | `implementation_complete`, `blocked`, `failed`, `cancelled` |
| `implementation_complete` | All criteria pass or are externally blocked | `review_required`, `blocked`, `failed`, `cancelled` |
| `review_required` | Awaiting independent review | `review_failed`, `review_passed`, `blocked`, `cancelled` |
| `review_failed` | Review found issues | `active`, `blocked`, `failed`, `cancelled` |
| `review_passed` | Review passed | `integration_ready`, `blocked`, `cancelled` |
| `integration_ready` | In the integration queue | `integrating`, `blocked`, `cancelled` |
| `integrating` | Human integrator is merging | `integrated`, `blocked`, `failed`, `cancelled` |
| `integrated` | Merged to `main` | (terminal) |
| `blocked` | Externally blocked | `active`, `cancelled` |
| `failed` | Irrecoverable | `proposed`, `cancelled` |
| `cancelled` | Aborted | (terminal) |

## 4. Ownership and Lock Check

Each workstream declares the files, patterns, and canonical contracts it owns.
The registry forbids:

- Two workstreams owning the exact same file.
- A file owned by one workstream matching a pattern owned by another.
- Two workstreams owning the same canonical contract.
- Overlapping patterns.

Run `astra_agent_lock_check.py` to test whether a path or contract is already
locked:

```bash
python scripts/astra_agent_lock_check.py --file src/foo.py
python scripts/astra_agent_lock_check.py --contract broker_submission
```

## 5. Forbidden Paths

`forbidden_paths.yaml` lists patterns that agents may never own. These include:

- The live Astra checkout (`/Users/eric/Desktop/astra-intelligence-clean`).
- Live state files under `state/`, `logs/`, `diagnostics/`, `.env` files.
- Configuration that could affect production.

Validating a workstream that claims any forbidden path returns a clear error.

## 6. Dependencies

A workstream may declare `depends_on` other workstreams. A dependency is
considered satisfied only when its status is `integrating` or `integrated`.
Circular dependencies are rejected.

## 7. Model Routing

`routing.py` recommends a model based on:

- `risk_level`: low, medium, high, critical.
- `complexity`: low, medium, high, critical.
- `task_type`: review/audit vs implementation.
- `touches_runtime`, `touches_broker`, `touches_canonical`, `cross_system`.

Policy rules:

- Low-risk review/audit tasks route to `deepseek-flash`.
- Contained implementation routes to `kimi`.
- Broker, runtime, lifecycle, canonical, or high-risk tasks route to
  `deepseek-pro`.
- Cross-system or critical tasks route to `codex`.
- The rate policy `max_model_tier` caps the final recommendation.

## 8. Acceptance Ledger

Each workstream has an `acceptance_criteria` list. A criterion may be:

- `PASS` — requires non-empty `evidence`.
- `BLOCKED` — requires an `external_blocker` reason.
- `FAIL` — prevents the workstream from finishing.
- `NOT_EVALUATED` — prevents the workstream from finishing.

`controllable_work_remaining` is also forbidden on a `PASS` criterion.

## 9. Integration Queue

Workstreams move into the integration queue only after:

- Status is `review_passed`.
- Ledger is valid.
- Required independent review is recorded.
- Worktree is valid.

Queue operations are manual and advisory:

```bash
python scripts/astra_integration_queue.py add <id>
python scripts/astra_integration_queue.py status
python scripts/astra_integration_queue.py start <id>
python scripts/astra_integration_queue.py complete <id>
```

The queue never merges, pushes, or restarts Astra.

## 10. Scripts

All scripts are thin wrappers around the modules and are executable from the
repository root:

```bash
# Register a new workstream from a YAML file
python scripts/astra_agent_register.py ops/multi_agent/examples/deepseek_position_lifecycle.yaml

# Validate one workstream
python scripts/astra_agent_validate.py --id my-workstream

# Validate all active workstreams
python scripts/astra_agent_validate.py --all

# Show status
python scripts/astra_agent_status.py

# Generate a prompt
python scripts/astra_agent_prompt.py my-workstream

# Validate completion
python scripts/astra_agent_finish.py my-workstream

# Pass/fail review
python scripts/astra_agent_review.py my-workstream --status passed

# Check lock
python scripts/astra_agent_lock_check.py --file src/foo.py --workstream my-workstream
```

## 11. Safety Rules

- `advisory_only: true`
- `execution_authorized: false`
- `paper_action_ready: false`
- `broker_submission_allowed: false`
- No script may restart Astra or modify the live checkout.
- No automatic merge or push to `main`.
- All operations are logged in the YAML registries.

## 12. Testing

Run the focused test suite:

```bash
python -m pytest tests/test_astra_multi_agent_os.py -v
```

The tests validate schema checks, ownership conflicts, forbidden paths,
dependencies, worktree state, routing, ledger, queue ordering, prompt
generation, script import/syntax, and runtime isolation.

## 13. Example Workflow

1. Create a workstream YAML from `ops/multi_agent/templates/workstream_template.yaml`.
2. Register it with `astra_agent_register.py`.
3. Validate with `astra_agent_validate.py`.
4. Start implementation in the assigned worktree.
5. Update criteria and evidence.
6. Run `astra_agent_finish.py` to validate completion.
7. Run `astra_agent_review.py --status passed`.
8. Add to the queue with `astra_integration_queue.py add`.
9. A human integrator runs `astra_integration_queue.py start` and later
   `complete` outside the OS.

## 14. Schema Version

The OS schema version is `1.0.0` and is recorded in
`ops/multi_agent/schema_version.yaml`.
