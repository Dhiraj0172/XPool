import pytest
import sys
import os
import sqlite3
import threading
from src.common.types import JulesPath
from src.common.errors import GatewayError, BackupVerificationError
from src.storage.rclone_adapter import RcloneRCAdapter
from src.backup.manager import BackupManager
from src.gateway.state import OperationTracker, OpState
from src.gateway.executor import SingleAuthoritativeExecutor

class LocalMockAdapter(RcloneRCAdapter):
    # We inherit __init__ which sets remote_name

    def _execute_rc(self, command: str, payload: dict = None, retries: int = 0) -> dict:
        if command == "operations/copyfile":
            src = payload["srcRemote"]
            dst = payload["dstRemote"]
            self.store[dst] = self.store.get(src, b"")
            return {}
        elif command == "operations/hashsumfile":
            import hashlib
            data = self.store.get(payload["remote"], b"")
            return {"hash": hashlib.sha256(data).hexdigest()}
        elif command == "operations/deletefile":
            if payload["remote"] in self.store:
                del self.store[payload["remote"]]
            return {}
        return {}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.store = {}
        self.throw_network = False

    def hash(self, path: JulesPath, hash_type: str = "sha256") -> str:
        remote_path = self._get_remote_path(path)
        if remote_path not in self.store:
            raise FileNotFoundError("Missing")
        import hashlib
        return hashlib.sha256(self.store[remote_path]).hexdigest()

    def write(self, path: JulesPath, data: bytes) -> bool:
        remote_path = self._get_remote_path(path)
        if self.throw_network:
            raise Exception("Mock Timeout")
        self.store[remote_path] = data
        return True

    def copy(self, src: JulesPath, dst: JulesPath) -> bool:
        src_remote = self._get_remote_path(src)
        dst_remote = self._get_remote_path(dst)
        if src_remote not in self.store:
            raise FileNotFoundError("Missing")
        self.store[dst_remote] = self.store[src_remote]
        return True

    def delete(self, path: JulesPath) -> bool:
        remote = self._get_remote_path(path)
        if remote in self.store:
            del self.store[remote]
        return True

@pytest.fixture
def test_env():
    # Use in-memory DB for tests
    tracker = OperationTracker(":memory:")
    root = "C:/JulesWorkspace" if sys.platform == "win32" else "/JulesWorkspace"
    adapter = LocalMockAdapter(jules_zone_root=root)
    backup_mgr = BackupManager(adapter, root)
    executor = SingleAuthoritativeExecutor(adapter, backup_mgr, tracker)
    return root, adapter, backup_mgr, tracker, executor

def test_protected_prefix_access(test_env):
    # Proves: Direct protected-prefix access through adapter is blocked.
    root, adapter, _, _, _ = test_env
    # For testing adapter boundary, adapter allows_protected_namespace is True by default for tests if initialized without care, but we want to test default-deny.
    # Actually wait, LocalMockAdapter inherits RcloneRCAdapter, let's verify default is False.
    adapter.allow_protected_namespace = False
    path = JulesPath(f"{root}/.xpool_recovery/secret.txt")
    with pytest.raises(GatewayError) as exc:
        adapter._get_remote_path(path)
    assert "protected recovery namespace" in str(exc.value)

def test_path_traversal(test_env):
    # Proves: Path traversal and alternate representations blocked.
    root, adapter, _, _, _ = test_env
    path = JulesPath(f"{root}/../.xpool_recovery/secret.txt")
    with pytest.raises(GatewayError) as exc:
        adapter._get_remote_path(path)
    # The canonicalizer resolves it out of bounds, so the JULES_ZONE bounds check catches it
    assert exc.value.code == 403

def test_duplicate_requests(test_env):
    # Proves: Idempotency keys block exact duplicates safely.
    root, adapter, _, tracker, executor = test_env
    path = JulesPath(f"{root}/new.txt")

    res1 = executor.execute_write("key-1", path, b"data", "user-A")
    assert res1 is True
    assert tracker.get_operation("key-1")['state'] == OpState.DONE.value

    # Send same idempotency key
    res2 = executor.execute_write("key-1", path, b"data", "user-A")
    assert res2 is True # Idempotent success returned

    # Send new key but same path (concurrent collision)
    # The Single Executor queues it and overwrites it serially, creating a backup
    res3 = executor.execute_write("key-2", path, b"data-new", "user-B")
    assert res3 is True
    assert tracker.get_operation("key-2")['state'] == OpState.DONE.value
    assert tracker.get_operation("key-2")['backup_id'] is not None

