"""
Persistent store for active VAPI call state (SQLite-backed).

Each outbound call gets a record keyed by VAPI call_id. This allows the
/chat/completions endpoint to look up per-call metadata (workflow_id,
handoff context, compliance history) and the webhook to correlate
end-of-call events back to Temporal workflows.

Persistence: records are written to SQLite so call state survives
process restarts.  An in-memory cache avoids DB round-trips on the
hot path (/chat/completions per-turn lookups).

Thread-safe via threading.Lock since uvicorn may serve requests concurrently.
"""

import json
import sqlite3
import threading
import time
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

_DB_PATH = os.getenv("DB_PATH", "./collections_agents.db")


@dataclass
class CallRecord:
    """State tracked for a single active voice call."""
    call_id: str
    workflow_id: str
    borrower_name: str
    borrower_phone: str
    balance: float
    handoff_summary: str                         # Agent 1 → 2 ledger (raw text)
    system_prompt: str                           # Full system prompt sent to VAPI
    created_at: float = field(default_factory=time.time)
    turn_count: int = 0
    compliance_violations: List[Dict] = field(default_factory=list)
    offers_made: List[Dict] = field(default_factory=list)
    ended: bool = False
    outcome: Optional[str] = None
    transcript: Optional[str] = None


class CallStateStore:
    """
    SQLite-backed store for active call records.

    On startup, loads existing records from DB into an in-memory cache.
    Mutations are written through to both cache and DB.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._calls: Dict[str, CallRecord] = {}
                    cls._instance._workflow_to_call: Dict[str, str] = {}
                    cls._instance._init_db()
                    cls._instance._load_from_db()
        return cls._instance

    def _get_conn(self) -> sqlite3.Connection:
        """Thread-local connection (sqlite3 objects can't cross threads)."""
        return sqlite3.connect(_DB_PATH)

    def _init_db(self):
        """Create the call_state table if it doesn't exist."""
        conn = self._get_conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS call_state (
                    call_id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    borrower_name TEXT,
                    borrower_phone TEXT,
                    balance REAL,
                    handoff_summary TEXT,
                    system_prompt TEXT,
                    created_at REAL,
                    turn_count INTEGER DEFAULT 0,
                    compliance_violations TEXT DEFAULT '[]',
                    offers_made TEXT DEFAULT '[]',
                    ended INTEGER DEFAULT 0,
                    outcome TEXT,
                    transcript TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_call_state_workflow
                ON call_state(workflow_id)
            """)
            conn.commit()
        finally:
            conn.close()

    def _load_from_db(self):
        """Load active (non-ended) records into memory on startup."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT * FROM call_state WHERE ended = 0"
            )
            cols = [d[0] for d in cursor.description]
            for row in cursor:
                data = dict(zip(cols, row))
                record = CallRecord(
                    call_id=data["call_id"],
                    workflow_id=data["workflow_id"],
                    borrower_name=data["borrower_name"] or "",
                    borrower_phone=data["borrower_phone"] or "",
                    balance=data["balance"] or 0.0,
                    handoff_summary=data["handoff_summary"] or "",
                    system_prompt=data["system_prompt"] or "",
                    created_at=data["created_at"] or time.time(),
                    turn_count=data["turn_count"] or 0,
                    compliance_violations=json.loads(data["compliance_violations"] or "[]"),
                    offers_made=json.loads(data["offers_made"] or "[]"),
                    ended=bool(data["ended"]),
                    outcome=data["outcome"],
                    transcript=data["transcript"],
                )
                self._calls[record.call_id] = record
                self._workflow_to_call[record.workflow_id] = record.call_id
            logger.info(f"Loaded {len(self._calls)} active call records from DB")
        except Exception as e:
            logger.warning(f"Failed to load call state from DB: {e}")
        finally:
            conn.close()

    def _persist(self, record: CallRecord):
        """Write-through to SQLite."""
        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO call_state
                (call_id, workflow_id, borrower_name, borrower_phone, balance,
                 handoff_summary, system_prompt, created_at, turn_count,
                 compliance_violations, offers_made, ended, outcome, transcript)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.call_id, record.workflow_id, record.borrower_name,
                record.borrower_phone, record.balance, record.handoff_summary,
                record.system_prompt, record.created_at, record.turn_count,
                json.dumps(record.compliance_violations),
                json.dumps(record.offers_made),
                int(record.ended), record.outcome, record.transcript,
            ))
            conn.commit()
        except Exception as e:
            logger.error(f"Failed to persist call state for {record.call_id}: {e}")
        finally:
            conn.close()

    def register(self, record: CallRecord) -> None:
        with self._lock:
            self._calls[record.call_id] = record
            self._workflow_to_call[record.workflow_id] = record.call_id
            logger.info(
                f"Registered call {record.call_id} for workflow {record.workflow_id}"
            )
        self._persist(record)

    def get_by_call_id(self, call_id: str) -> Optional[CallRecord]:
        return self._calls.get(call_id)

    def get_by_workflow_id(self, workflow_id: str) -> Optional[CallRecord]:
        call_id = self._workflow_to_call.get(workflow_id)
        if call_id:
            return self._calls.get(call_id)
        return None

    def mark_ended(self, call_id: str, outcome: str, transcript: str) -> None:
        with self._lock:
            record = self._calls.get(call_id)
            if record:
                record.ended = True
                record.outcome = outcome
                record.transcript = transcript
        if record:
            self._persist(record)

    def increment_turn(self, call_id: str) -> int:
        with self._lock:
            record = self._calls.get(call_id)
            if record:
                record.turn_count += 1
                turn = record.turn_count
            else:
                turn = 0
        if record:
            self._persist(record)
        return turn

    def add_violation(self, call_id: str, violation: Dict) -> None:
        with self._lock:
            record = self._calls.get(call_id)
            if record:
                record.compliance_violations.append(violation)
        if record:
            self._persist(record)

    def add_offer(self, call_id: str, offer: Dict) -> None:
        with self._lock:
            record = self._calls.get(call_id)
            if record:
                record.offers_made.append(offer)
        if record:
            self._persist(record)

    def cleanup_stale(self, max_age_seconds: int = 3600) -> int:
        """Remove call records older than max_age_seconds."""
        now = time.time()
        removed = 0
        stale_ids = []
        with self._lock:
            stale_ids = [
                cid for cid, rec in self._calls.items()
                if (now - rec.created_at) > max_age_seconds
            ]
            for cid in stale_ids:
                rec = self._calls.pop(cid, None)
                if rec:
                    self._workflow_to_call.pop(rec.workflow_id, None)
                    removed += 1
        # Also clean from DB
        if stale_ids:
            conn = self._get_conn()
            try:
                placeholders = ",".join("?" * len(stale_ids))
                conn.execute(
                    f"DELETE FROM call_state WHERE call_id IN ({placeholders})",
                    stale_ids
                )
                conn.commit()
            finally:
                conn.close()
        if removed:
            logger.info(f"Cleaned up {removed} stale call records")
        return removed


def get_call_store() -> CallStateStore:
    return CallStateStore()
