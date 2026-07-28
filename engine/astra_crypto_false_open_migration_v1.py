"""Safe idempotent migration: mark false crypto OPEN records as SIMULATED.

Applies only to records with:
  status='OPEN', asset_type=crypto, reconciliation_reason=SIMULATED_OPEN_NO_BROKER_LINKAGE
  no entry_fill_id, entry_price_verified=0
  AND they are NOT broker-linked active positions according to the canonical
  predicate from astra_canonical_ownership_contract_v1.

Repeated execution affects zero additional rows.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engine.astra_canonical_ownership_contract_v1 import is_broker_linked_active_position


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _row_to_record(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def migrate_false_crypto_open(db_path: str | Path, apply: bool = True) -> dict[str, Any]:
    """Migrate false crypto OPEN records to SIMULATED."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    now = _now_iso()

    migrated = 0
    eligible = 0
    remaining = 0
    simulated = 0
    crypto_open = 0
    skipped_active = 0
    errors: list[str] = []

    try:
        cur.execute("""
            SELECT * FROM paper_positions
            WHERE status = 'OPEN'
            AND asset_type IN ('crypto','cryptocurrency')
            AND reconciliation_reason = 'SIMULATED_OPEN_NO_BROKER_LINKAGE'
            AND (entry_fill_id IS NULL OR entry_fill_id = '')
            AND entry_price_verified = 0
        """)
        candidate_rows = [_row_to_record(r) for r in cur.fetchall()]

        # Filter using the canonical broker-linked active-position predicate.
        # Real broker-linked crypto positions must NEVER be migrated to SIMULATED.
        eligible_rows = []
        for row in candidate_rows:
            if is_broker_linked_active_position(row, allow_dust=True):
                skipped_active += 1
            else:
                eligible_rows.append(row)

        eligible = len(eligible_rows)

        if apply and eligible > 0:
            migration_id = f"mig:crypto_simulated:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            position_ids = [str(r["position_id"]) for r in eligible_rows if r.get("position_id")]
            placeholders = ",".join("?" * len(position_ids))
            cur.execute(f"""
                UPDATE paper_positions SET
                    prior_status = CASE WHEN prior_status IS NULL OR prior_status = '' THEN status ELSE prior_status END,
                    status = 'SIMULATED',
                    lifecycle_notes = COALESCE(lifecycle_notes, '') || ?
                WHERE position_id IN ({placeholders})
                AND status = 'OPEN'
                AND asset_type IN ('crypto','cryptocurrency')
                AND reconciliation_reason = 'SIMULATED_OPEN_NO_BROKER_LINKAGE'
                AND (entry_fill_id IS NULL OR entry_fill_id = '')
                AND entry_price_verified = 0
            """, (f"||migrated_SIMULATED:{migration_id}@{now}", *position_ids))
            migrated = cur.rowcount
            conn.commit()

        # Idempotency check
        cur.execute("""
            SELECT * FROM paper_positions
            WHERE status = 'OPEN'
            AND asset_type IN ('crypto','cryptocurrency')
            AND reconciliation_reason = 'SIMULATED_OPEN_NO_BROKER_LINKAGE'
            AND (entry_fill_id IS NULL OR entry_fill_id = '')
            AND entry_price_verified = 0
        """)
        remaining_rows = [_row_to_record(r) for r in cur.fetchall()]
        remaining = len([r for r in remaining_rows if not is_broker_linked_active_position(r, allow_dust=True)])

        cur.execute("SELECT COUNT(*) FROM paper_positions WHERE status='SIMULATED' AND asset_type IN ('crypto','cryptocurrency')")
        simulated = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM paper_positions WHERE status='OPEN' AND asset_type IN ('crypto','cryptocurrency')")
        crypto_open = cur.fetchone()[0]

    except Exception as e:
        errors.append(str(e))
    finally:
        conn.close()

    return {
        "applied": apply,
        "eligible_pre_migration": eligible,
        "migrated_this_run": migrated,
        "remaining_eligible": remaining,
        "simulated_total": simulated if apply else 0,
        "false_crypto_open_count": crypto_open if apply else eligible,
        "skipped_active_broker_linked": skipped_active,
        "idempotent": migrated == 0 if eligible > 0 and not apply else True,
        "errors": errors,
    }