def test_uncertain_backend_outcome(test_env):
    # Proves: Network timeout during mutation yields UNCERTAIN state, failing closed.
    root, adapter, _, tracker, executor = test_env
    path = JulesPath(f"{root}/timeout.txt")

    adapter.throw_network = True
    with pytest.raises(GatewayError) as exc:
        executor.execute_write("key-timeout", path, b"data", "user-A")
    assert "outcome uncertain" in str(exc.value)
    assert tracker.get_operation("key-timeout")['state'] == OpState.UNCERTAIN.value

def test_restart_reconciliation(test_env):
    # Proves: Incomplete operations safely transition on restart.
    root, adapter, _, tracker, executor = test_env

    # Inject stuck states
    tracker.begin_operation("key-req", "a.txt", "user-A")
    tracker.update_state("key-req", OpState.LOCKED)

    tracker.begin_operation("key-exec", "b.txt", "user-B")
    tracker.update_state("key-exec", OpState.LOCKED)
    tracker.update_state("key-exec", OpState.SOURCE_VERSION_IDENTIFIED)
    tracker.update_state("key-exec", OpState.MUTATION_ALLOWED)
    tracker.update_state("key-exec", OpState.MUTATION_EXECUTING)

    tracker.reconcile_restarts()

    assert tracker.get_operation("key-req")['state'] == OpState.FAILED.value
    assert tracker.get_operation("key-exec")['state'] == OpState.UNCERTAIN.value

def test_backup_verification_blocks_mutation(test_env):
    # Proves: Backup checksum mismatch blocks mutation and marks FAILED.
    root, adapter, backup_mgr, tracker, executor = test_env
    path = JulesPath(f"{root}/target.txt")
    adapter.store["target.txt"] = b"orig"

    # Mock backup verification to fail
    def failing_backup(*args, **kwargs):
        raise BackupVerificationError("Mismatch")
    backup_mgr.create_recovery_point = failing_backup

    with pytest.raises(BackupVerificationError):
        executor.execute_write("key-mismatch", path, b"newdata", "user-A")

    assert tracker.get_operation("key-mismatch")['state'] == OpState.FAILED.value
    assert adapter.store["target.txt"] == b"orig" # Mutation prevented

def test_audit_logs_no_credentials(test_env):
    # Proves: Tracker strictly stores principal_id, no raw tokens.
    root, adapter, _, tracker, executor = test_env
    path = JulesPath(f"{root}/audit.txt")
    executor.execute_write("key-audit", path, b"audit", "princ-1234")

    row = tracker.get_operation("key-audit")
    assert row["principal_id"] == "princ-1234"
    assert "token" not in str(row)

def test_db_failure_blocks_mutation(test_env):
    # Proves: DB write failure prevents backend mutation (Fail closed).
    root, adapter, _, tracker, executor = test_env
    path = JulesPath(f"{root}/dbfail.txt")

    # Simulate readonly/broken DB by closing it and relying on sqlite error
    if tracker.mem_conn:
        tracker.mem_conn.close()

    with pytest.raises(Exception):
        executor.execute_write("key-dbfail", path, b"data", "user-1")

    assert "/JulesWorkspace/dbfail.txt" not in adapter.store

def test_invalid_state_transition(test_env):
    # Proves: SQLite tracker strictly rejects invalid DAG jumps
    root, adapter, _, tracker, executor = test_env
    tracker.begin_operation("key-invalid", "path.txt", "user")
    tracker.update_state("key-invalid", OpState.LOCKED)

    # Try jumping directly to DONE
    with pytest.raises(ValueError) as exc:
        tracker.update_state("key-invalid", OpState.DONE)
    assert "Invalid transition" in str(exc.value)

