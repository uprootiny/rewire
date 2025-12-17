"""
Rewire database layer: SQLite-backed storage for expectations, observations, trials, violations.

Design principles:
- Append-only observations (epistemic trail)
- Violations are facts with evidence pointers
- WAL mode for concurrent read/write
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional, Iterator, Any, List

# Type aliases for clarity
Timestamp = int
ExpectationRow = sqlite3.Row
ObservationRow = sqlite3.Row
TrialRow = sqlite3.Row
ViolationRow = sqlite3.Row


SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS expectations (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL CHECK(type IN ('schedule', 'alert_path')),
  name TEXT NOT NULL,
  expected_interval_s INTEGER NOT NULL CHECK(expected_interval_s >= 60),
  tolerance_s INTEGER NOT NULL DEFAULT 0 CHECK(tolerance_s >= 0),
  params_json TEXT NOT NULL,
  owner_email TEXT NOT NULL,
  is_enabled INTEGER NOT NULL DEFAULT 1 CHECK(is_enabled IN (0, 1)),
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS observations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  expectation_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('start', 'end', 'ping', 'ack')),
  observed_at INTEGER NOT NULL,
  meta_json TEXT,
  FOREIGN KEY(expectation_id) REFERENCES expectations(id)
);

CREATE INDEX IF NOT EXISTS idx_obs_exp_time ON observations(expectation_id, observed_at);

CREATE TABLE IF NOT EXISTS alert_trials (
  id TEXT PRIMARY KEY,
  expectation_id TEXT NOT NULL,
  sent_at INTEGER NOT NULL,
  acked_at INTEGER,
  status TEXT NOT NULL CHECK(status IN ('pending', 'acked', 'expired')),
  meta_json TEXT,
  FOREIGN KEY(expectation_id) REFERENCES expectations(id)
);

CREATE INDEX IF NOT EXISTS idx_trials_exp ON alert_trials(expectation_id);
CREATE INDEX IF NOT EXISTS idx_trials_status ON alert_trials(status);

CREATE TABLE IF NOT EXISTS violations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  expectation_id TEXT NOT NULL,
  detected_at INTEGER NOT NULL,
  code TEXT NOT NULL,
  message TEXT NOT NULL,
  evidence_json TEXT NOT NULL,
  is_open INTEGER NOT NULL DEFAULT 1 CHECK(is_open IN (0, 1)),
  last_notified_at INTEGER,
  FOREIGN KEY(expectation_id) REFERENCES expectations(id)
);

CREATE INDEX IF NOT EXISTS idx_viol_open ON violations(expectation_id, is_open);
CREATE INDEX IF NOT EXISTS idx_viol_code ON violations(expectation_id, code);
"""


def now_i() -> Timestamp:
    """Current Unix timestamp as integer."""
    return int(time.time())


@dataclass(frozen=True)
class CreateExpectationParams:
    """Parameters for creating an expectation."""
    exp_id: str
    exp_type: str
    name: str
    expected_interval_s: int
    tolerance_s: int
    params_json: str
    owner_email: str


