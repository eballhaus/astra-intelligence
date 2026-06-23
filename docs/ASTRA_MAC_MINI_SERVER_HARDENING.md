# Astra Mac Mini Server Hardening

This guide documents the safe operational setup for running Astra as a local Mac mini server. It does not change trading behavior, broker behavior, ranking, entries, exits, sizing, allocation, thresholds, provider usage, or LLM usage.

## Startup Scripts

Use the existing persistent scripts from the repository root:

```bash
bash ./start_astra_persistent.sh
bash ./stop_astra_persistent.sh
```

The wrapper scripts in `scripts/` call the same lifecycle:

```bash
bash ./scripts/start_astra.sh
bash ./scripts/stop_astra.sh
```

Startup logs are appended to:

```text
logs/astra_startup.log
```

## Targeted Recovery

The persistent start script supports component-scoped recovery for the watchdog:

```bash
ASTRA_START_COMPONENT=backend ASTRA_START_SKIP_CLEANUP=1 bash ./start_astra_persistent.sh
ASTRA_START_COMPONENT=frontend ASTRA_START_SKIP_CLEANUP=1 bash ./start_astra_persistent.sh
```

Valid components are:

```text
all
backend
frontend
```

Targeted recovery stops only the degraded component's tmux session and port listener. Full startup still performs a full cleanup to avoid duplicate owners.

## Watchdog

One-shot check:

```bash
python3 scripts/astra_watchdog.py
```

Continuous mode:

```bash
python3 scripts/astra_watchdog.py --loop --interval 45
```

Watchdog logs:

```text
logs/astra_watchdog.log
logs/astra_recovery.log
```

The watchdog is operational only. It may restart backend/frontend services, but it never trades, sells, changes broker behavior, changes rankings, changes entries, changes exits, changes sizing, changes allocation, changes thresholds, or calls providers/LLMs.

## LaunchAgent

Validate the plist:

```bash
plutil -lint scripts/com.astra.watchdog.plist
```

Install using the existing installer only when you want macOS to keep Astra running:

```bash
bash scripts/install_astra_launch_agent.sh
```

Remove it with:

```bash
bash scripts/uninstall_astra_launch_agent.sh
```

## Remote Access Checklist

Manual macOS settings may be needed for remote operation. Astra does not enable these automatically.

1. Enable SSH manually if desired: System Settings -> General -> Sharing -> Remote Login.
2. Enable Screen Sharing manually if desired: System Settings -> General -> Sharing -> Screen Sharing.
3. Install and authenticate Tailscale manually if desired.
4. Confirm local health: `curl http://127.0.0.1:8000/api/health`.
5. Confirm frontend: `curl http://127.0.0.1:5173`.
6. Open Recovery Center in Astra for a read-only status snapshot.

## Recovery Center Endpoint

```text
/api/astra_recovery_center_v1
```

The endpoint reports:

- Backend/frontend health
- tmux session presence
- watchdog/recovery log availability
- remote access status
- learning freshness protection
- local system status
- explicit safety flags

Expected safety fields remain:

```text
behavior_safe_to_apply=false
broker_execution_added=false
automatic_entries_enabled=false
automatic_exits_enabled=false
provider_calls_used=0
llm_calls_used=0
dashboard_provider_calls_used=0
dashboard_llm_calls_used=0
```

## If Astra Appears Offline

1. Run `bash ./scripts/check_astra_health.sh`.
2. Run `python3 scripts/astra_watchdog.py` for one-shot recovery.
3. Review `logs/astra_recovery.log` and `logs/astra_startup.log`.
4. If both backend and frontend are unhealthy, run `bash ./start_astra_persistent.sh`.
5. If only one component is unhealthy, use targeted recovery commands above.

## Safety Boundary

This hardening layer is infrastructure-only. It is not a strategy layer and does not modify Astra intelligence outputs or trading behavior.
