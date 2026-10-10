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
        """
        Executes the mandatory Pre-Mutation Backup Hook.
        1. Reads original content.
        2. Writes to an isolated recovery path.
        3. Reads the written backup back out and hashes it.
        4. Compares hash against the original to guarantee integrity.

        Raises BackupVerificationError if any step fails.
        """
        # We safely flatten the original canonical path relative string
        try:
            rel = original_path.canonical_path.relative_to(self.jules_zone_root).as_posix()
        except ValueError:
            raise GatewayError("Path traversal prevented during backup generation", code=403)

        try:
            original_content = self.storage.read(original_path)
            original_hash = calculate_sha256(original_content)
        except FileNotFoundError:
            # If the original file does not exist, the operation is a pure create,
            # not a destructive mutation. We return a blank recovery ID indicating safety.
            return RecoveryID("CREATE_ONLY")
        except Exception as e:
            raise BackupVerificationError(f"Failed to read original object for backup: {e}")

        # Generate isolated backup path
        timestamp = int(time.time())
        unique_id = str(uuid.uuid4())

        flat_name = rel.replace('/', '_')
        recovery_id = RecoveryID(f"{timestamp}_{unique_id}")

        # We use JulesPath but prefix it so the storage adapter maps it properly.
        # This isolates it inside the same base remote but out of the allowed user tree.
        backup_path_raw = f"{self.jules_zone_root}/{self.recovery_prefix}{recovery_id}_{flat_name}"
        backup_path = JulesPath(backup_path_raw)

        try:
            # Write backup to storage
            write_success = self.storage.write(backup_path, original_content)
            if not write_success:
                raise BackupVerificationError("Storage adapter rejected backup write")

            # Read back for integrity verification
            backup_content = self.storage.read(backup_path)
            backup_hash = calculate_sha256(backup_content)

            if original_hash != backup_hash:
                raise BackupVerificationError("Hash mismatch between original data and written backup")

        except Exception as e:
            # Any failure during write/verify mandates that we ABORT the sequence
            # and prevent the caller from proceeding with the destructive mutation.
            if not isinstance(e, BackupVerificationError):
                raise BackupVerificationError(f"Backup storage transaction failed: {e}")
            raise e

        logger.info(f"Recovery point created securely: {recovery_id}")
        return recovery_id
