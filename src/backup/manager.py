import time
import uuid
import logging
from src.common.types import JulesPath, RecoveryID
from src.common.errors import BackupVerificationError, GatewayError

logger = logging.getLogger(__name__)

class BackupManager:
    """
    Manages the creation and cryptographic verification of recovery points
    before destructive mutations are permitted.
    """

    def __init__(self, storage_adapter, jules_zone_root: str):
        # Allow the backup manager to bypass namespace restrictions to perform its duty
        self.storage = storage_adapter
        # The isolated prefix mapping for backup objects.
        # By contract, this is inaccessible via ordinary Jules token read/writes.
        self.recovery_prefix = ".xpool_recovery/"
        self.jules_zone_root = jules_zone_root

    def create_recovery_point(self, original_path: JulesPath) -> RecoveryID:
        try:
            rel = original_path.canonical_path.relative_to(self.jules_zone_root).as_posix()
        except ValueError:
            raise GatewayError("Path traversal prevented during backup generation", code=403)

        try:
            # We use backend hashing to prevent OOM vulnerabilities and binary-read corruption
            original_hash = self.storage.hash(original_path, "sha256")
        except FileNotFoundError:
            raise BackupVerificationError("Cannot backup a missing file. Ensure caller handles CREATE_ONLY correctly.")
        except Exception as e:
            raise BackupVerificationError(f"Failed to hash original object for backup: {e}")

        timestamp = int(time.time())
        unique_id = str(uuid.uuid4())
        flat_name = rel.replace('/', '_')
        recovery_id = RecoveryID(f"{timestamp}_{unique_id}")

        backup_path_raw = f"{self.jules_zone_root}/{self.recovery_prefix}{recovery_id}_{flat_name}"
        backup_path = JulesPath(backup_path_raw)

        try:
            # Perform a backend copy using internal RC dispatch to bypass gateway public limits safely
            src_remote = self.storage._get_remote_path(original_path)
            # We calculate dst_remote manually because _get_remote_path strictly blocks .xpool_recovery
            dst_remote = backup_path.canonical_path.relative_to(self.jules_zone_root).as_posix()

            payload_copy = {
                "srcFs": self.storage.remote_name,
                "srcRemote": src_remote,
                "dstFs": self.storage.remote_name,
                "dstRemote": dst_remote
            }
            self.storage._execute_rc("operations/copyfile", payload=payload_copy, retries=3)

            # Hash the backup to verify integrity internally
            payload_hash = {
                "fs": self.storage.remote_name,
                "remote": dst_remote,
                "hashType": "sha256"
            }
            res = self.storage._execute_rc("operations/hashsumfile", payload=payload_hash, retries=3)
            backup_hash = res.get("hash", "")

            if original_hash != backup_hash:
                raise BackupVerificationError("Hash mismatch between original data and written backup")

        except Exception as e:
            # Deterministic artifact cleanup for failed backups
            try:
                dst_remote = backup_path.canonical_path.relative_to(self.jules_zone_root).as_posix()
                payload_del = {
                    "fs": self.storage.remote_name,
                    "remote": dst_remote
                }
                self.storage._execute_rc("operations/deletefile", payload=payload_del, retries=3)
            except Exception as cleanup_err:
                logger.error(f"Failed to cleanup orphaned backup {backup_path}: {cleanup_err}")

            if not isinstance(e, BackupVerificationError):
                raise BackupVerificationError(f"Backup storage transaction failed: {e}")
            raise e

        logger.info(f"Recovery point created securely: {recovery_id}")
        return recovery_id
