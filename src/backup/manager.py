import time
import uuid
import logging
from src.common.types import JulesPath, RecoveryID
from src.common.errors import BackupVerificationError, GatewayError
from src.dedup.cas import calculate_sha256

logger = logging.getLogger(__name__)

class BackupManager:
    """
    Manages the creation and cryptographic verification of recovery points
    before destructive mutations are permitted.
    """

    def __init__(self, storage_adapter, jules_zone_root: str):
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
            return RecoveryID("CREATE_ONLY")
        except Exception as e:
            raise BackupVerificationError(f"Failed to hash original object for backup: {e}")

        timestamp = int(time.time())
        unique_id = str(uuid.uuid4())
        flat_name = rel.replace('/', '_')
        recovery_id = RecoveryID(f"{timestamp}_{unique_id}")

        backup_path_raw = f"{self.jules_zone_root}/{self.recovery_prefix}{recovery_id}_{flat_name}"
        backup_path = JulesPath(backup_path_raw)

        try:
            # Perform a backend copy (avoids network transfer and memory bloat)
            copy_success = self.storage.copy(original_path, backup_path)
            if not copy_success:
                raise BackupVerificationError("Storage adapter rejected backup copy")

            # Hash the backup to verify integrity
            backup_hash = self.storage.hash(backup_path, "sha256")

            if original_hash != backup_hash:
                raise BackupVerificationError("Hash mismatch between original data and written backup")

        except Exception as e:
            # Deterministic artifact cleanup for failed backups
            try:
                self.storage.delete(backup_path)
            except Exception as cleanup_err:
                logger.error(f"Failed to cleanup orphaned backup {backup_path}: {cleanup_err}")

            if not isinstance(e, BackupVerificationError):
                raise BackupVerificationError(f"Backup storage transaction failed: {e}")
            raise e

        logger.info(f"Recovery point created securely: {recovery_id}")
        return recovery_id