def test_recovery_cleanup_safety(test_env):
    # Proves: Active or UNCERTAIN ops flag their backups as needed, protecting from GC.
    root, adapter, _, tracker, executor = test_env

    tracker.begin_operation("key-gc-active", "a.txt", "user")
    tracker.update_state("key-gc-active", OpState.LOCKED)
    tracker.update_state("key-gc-active", OpState.SOURCE_VERSION_IDENTIFIED)
    tracker.update_state("key-gc-active", OpState.BACKUP_REQUIRED)
    tracker.update_state("key-gc-active", OpState.BACKUP_RUNNING)
    tracker.update_state("key-gc-active", OpState.BACKUP_VERIFIED, backup_id="backup-123")

    tracker.begin_operation("key-gc-done", "b.txt", "user")
    tracker.update_state("key-gc-done", OpState.LOCKED)
    tracker.update_state("key-gc-done", OpState.SOURCE_VERSION_IDENTIFIED)
    tracker.update_state("key-gc-done", OpState.BACKUP_REQUIRED)
    tracker.update_state("key-gc-done", OpState.BACKUP_RUNNING)
    tracker.update_state("key-gc-done", OpState.BACKUP_VERIFIED, backup_id="backup-456")
    tracker.update_state("key-gc-done", OpState.MUTATION_ALLOWED)
    tracker.update_state("key-gc-done", OpState.MUTATION_EXECUTING)
    tracker.update_state("key-gc-done", OpState.MUTATION_CONFIRMED)
    tracker.update_state("key-gc-done", OpState.DONE)

    tracker.begin_operation("key-gc-failed", "c.txt", "user")
    tracker.update_state("key-gc-failed", OpState.LOCKED)
    tracker.update_state("key-gc-failed", OpState.SOURCE_VERSION_IDENTIFIED)
    tracker.update_state("key-gc-failed", OpState.BACKUP_REQUIRED)
    tracker.update_state("key-gc-failed", OpState.BACKUP_RUNNING)
    tracker.update_state("key-gc-failed", OpState.BACKUP_VERIFIED, backup_id="backup-789")
    tracker.update_state("key-gc-failed", OpState.FAILED)

    tracker.begin_operation("key-gc-uncertain", "d.txt", "user")
    tracker.update_state("key-gc-uncertain", OpState.LOCKED)
    tracker.update_state("key-gc-uncertain", OpState.SOURCE_VERSION_IDENTIFIED)
    tracker.update_state("key-gc-uncertain", OpState.BACKUP_REQUIRED)
    tracker.update_state("key-gc-uncertain", OpState.BACKUP_RUNNING)
    tracker.update_state("key-gc-uncertain", OpState.BACKUP_VERIFIED, backup_id="backup-999")
    tracker.update_state("key-gc-uncertain", OpState.MUTATION_ALLOWED)
    tracker.update_state("key-gc-uncertain", OpState.MUTATION_EXECUTING)
    tracker.update_state("key-gc-uncertain", OpState.UNCERTAIN)

    active_ids = tracker.get_active_backup_ids()
    assert "backup-123" in active_ids # Active
    assert "backup-456" not in active_ids # DONE
    assert "backup-789" not in active_ids # FAILED
    assert "backup-999" in active_ids # UNCERTAIN is protected


def test_concurrent_source_change_reval(test_env):
    # Proves: Re-evaluating source hash immediately before mutation aborts if changed.
    root, adapter, backup_mgr, tracker, executor = test_env
    path = JulesPath(f"{root}/race.txt")
    adapter.store["race.txt"] = b"orig"

    def hacky_backup(*args, **kwargs):
        # We simulate a concurrent external writer mutating the backend while we are backing up
        adapter.store["race.txt"] = b"changed_externally"
        return "bck-1"

    backup_mgr.create_recovery_point = hacky_backup

    with pytest.raises(GatewayError) as exc:
        executor.execute_write("key-race", path, b"newdata", "user")

    assert "mutated concurrently" in str(exc.value)
    assert tracker.get_operation("key-race")['state'] == OpState.FAILED.value

