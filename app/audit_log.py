"""
Audit Log
==========
Append-only decision log. A human override is never written as an UPDATE
to the original row — it's inserted as a new row in a separate
`reviewer_overrides` table that references the original entry. This keeps
the original decision record immutable (what the system actually did,
under which policy version, is never rewritten) while still capturing the
review outcome as a first-class, queryable fact for the feedback loop.
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "controlplane.db"


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                use_case TEXT NOT NULL,
                jurisdiction TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                scenario_id TEXT,
                request_text TEXT,
                raw_response_text TEXT,
                delivered_text TEXT,
                findings_json TEXT,
                overall_risk REAL,
                decision_tier TEXT,
                throttled_from_escalate INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reviewer_overrides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                audit_log_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                override_decision TEXT NOT NULL,   -- 'agree' | 'false_positive' | 'false_negative'
                note TEXT,
                FOREIGN KEY (audit_log_id) REFERENCES audit_log(id)
            )
        """)
        conn.commit()


def write_entry(use_case: str, jurisdiction: str, policy_version: str,
                 scenario_id: Optional[str], request_text: str,
                 raw_response_text: str, decision: Dict[str, Any]) -> int:
    with _conn() as conn:
        cur = conn.execute("""
            INSERT INTO audit_log
                (timestamp, use_case, jurisdiction, policy_version, scenario_id,
                 request_text, raw_response_text, delivered_text, findings_json,
                 overall_risk, decision_tier, throttled_from_escalate)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now(timezone.utc).isoformat(),
            use_case, jurisdiction, policy_version, scenario_id,
            request_text, raw_response_text, decision["delivered_text"],
            json.dumps(decision["findings"]),
            decision["overall_risk"], decision["tier"],
            int(decision["throttled_from_escalate"]),
        ))
        conn.commit()
        return cur.lastrowid


def record_override(audit_log_id: int, reviewer: str, override_decision: str, note: str = ""):
    with _conn() as conn:
        conn.execute("""
            INSERT INTO reviewer_overrides (audit_log_id, timestamp, reviewer, override_decision, note)
            VALUES (?, ?, ?, ?, ?)
        """, (audit_log_id, datetime.now(timezone.utc).isoformat(), reviewer, override_decision, note))
        conn.commit()


def get_entry(audit_log_id: int) -> Optional[Dict[str, Any]]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM audit_log WHERE id = ?", (audit_log_id,)).fetchone()
        return dict(row) if row else None


def recent_entries(use_case: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    with _conn() as conn:
        if use_case:
            rows = conn.execute(
                "SELECT * FROM audit_log WHERE use_case = ? ORDER BY id DESC LIMIT ?",
                (use_case, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


def escalation_rate_per_1000(use_case: str) -> float:
    with _conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) c FROM audit_log WHERE use_case = ?", (use_case,)
        ).fetchone()["c"]
        escalated = conn.execute(
            "SELECT COUNT(*) c FROM audit_log WHERE use_case = ? AND decision_tier = 'ESCALATE'",
            (use_case,),
        ).fetchone()["c"]
        if total == 0:
            return 0.0
        return (escalated / total) * 1000


def overrides_for_use_case(use_case: str) -> List[Dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute("""
            SELECT ro.*, al.use_case, al.findings_json, al.decision_tier
            FROM reviewer_overrides ro
            JOIN audit_log al ON al.id = ro.audit_log_id
            WHERE al.use_case = ?
            ORDER BY ro.id DESC
        """, (use_case,)).fetchall()
        return [dict(r) for r in rows]


def metrics_summary() -> Dict[str, Any]:
    with _conn() as conn:
        by_use_case = conn.execute("""
            SELECT use_case, decision_tier, COUNT(*) c
            FROM audit_log GROUP BY use_case, decision_tier
        """).fetchall()
        total_requests = conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"]
        total_overrides = conn.execute("SELECT COUNT(*) c FROM reviewer_overrides").fetchone()["c"]
        return {
            "by_use_case_tier": [dict(r) for r in by_use_case],
            "total_requests": total_requests,
            "total_overrides": total_overrides,
        }
