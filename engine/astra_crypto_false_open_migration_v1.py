"""Safe idempotent migration: mark false crypto OPEN records as SIMULATED.

Applies only to records with:
  status='OPEN', asset_type=crypto, reconciliation_reason=SIMULATED_OPEN_NO_BROKER_LINKAGE
  no entry_fill_id, entry_price_verified=0

Repeated execution affects zero additional rows.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def migrate_false_crypto_open(db_path: str | Path, apply: bool = True) -> dict[str, Any]:
    """Migrate false crypto OPEN records to SIMULATED."""
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    now = _now_iso()

    migrated = 0
    errors: list[str] = []

    try:
        cur.execute("""
            SELECT COUNT(*) FROM paper_positions
            WHERE status = 'OPEN'
            AND asset_type IN ('crypto','cryptocurrency')
            AND reconciliation_reason = 'SIMULATED_OPEN_NO_BROKER_LINKAGE'
            AND (entry_fill_id IS NULL OR entry_fill_id = '')
            AND entry_price_verified = 0
        """)
        eligible = cur.fetchone()[0]

        if apply and eligible > 0:
            migration_id = f"mig:crypto_simulated:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            cur.execute("""
                UPDATE paper_positions SET
                    prior_status = CASE WHEN prior_status IS NULL OR prior_status = '' THEN status ELSE prior_status END,
                    status = 'SIMULATED',
                    lifecycle_notes = COALESCE(lifecycle_notes, '') || ?
                WHERE status = 'OPEN'
                AND asset_type IN ('crypto','cryptocurrency')
                AND reconciliation_reason = 'SIMULATED_OPEN_NO_BROKER_LINKAGE'
                AND (entry_fill_id IS NULL OR entry_fill_id = '')
                AND entry_price_verified = 0
            """, (f"||migrated_SIMULATED:{migration_id}@{now}",))
            migrated = cur.rowcount
            conn.commit()

        # Idempotency check
        cur.execute("""
            SELECT COUNT(*) FROM paper_positions
            WHERE status = 'OPEN'
            AND asset_type IN ('crypto','cryptocurrency')
            AND reconciliation_reason = 'SIMULATED_OPEN_NO_BROKER_LINKAGE'
            AND (entry_fill_id IS NULL OR entry_fill_id = '')
            AND entry_price_verified = 0
        """)
        remaining = cur.fetchone()[0]

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
        "idempotent": migrated == 0 if eligible > 0 and not apply else True,
        "errors": errors,
    }