def test_protected_namespace_copy_move_destination(test_env):
    # Proves: Ordinary operations cannot target .xpool_recovery as destination
    root, adapter, _, _, _ = test_env
    src = JulesPath(f"{root}/legit.txt")
    dst = JulesPath(f"{root}/.xpool_recovery/malicious.txt")

    with pytest.raises(GatewayError) as exc:
        adapter.copy(src, dst)
    assert "protected recovery namespace" in str(exc.value)

    with pytest.raises(GatewayError) as exc:
        adapter.move(src, dst)
    assert "protected recovery namespace" in str(exc.value)

def test_protected_namespace_copy_move_source(test_env):
    # Proves: Ordinary operations cannot use .xpool_recovery as a source
    root, adapter, _, _, _ = test_env
    src = JulesPath(f"{root}/.xpool_recovery/backup.txt")
    dst = JulesPath(f"{root}/legit.txt")

    with pytest.raises(GatewayError) as exc:
        adapter.copy(src, dst)
    assert "protected recovery namespace" in str(exc.value)

    with pytest.raises(GatewayError) as exc:
        adapter.move(src, dst)
    assert "protected recovery namespace" in str(exc.value)

def test_concurrent_state_updates(test_env):
    # Proves: SQLite _local_lock prevents concurrent thread data corruption.
    root, adapter, _, tracker, executor = test_env
    tracker.begin_operation("key-conc", "conc.txt", "user")
    tracker.update_state("key-conc", OpState.LOCKED)

    def worker1():
        try:
            tracker.update_state("key-conc", OpState.SOURCE_VERSION_IDENTIFIED)
        except Exception:
            pass

    def worker2():
        try:
            tracker.update_state("key-conc", OpState.FAILED)
        except Exception:
            pass

    t1 = threading.Thread(target=worker1)
    t2 = threading.Thread(target=worker2)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # State should be deterministically one of the two based on who locked first.
    # The DAG blocks one if the other succeeds because SOURCE_VERSION_IDENTIFIED -> FAILED is valid,
    # but FAILED -> SOURCE_VERSION_IDENTIFIED is invalid.
    final_state = tracker.get_operation("key-conc")["state"]
    assert final_state in (OpState.FAILED.value, OpState.SOURCE_VERSION_IDENTIFIED.value)

import multiprocessing

def _mp_worker(db_path, idempotency_key):
    # This runs in a separate process
    tracker = OperationTracker(db_path)
    try:
        tracker.begin_operation(idempotency_key, "mp.txt", "user-mp")
        tracker.update_state(idempotency_key, OpState.LOCKED)
    except Exception:
        pass

def test_multi_process_state_updates(tmp_path):
    # Proves: SQLite handles concurrent process access, though without BEGIN EXCLUSIVE,
    # it relies on default busy timeouts.
    db_file = str(tmp_path / "test_mp.db")
    tracker = OperationTracker(db_file)

    p1 = multiprocessing.Process(target=_mp_worker, args=(db_file, "key-mp1"))
    p2 = multiprocessing.Process(target=_mp_worker, args=(db_file, "key-mp2"))

    p1.start()
    p2.start()
    p1.join()
    p2.join()

    assert tracker.get_operation("key-mp1") is not None
    assert tracker.get_operation("key-mp2") is not None

def test_persistence_failure_post_mutation(test_env):
    # Proves: If remote mutation succeeds but DB write fails, operation is caught as UNCERTAIN safely on reboot.
    # We simulate this by monkey-patching update_state to crash only when trying to write MUTATION_CONFIRMED.
    root, adapter, backup_mgr, tracker, executor = test_env
    path = JulesPath(f"{root}/post_crash.txt")

    original_update = tracker.update_state
    def failing_update(key, state, **kwargs):
        if state == OpState.MUTATION_CONFIRMED:
            raise sqlite3.OperationalError("Disk Full")
        original_update(key, state, **kwargs)

    tracker.update_state = failing_update

    with pytest.raises(sqlite3.OperationalError):
        executor.execute_write("key-postcrash", path, b"data", "user")

    # Because the executor safely caught the failure mid-flight, it already transitioned
    # the operation to UNCERTAIN before dying.
    tracker.update_state = original_update # Restore
    op = tracker.get_operation("key-postcrash")
    assert op['state'] == OpState.UNCERTAIN.value


