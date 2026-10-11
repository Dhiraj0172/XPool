import sqlite3
import threading
from enum import Enum
import time

class OpState(Enum):
    REQUESTED = "REQUESTED"
    LOCKED = "LOCKED"
    SOURCE_VERSION_IDENTIFIED = "SOURCE_VERSION_IDENTIFIED"
    BACKUP_REQUIRED = "BACKUP_REQUIRED"
    BACKUP_RUNNING = "BACKUP_RUNNING"
    BACKUP_VERIFIED = "BACKUP_VERIFIED"
    MUTATION_ALLOWED = "MUTATION_ALLOWED"
    MUTATION_EXECUTING = "MUTATION_EXECUTING"
    MUTATION_CONFIRMED = "MUTATION_CONFIRMED"
    DONE = "DONE"
    FAILED = "FAILED"
    ABORTED = "ABORTED"
    UNCERTAIN = "UNCERTAIN"

VALID_TRANSITIONS = {
    OpState.REQUESTED: {OpState.LOCKED, OpState.FAILED, OpState.ABORTED},
    OpState.LOCKED: {OpState.SOURCE_VERSION_IDENTIFIED, OpState.FAILED},
    OpState.SOURCE_VERSION_IDENTIFIED: {OpState.BACKUP_REQUIRED, OpState.MUTATION_ALLOWED, OpState.FAILED},
    OpState.BACKUP_REQUIRED: {OpState.BACKUP_RUNNING, OpState.FAILED},
    OpState.BACKUP_RUNNING: {OpState.BACKUP_VERIFIED, OpState.FAILED},
    OpState.BACKUP_VERIFIED: {OpState.MUTATION_ALLOWED, OpState.FAILED},
    OpState.MUTATION_ALLOWED: {OpState.MUTATION_EXECUTING, OpState.FAILED},
    OpState.MUTATION_EXECUTING: {OpState.MUTATION_CONFIRMED, OpState.UNCERTAIN, OpState.FAILED},
    OpState.MUTATION_CONFIRMED: {OpState.DONE, OpState.UNCERTAIN, OpState.FAILED},
    # Terminals
    OpState.DONE: set(),
    OpState.FAILED: set(),
    OpState.ABORTED: set(),
    OpState.UNCERTAIN: {OpState.DONE, OpState.FAILED} # Allowed via reconciliation
}
class OperationTracker:
    def __init__(self, db_path: str = "operations.db"):
        self.db_path = db_path
        self._local_lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        # We must keep the connection open for memory DBs so the table persists
        self.mem_conn = sqlite3.connect(self.db_path, check_same_thread=False) if self.db_path == ":memory:" else None

        with self._local_lock, (self.mem_conn or sqlite3.connect(self.db_path)) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS operations (
                    idempotency_key TEXT PRIMARY KEY,
                    target_path TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    backup_id TEXT,
                    original_hash TEXT,
                    final_hash TEXT,
                    last_updated REAL NOT NULL
                )
            ''')
            conn.commit()

    def begin_operation(self, idempotency_key: str, target_path: str, principal_id: str) -> bool:
        retries = 10
        for attempt in range(retries):
            try:
                with self._local_lock, (self.mem_conn or sqlite3.connect(self.db_path, isolation_level=None, timeout=10.0)) as conn:
                    cursor = conn.cursor()
                    try:
                        cursor.execute("BEGIN IMMEDIATE")
                        cursor.execute(
                            "INSERT INTO operations (idempotency_key, target_path, principal_id, state, last_updated) VALUES (?, ?, ?, ?, ?)",
                            (idempotency_key, target_path, principal_id, OpState.REQUESTED.value, time.time())
                        )
                        conn.commit()
                        return True
                    except sqlite3.IntegrityError:
                        conn.execute("ROLLBACK")
                        return False # Duplicate key
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and attempt < retries - 1:
                    time.sleep(0.1 * (2 ** attempt))
                    continue
                raise

    def update_state(self, idempotency_key: str, new_state: OpState, backup_id: str = None, original_hash: str = None, final_hash: str = None):
        retries = 10
        for attempt in range(retries):
            try:
                with self._local_lock, (self.mem_conn or sqlite3.connect(self.db_path, isolation_level=None, timeout=10.0)) as conn:
                    cursor = conn.cursor()
                    cursor.execute("BEGIN IMMEDIATE")

                    try:
                        # Atomic transition check
                        cursor.execute("SELECT state FROM operations WHERE idempotency_key = ?", (idempotency_key,))
                        row = cursor.fetchone()
                        if not row:
                            raise ValueError("Operation not found")
                        current_state = OpState(row[0])

                        if new_state not in VALID_TRANSITIONS.get(current_state, set()):
                            raise ValueError(f"Invalid transition from {current_state} to {new_state}")

                        updates = ["state = ?", "last_updated = ?"]
                        params = [new_state.value, time.time()]

                        if backup_id is not None:
                            updates.append("backup_id = ?")
                            params.append(backup_id)
                        if original_hash is not None:
                            updates.append("original_hash = ?")
                            params.append(original_hash)
                        if final_hash is not None:
                            updates.append("final_hash = ?")
                            params.append(final_hash)

                        params.append(idempotency_key)
                        query = f"UPDATE operations SET {', '.join(updates)} WHERE idempotency_key = ?"
                        cursor.execute(query, params)
                        if cursor.rowcount == 0:
                            raise ValueError("Operation not found")
                        conn.commit()
                        return
                    except Exception:
                        conn.execute("ROLLBACK")
                        raise
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and attempt < retries - 1:
                    time.sleep(0.1 * (2 ** attempt))
                    continue
                raise

    def get_operation(self, idempotency_key: str) -> dict:
        with self._local_lock, (self.mem_conn or sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM operations WHERE idempotency_key = ?", (idempotency_key,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_active_backup_ids(self) -> set:
        """
        Defines the recovery cleanup safety protocol.
        Returns a set of backup_ids that belong to operations which are NOT strictly FAILED or DONE.
        GC MUST NOT delete any backup_id returned by this method.
        Note: The actual background GC loop is NOT currently implemented.
        """
        with self._local_lock, (self.mem_conn or sqlite3.connect(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT backup_id FROM operations WHERE state NOT IN (?, ?) AND backup_id IS NOT NULL",
                (OpState.FAILED.value, OpState.DONE.value)
            )
            return {row[0] for row in cursor.fetchall()}

    def reconcile_restarts(self):
        """Identifies interrupted operations upon startup and transitions them safely."""
        with self._local_lock, (self.mem_conn or sqlite3.connect(self.db_path, isolation_level=None, timeout=30.0)) as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")

            # Anything between REQUESTED and MUTATION_ALLOWED transitions to FAILED
            safe_to_fail_states = [
                OpState.REQUESTED.value, OpState.LOCKED.value,
                OpState.SOURCE_VERSION_IDENTIFIED.value, OpState.BACKUP_REQUIRED.value,
                OpState.BACKUP_RUNNING.value, OpState.BACKUP_VERIFIED.value,
                OpState.MUTATION_ALLOWED.value
            ]
            placeholders = ','.join(['?'] * len(safe_to_fail_states))
            cursor.execute(
                f"UPDATE operations SET state = ?, last_updated = ? WHERE state IN ({placeholders})",
                [OpState.FAILED.value, time.time()] + safe_to_fail_states
            )

            # Anything executing transitions to UNCERTAIN
            cursor.execute(
                "UPDATE operations SET state = ?, last_updated = ? WHERE state = ?",
                (OpState.UNCERTAIN.value, time.time(), OpState.MUTATION_EXECUTING.value)
            )

            # Anything confirmed but un-audited (unlikely in this single-step DB) transitions to DONE
            cursor.execute(
                "UPDATE operations SET state = ?, last_updated = ? WHERE state = ?",
                (OpState.DONE.value, time.time(), OpState.MUTATION_CONFIRMED.value)
            )

            conn.commit()
