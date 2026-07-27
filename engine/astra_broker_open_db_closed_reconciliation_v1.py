"""Safe migration: reconcile BROKER_OPEN_DB_CLOSED positions.

Creates truthful OPEN records for broker positions whose DB records were
prematurely closed (partial sell residuals, rounding, etc.).

Idempotent — safe to run repeatedly.
"""
import sqlite3
import json
import uuid
from datetime import datetime, timezone

def _now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def _num(val, default=0.0):
    try:
        return float(val) if val not in (None, "") else default
    except (TypeError, ValueError):
        return default

def migrate_broker_open_db_closed(apply: bool = True):
    conn = sqlite3.connect("state/ai_trading_memory.db")
    cur = conn.cursor()
    now = _now_iso()
    
    # Get broker positions from capacity snapshot
    with open("state/paper_autopilot_state.json") as f:
        state = json.load(f)
    cap = state.get("last_evidence_capacity_snapshot", {})
    pos_rows = cap.get("position_rows_for_read_only_consumers", [])
    
    # Build broker position data
    broker_data = {}
    for row in pos_rows:
        sym = row.get("symbol", "").upper()
        qty = float(row.get("qty", 0))
        if sym and qty > 0:
            broker_data[sym] = {
                "qty": qty,
                "avg_entry_price": float(row.get("avg_entry_price", 0)),
                "current_price": float(row.get("current_price", 0)),
                "market_value": float(row.get("market_value", 0)),
                "asset_class": row.get("asset_class", "us_equity"),
            }
    
    # Find BROKER_OPEN_DB_CLOSED symbols
    results = []
    created = 0
    skipped_already_open = 0
    skipped_dust = 0
    errors = 0
    
    for sym, bdata in sorted(broker_data.items()):
        if bdata["qty"] < 0.001:
            skipped_dust += 1
            results.append({"symbol": sym, "action": "SKIPPED_DUST", "qty": bdata["qty"]})
            continue
        
        # Check if already has an OPEN record
        cur.execute("SELECT position_id, quantity FROM paper_positions WHERE symbol=? AND status='OPEN'", (sym,))
        open_rows = cur.fetchall()
        if open_rows:
            skipped_already_open += 1
            results.append({"symbol": sym, "action": "SKIP_ALREADY_OPEN", "open_count": len(open_rows)})
            continue
        
        # Check CLOSED records for this symbol
        cur.execute("""
            SELECT position_id, entry_price, entry_price_verified, entry_price_source,
                   entry_order_id, entry_fill_id, source_candidate_id, source_lifecycle_id,
                   lane_id, position_owner, lifecycle_notes, reconciliation_reason
            FROM paper_positions 
            WHERE symbol=? AND status='CLOSED' 
            ORDER BY rowid DESC LIMIT 1
        """, (sym,))
        closed_row = cur.fetchone()
        
        if not closed_row:
            errors += 1
            results.append({"symbol": sym, "action": "ERROR_NO_CLOSED_RECORD"})
            continue
        
        try:
            old_pos_id = closed_row[0]
            # Use broker avg_entry_price as the truth; DB closed records may
            # reflect a different entry cycle. Entry is provisional unless
            # the DB record had verified fill evidence.
            old_entry_price = closed_row[1]
            old_entry_verified = int(closed_row[2] or 0)
            old_entry_source = closed_row[3]
            old_entry_order = closed_row[4]
            old_entry_fill = closed_row[5]
            old_candidate = closed_row[6]
            old_lifecycle = closed_row[7]
            old_lane = closed_row[8]
            old_owner = closed_row[9]
            old_notes = closed_row[10]
            old_reason = closed_row[11]
            
            # Broker-reported avg_entry is the current position entry price
            broker_entry = bdata["avg_entry_price"]
            # Prefer DB entry when broker-confirmed and consistent
            if old_entry_verified and old_entry_price and abs(old_entry_price - broker_entry) / max(broker_entry, 0.01) < 0.05:
                used_entry = old_entry_price
                entry_source = old_entry_source or "broker_and_db_confirmed"
                entry_verified = old_entry_verified
            elif broker_entry > 0:
                used_entry = broker_entry
                entry_source = "broker_position_reported_avg_entry"
                entry_verified = 0
            else:
                used_entry = old_entry_price
                entry_source = "db_last_closed_entry"
                entry_verified = 0

            # Decide ownership
            has_proven_lane = old_lane in ("DAY", "SWING", "CRYPTO") if old_lane else False
            has_entry_fill = bool(old_entry_fill and old_entry_fill.strip())
            is_managed = has_proven_lane and has_entry_fill and entry_verified == 1
            
            new_pos_id = f"recon:{sym}:{uuid.uuid4().hex[:12]}"
            
            if apply:
                notes = json.dumps({
                    "reconciled_from": old_pos_id,
                    "reconciliation_type": "BROKER_OPEN_DB_CLOSED",
                    "broker_qty": bdata["qty"],
                    "broker_avg_entry": bdata["avg_entry_price"],
                    "broker_current_price": bdata["current_price"],
                    "original_status": "CLOSED",
                    "original_exit_reason": old_reason,
                    "old_notes": old_notes,
                })
                
                lane_id = old_lane if has_proven_lane else ""
                position_owner = old_owner if is_managed else "LEGACY"
                ownership_status = "MANAGED" if is_managed else "LEGACY_MANAGED"
                
                cur.execute("""
                    INSERT INTO paper_positions (
                        position_id, symbol, asset_type, status, quantity,
                        entry_price, entry_price_verified, entry_price_provisional,
                        entry_price_source, entry_price_lineage_status,
                        lane_id, position_owner, exit_policy_owner,
                        entry_order_id, entry_fill_id,
                        source_candidate_id, source_lifecycle_id,
                        lifecycle_notes, reconciliation_reason,
                        reconciliation_evidence_source, prior_status,
                        source_bucket, created_at, updated_at, reconciled_at
                    ) VALUES (?, ?, ?, ?, ?,
                              ?, ?, ?, ?, ?,
                              ?, ?, ?, ?, ?,
                              ?, ?,
                              ?, ?, ?, ?, ?, ?, ?)
                """, (
                    new_pos_id, sym, bdata["asset_class"], "OPEN", round(bdata["qty"], 6),
                    round(used_entry, 6), entry_verified, 0,
                    entry_source, "UNPROVEN",
                    lane_id, position_owner, position_owner,
                    old_entry_order, old_entry_fill,
                    old_candidate, old_lifecycle,
                    notes, "PARTIAL_EXIT_RESIDUAL",
                    "broker_position_truth", "CLOSED",
                    ownership_status, now, now, now
                ))
                
                created += 1
                results.append({
                    "symbol": sym, 
                    "action": "CREATED",
                    "new_position_id": new_pos_id,
                    "qty": round(bdata["qty"], 6),
                    "entry_price": round(old_entry_price, 6),
                    "ownership": ownership_status,
                })
            else:
                results.append({
                    "symbol": sym,
                    "action": "WOULD_CREATE",
                    "qty": round(bdata["qty"], 6),
                    "entry_price": round(old_entry_price, 6),
                })
        except Exception as e:
            errors += 1
            results.append({"symbol": sym, "action": "ERROR", "error": str(e)})
    
    if apply:
        conn.commit()
    
    # Summary
    cur.execute("SELECT COUNT(*) FROM paper_positions WHERE status='OPEN' AND asset_type NOT IN ('crypto','cryptocurrency')")
    stock_open_after = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM paper_positions WHERE reconciliation_reason='PARTIAL_EXIT_RESIDUAL'")
    residual_count = cur.fetchone()[0]
    
    conn.close()
    
    return {
        "applied": apply,
        "broker_positions_found": len(broker_data),
        "created": created,
        "skipped_already_open": skipped_already_open,
        "skipped_dust": skipped_dust,
        "errors": errors,
        "stock_open_after": stock_open_after,
        "residual_reconciliation_count": residual_count,
        "results": results,
    }