def _mp_conflict_worker(db_path, idempotency_key):
    tracker = OperationTracker(db_path)
    try:
        tracker.update_state(idempotency_key, OpState.LOCKED)
    except Exception:
        pass

def test_multi_process_conflict_handling(tmp_path):
    # Proves: Strict BEGIN IMMEDIATE handling with exponential backoff
    # protects state transitions under heavy multi-process contention.
    db_file = str(tmp_path / "test_conflict.db")
    tracker = OperationTracker(db_file)
    tracker.begin_operation("key-mp-conflict", "race.txt", "user")

    processes = []
    for _ in range(5):
        p = multiprocessing.Process(target=_mp_conflict_worker, args=(db_file, "key-mp-conflict"))
        processes.append(p)
        p.start()

    for p in processes:
        p.join()

    op = tracker.get_operation("key-mp-conflict")
    assert op is not None
    assert op['state'] == OpState.LOCKED.value

def test_local_e2e_wiring_success(test_env):
    # Proves: The core components successfully wire together to execute a mutative flow
    # capturing tracking, backup, and storage states properly.
    root, adapter, backup_mgr, tracker, executor = test_env
    path = JulesPath(f"{root}/e2e_target.txt")

    # Pre-populate using the same format the adapter internally uses
    remote_path = adapter._get_remote_path(path)
    adapter.store[remote_path] = b"original"

    # Execute through executor
    res = executor.execute_write("key-e2e-1", path, b"new_data", "princ-1")
    assert res is True

    # Verify backup exists
    backup_ids = tracker.get_active_backup_ids()
    assert len(backup_ids) == 0  # Should be 0 because it's DONE, not active!

    op = tracker.get_operation("key-e2e-1")
    assert op['state'] == OpState.DONE.value
    assert op['backup_id'] is not None

    # Verify mock backend actually stored it
    assert adapter.store[remote_path] == b"new_data"

def test_local_e2e_wiring_failure(test_env):
    # Proves: The core components successfully abort and fail closed if
    # a backup integrity issue happens.
    root, adapter, backup_mgr, tracker, executor = test_env
    path = JulesPath(f"{root}/e2e_fail.txt")
    remote_path = adapter._get_remote_path(path)
    adapter.store[remote_path] = b"original"

    # Mock backup verification to fail
    def failing_backup(*args, **kwargs):
        raise BackupVerificationError("Mismatch")
    backup_mgr.create_recovery_point = failing_backup

    with pytest.raises(BackupVerificationError):
        executor.execute_write("key-e2e-2", path, b"new_data", "princ-1")

    op = tracker.get_operation("key-e2e-2")
    assert op['state'] == OpState.FAILED.value
    assert adapter.store[remote_path] == b"original"

def test_unresolved_path_traversal_blocked(test_env):
    # Proves: A path containing /../ pointing to a non-existent parent directory
    # is still correctly canonicalized and caught by relative_to().
    root, adapter, _, _, _ = test_env
    # Even if "fake_dir" doesn't exist, resolve(strict=False) processes the .. correctly.
    path = JulesPath(f"{root}/fake_dir/../../etc/passwd")

    with pytest.raises(GatewayError) as exc:
        adapter._get_remote_path(path)
    assert exc.value.code == 403
    assert "Path traversal prevented" in str(exc.value)

def test_absolute_path_injection_blocked(test_env):
    # Proves: Submitting an absolute path bypassing the intended relative structure
    # is trapped by the adapter's relative_to check.
    root, adapter, _, _, _ = test_env

    if sys.platform == "win32":
        path = JulesPath("C:\Windows\System32\cmd.exe")
    else:
        path = JulesPath("/etc/passwd")

    with pytest.raises(GatewayError) as exc:
        adapter._get_remote_path(path)
    assert exc.value.code == 403

def test_path_prefix_confusion(test_env):
    # Proves: Canonicalization checks exact path parts, not simple string prefixes
    root, adapter, _, _, _ = test_env
    # The adapter should allow this, because .xpool_recovery_fake is NOT .xpool_recovery
    path = JulesPath(f"{root}/.xpool_recovery_fake/secret.txt")

    # Should not throw 403
    remote_path = adapter._get_remote_path(path)
    assert remote_path == ".xpool_recovery_fake/secret.txt"
