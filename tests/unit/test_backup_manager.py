import pytest
import sys
from src.backup.manager import BackupManager
from src.common.types import JulesPath
from src.common.errors import BackupVerificationError, GatewayError

# Provide a mock adapter isolating the backend
class MockStorageAdapter:
    def __init__(self):
        self.store = {}
        self.read_fail = False
        self.write_fail = False
        self.corrupt_read_back = False

    def read(self, path: JulesPath) -> bytes:
        if self.read_fail:
            raise GatewayError("Backend down", code=502)
        if str(path.canonical_path) not in self.store:
            raise FileNotFoundError("Missing")

        # Simulate corruption on the read-back verification step
        if self.corrupt_read_back and ".xpool_recovery" in str(path.canonical_path):
            return b"corrupted_bytes"

        return self.store[str(path.canonical_path)]

    def write(self, path: JulesPath, data: bytes) -> bool:
        if self.write_fail:
            return False
        self.store[str(path.canonical_path)] = data
        return True


@pytest.fixture
def root_path():
    return "C:/JulesWorkspace" if sys.platform == "win32" else "/JulesWorkspace"


@pytest.fixture
def backup_mgr(root_path):
    adapter = MockStorageAdapter()
    return BackupManager(storage_adapter=adapter, jules_zone_root=root_path), adapter


def test_backup_success(backup_mgr, root_path):
    mgr, adapter = backup_mgr
    target = JulesPath(f"{root_path}/target.txt")

    # Pre-populate original file
    adapter.store[str(target.canonical_path)] = b"original_content"

    recovery_id = mgr.create_recovery_point(target)

    # Verify the backup ID exists and the backup object is stored
    assert recovery_id != "CREATE_ONLY"
    backup_files = [k for k in adapter.store.keys() if ".xpool_recovery" in k]
    assert len(backup_files) == 1
    assert adapter.store[backup_files[0]] == b"original_content"


def test_backup_missing_file_skips(backup_mgr, root_path):
    mgr, _ = backup_mgr
    target = JulesPath(f"{root_path}/new_file.txt")

    # No file in store means it's a new create, no destructive mutation
    recovery_id = mgr.create_recovery_point(target)
    assert recovery_id == "CREATE_ONLY"


def test_backup_write_failure_aborts(backup_mgr, root_path):
    mgr, adapter = backup_mgr
    target = JulesPath(f"{root_path}/target.txt")
    adapter.store[str(target.canonical_path)] = b"original_content"

    adapter.write_fail = True

    with pytest.raises(BackupVerificationError) as exc:
        mgr.create_recovery_point(target)

    assert "rejected backup write" in str(exc.value)


def test_backup_integrity_mismatch_aborts(backup_mgr, root_path):
    mgr, adapter = backup_mgr
    target = JulesPath(f"{root_path}/target.txt")
    adapter.store[str(target.canonical_path)] = b"original_content"

    # Force the read-back to return different bytes
    adapter.corrupt_read_back = True

    with pytest.raises(BackupVerificationError) as exc:
        mgr.create_recovery_point(target)

    assert "Hash mismatch" in str(exc.value)


def test_backup_path_escape_blocked(backup_mgr):
    mgr, _ = backup_mgr
    # Attempting to backup a file outside the zone entirely
    target = JulesPath("C:/Windows/System32/evil.dll" if sys.platform == "win32" else "/etc/passwd")

    with pytest.raises(GatewayError) as exc:
        mgr.create_recovery_point(target)
    assert exc.value.code == 403
    assert "Path traversal prevented" in str(exc.value)
