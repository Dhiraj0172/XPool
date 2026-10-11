# XPool Stage C: Final Evidence Audit and Security Acceptance Preparation

## 1. Actual Baseline and Files Inspected
The repository baseline matches the remediation branch. Analyzed source code:
- `src/storage/rclone_adapter.py`
- `src/backup/manager.py`
- `src/gateway/executor.py`
- `src/gateway/state.py`
- `tests/unit/test_adversarial.py`

## 2. Verified Protections and Exact Supporting Tests
- **Protected Recovery Namespace (Application Layer):** `_execute_rc` is not reachable by untrusted user input directly. All public methods on `RcloneRCAdapter` explicitly route through `_get_remote_path()`, which natively throws a 403 GatewayError if the path begins with `.xpool_recovery`. This applies equivalently to copy/move operations.
  - *Supporting Tests:* `test_protected_prefix_access`, `test_protected_namespace_copy_move_destination`, `test_protected_namespace_copy_move_source`.
- **State Machine Integrity:** The DAG is verified via `VALID_TRANSITIONS`. Invalid transitions throw `ValueError`. DB write failures correctly fail closed.
  - *Supporting Tests:* `test_invalid_state_transition`, `test_db_failure_blocks_mutation`, `test_concurrent_state_updates`.
- **Restart Reconciliation:** Reconciles operations effectively upon reboot. `MUTATION_EXECUTING` goes to `UNCERTAIN`.
  - *Supporting Tests:* `test_restart_reconciliation`.

## 3. Security Findings and Unresolved Risks
- **TOCTOU Race Limitation:** Rclone lacks a cross-backend atomic compare-and-swap mechanism via RC. The Gateway re-hashes the source immediately prior to mutation, but an external writer could still modify the source file during the network roundtrip of the subsequent `operations/uploadfile` API call. Therefore, `TOCTOU_SAFETY` remains `BLOCKED` for uncontrolled/external writers.
- **Recovery GC Safety:** The SQL query `get_active_backup_ids()` exists to protect active and uncertain operations from deletion. However, no destructive GC deletion script actually exists in the repository. Therefore, `RECOVERY_GC_SAFETY` is explicitly `NOT_IMPLEMENTED`.
- **Namespace Isolation:** The application-layer enforces strict boundary checks. However, both the Gateway and the internal BackupManager share the identical set of Rclone daemon credentials. Complete backend cryptographic isolation is absent. Therefore, `PROTECTED_NAMESPACE_ISOLATION` remains `PARTIAL`.

## 4. Test Results (Mock vs Real Backend)
- **Execution:** `python3 -m pytest -v` executed 36 tests.
- **Results:** 36 PASSED, 0 FAILED, 0 SKIPPED.
- **Test Classification:** **ALL 36 TESTS ARE MOCKED OFFLINE UNIT TESTS.** There are absolutely zero "real backend" integration tests connecting to a live Google Drive or Rclone daemon.

## 5. Documentation Changes and Current Git Status
- `git diff --check` passed clean. No unstaged errors.
- `git status --short` confirms only approved Python source files (`src/storage/rclone_adapter.py`, `src/backup/manager.py`, `src/gateway/executor.py`, `src/gateway/state.py`), tests (`tests/unit/test_adversarial.py`), and markdown documentation reports have been added or modified. No production data or configuration files were changed.

## 6. Recommended Next Milestone
Authorize execution of `T05-WINDOWS-INTEGRATION` to verify WinFsp pre-login mounting logic against a designated integration test host, without executing unauthorized live mutations.