class Store:
    """
    SQLite-backed storage for Rewire.

    Thread-safe via connection-per-operation pattern.
    Uses WAL mode for concurrent reads during writes.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        """Context manager for database connections."""
        conn = sqlite3.connect(
            self.db_path,
            timeout=30,
            check_same_thread=False,
            isolation_level=None,  # autocommit off by default
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    def init_db(self) -> None:
        """Initialize database schema."""
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    # === Expectations ===

    def create_expectation(self, params: CreateExpectationParams) -> None:
        """Create a new expectation."""
        t = now_i()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO expectations
                   (id, type, name, expected_interval_s, tolerance_s,
                    params_json, owner_email, is_enabled, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                (
                    params.exp_id, params.exp_type, params.name,
                    params.expected_interval_s, params.tolerance_s,
                    params.params_json, params.owner_email, t, t
                ),
            )
            conn.commit()

    def get_expectation(self, exp_id: str) -> Optional[ExpectationRow]:
        """Retrieve an expectation by ID."""
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM expectations WHERE id = ?", (exp_id,)
            ).fetchone()

    def list_enabled_expectations(self) -> List[ExpectationRow]:
        """List all enabled expectations."""
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM expectations WHERE is_enabled = 1"
            ).fetchall()

    def set_enabled(self, exp_id: str, enabled: bool) -> bool:
        """Enable or disable an expectation. Returns True if updated."""
        with self._conn() as conn:
            cursor = conn.execute(
                "UPDATE expectations SET is_enabled = ?, updated_at = ? WHERE id = ?",
                (1 if enabled else 0, now_i(), exp_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    # === Observations ===

    def add_observation(
        self, exp_id: str, kind: str, meta_json: Optional[str] = None
    ) -> int:
        """Record an observation. Returns the observation ID."""
        t = now_i()
        with self._conn() as conn:
            cursor = conn.execute(
                """INSERT INTO observations (expectation_id, kind, observed_at, meta_json)
                   VALUES (?, ?, ?, ?)""",
                (exp_id, kind, t, meta_json),
            )
            conn.commit()
            return cursor.lastrowid or 0

    def recent_observations(
        self, exp_id: str, limit: int = 50
    ) -> List[ObservationRow]:
        """Get recent observations for an expectation, newest first."""
        with self._conn() as conn:
            return conn.execute(
                """SELECT * FROM observations
                   WHERE expectation_id = ?
                   ORDER BY observed_at DESC
                   LIMIT ?""",
                (exp_id, limit),
            ).fetchall()

    def last_observation_time(
        self, exp_id: str, kind: Optional[str] = None
    ) -> Optional[Timestamp]:
        """Get the timestamp of the most recent observation."""
        with self._conn() as conn:
            if kind:
                row = conn.execute(
                    """SELECT observed_at FROM observations
                       WHERE expectation_id = ? AND kind = ?
                       ORDER BY observed_at DESC LIMIT 1""",
                    (exp_id, kind),
                ).fetchone()
            else:
                row = conn.execute(
                    """SELECT observed_at FROM observations
                       WHERE expectation_id = ?
                       ORDER BY observed_at DESC LIMIT 1""",
                    (exp_id,),
                ).fetchone()
            return int(row["observed_at"]) if row else None

    # === Alert Trials ===

    def create_trial(
        self, trial_id: str, exp_id: str, meta_json: str
    ) -> None:
        """Create a new alert trial (synthetic test)."""
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO alert_trials
                   (id, expectation_id, sent_at, acked_at, status, meta_json)
                   VALUES (?, ?, ?, NULL, 'pending', ?)""",
                (trial_id, exp_id, now_i(), meta_json),
            )
            conn.commit()

    def ack_trial(self, trial_id: str) -> bool:
        """
        Acknowledge a pending trial.
        Returns True if acknowledged, False if not found or not pending.
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT status FROM alert_trials WHERE id = ?", (trial_id,)
            ).fetchone()
            if not row or row["status"] != "pending":
                return False
            conn.execute(
                "UPDATE alert_trials SET acked_at = ?, status = 'acked' WHERE id = ?",
                (now_i(), trial_id),
            )
            conn.commit()
            return True

    def pending_trials(self, exp_id: str) -> List[TrialRow]:
        """Get all pending trials for an expectation."""
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM alert_trials WHERE expectation_id = ? AND status = 'pending'",
                (exp_id,),
            ).fetchall()

    def expire_trial(self, trial_id: str) -> None:
        """Mark a pending trial as expired."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE alert_trials SET status = 'expired' WHERE id = ? AND status = 'pending'",
                (trial_id,),
            )
            conn.commit()

    # === Violations ===

    def open_violation(
        self, exp_id: str, code: str
    ) -> Optional[ViolationRow]:
        """Get the most recent open violation of a given code."""
        with self._conn() as conn:
            return conn.execute(
                """SELECT * FROM violations
                   WHERE expectation_id = ? AND code = ? AND is_open = 1
                   ORDER BY detected_at DESC LIMIT 1""",
                (exp_id, code),
            ).fetchone()

    def create_violation(
        self, exp_id: str, code: str, message: str, evidence_json: str
    ) -> int:
        """Create a new violation. Returns the violation ID."""
        with self._conn() as conn:
            cursor = conn.execute(
                """INSERT INTO violations
                   (expectation_id, detected_at, code, message, evidence_json, is_open, last_notified_at)
                   VALUES (?, ?, ?, ?, ?, 1, NULL)""",
                (exp_id, now_i(), code, message, evidence_json),
            )
            conn.commit()
            return cursor.lastrowid or 0

    def close_violations(self, exp_id: str, codes: List[str]) -> int:
        """Close open violations matching the given codes. Returns count closed."""
        if not codes:
            return 0
        placeholders = ",".join(["?"] * len(codes))
        with self._conn() as conn:
            cursor = conn.execute(
                f"""UPDATE violations SET is_open = 0
                    WHERE expectation_id = ? AND is_open = 1 AND code IN ({placeholders})""",
                [exp_id] + codes,
            )
            conn.commit()
            return cursor.rowcount

    def mark_notified(self, viol_id: int) -> None:
        """Mark a violation as notified."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE violations SET last_notified_at = ? WHERE id = ?",
                (now_i(), viol_id),
            )
            conn.commit()

    def open_violations_count(self, exp_id: Optional[str] = None) -> int:
        """Count open violations, optionally filtered by expectation."""
        with self._conn() as conn:
            if exp_id:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM violations WHERE expectation_id = ? AND is_open = 1",
                    (exp_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM violations WHERE is_open = 1"
                ).fetchone()
            return int(row["cnt"]) if row else 0
