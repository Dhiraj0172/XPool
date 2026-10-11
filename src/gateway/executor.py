import threading
from typing import Callable, Any
from src.common.types import JulesPath
from src.common.errors import GatewayError, BackupVerificationError
from src.gateway.state import OperationTracker, OpState
from src.backup.manager import BackupManager

class SingleAuthoritativeExecutor:
    """
    Serializes mutative operations to prevent local TOCTOU races.
    Explicit Limitation: This application-level lock does NOT prevent races
    involving external writers bypassing the gateway or delayed backend mutations,
    as the rclone backend lacks atomic conditional writes.
    """
    def __init__(self, storage_adapter, backup_manager: BackupManager, tracker: OperationTracker):
        self.storage = storage_adapter
        self.backup_mgr = backup_manager
        self.tracker = tracker
        self._global_mutation_lock = threading.Lock()

    def execute_write(self, idempotency_key: str, target_path: JulesPath, data: bytes, principal_id: str) -> bool:
        # Deduplicate requests idempotently
        if not self.tracker.begin_operation(idempotency_key, str(target_path.canonical_path), principal_id):
            op = self.tracker.get_operation(idempotency_key)
            if op and op['state'] == OpState.DONE.value:
                return True
            raise GatewayError("Duplicate or conflicting request in progress", code=409)

        # Single Authoritative execution ensures no local TOCTOU races
        with self._global_mutation_lock:
            self.tracker.update_state(idempotency_key, OpState.LOCKED)

            try:
                # 1. Identify Source
                try:
                    original_hash = self.storage.hash(target_path, "sha256")
                except FileNotFoundError:
                    original_hash = "CREATE_ONLY"

                self.tracker.update_state(idempotency_key, OpState.SOURCE_VERSION_IDENTIFIED, original_hash=original_hash)

                # 2. Backup if necessary
                if original_hash != "CREATE_ONLY":
                    self.tracker.update_state(idempotency_key, OpState.BACKUP_REQUIRED)
                    self.tracker.update_state(idempotency_key, OpState.BACKUP_RUNNING)

                    try:
                        backup_id = self.backup_mgr.create_recovery_point(target_path)
                        self.tracker.update_state(idempotency_key, OpState.BACKUP_VERIFIED, backup_id=str(backup_id))
                    except BackupVerificationError as e:
                        # Fail closed
                        self.tracker.update_state(idempotency_key, OpState.FAILED)
                        raise

                # 3. Re-evaluate source state
                # By holding the global lock, we ensure no other Gateway thread altered it.
                # We re-hash to catch immediate local/shared FS anomalies.
                # LIMITATION: External writers or delayed packets bypassing this gateway
                # can still mutate the backend immediately after this check, before write() lands.
                # TOCTOU safety is BLOCKED for external/uncontrolled writers.
                try:
                    reval_hash = self.storage.hash(target_path, "sha256")
                except FileNotFoundError:
                    reval_hash = "CREATE_ONLY"

                if reval_hash != original_hash:
                    # Source changed concurrently (external writer or mock injection)
                    self.tracker.update_state(idempotency_key, OpState.FAILED)
                    raise GatewayError("Source state mutated concurrently before write", code=409)

                self.tracker.update_state(idempotency_key, OpState.MUTATION_ALLOWED)
                self.tracker.update_state(idempotency_key, OpState.MUTATION_EXECUTING)

                try:
                    write_success = self.storage.write(target_path, data)
                except Exception:
                    # Network crash or ambiguous failure
                    self.tracker.update_state(idempotency_key, OpState.UNCERTAIN)
                    raise GatewayError("Backend outcome uncertain due to network/execution failure", code=500)

                if write_success:
                    import hashlib
                    final_hash = hashlib.sha256(data).hexdigest()
                    self.tracker.update_state(idempotency_key, OpState.MUTATION_CONFIRMED, final_hash=final_hash)
                    self.tracker.update_state(idempotency_key, OpState.DONE)
                    return True
                else:
                    self.tracker.update_state(idempotency_key, OpState.UNCERTAIN)
                    raise GatewayError("Write returned False but outcome uncertain", code=500)

            except Exception as e:
                # If we crash *after* we began MUTATION_EXECUTING but before DONE,
                # we must treat the backend state as UNCERTAIN, not safely FAILED.
                op = self.tracker.get_operation(idempotency_key)
                if op:
                    current = op['state']
                    if current == OpState.MUTATION_EXECUTING.value:
                        try:
                            self.tracker.update_state(idempotency_key, OpState.UNCERTAIN)
                        except Exception:
                            pass # We are probably already crashing (e.g. Disk Full)
                    elif current not in [OpState.UNCERTAIN.value, OpState.DONE.value, OpState.FAILED.value]:
                        try:
                            self.tracker.update_state(idempotency_key, OpState.FAILED)
                        except Exception:
                            pass
                raise
