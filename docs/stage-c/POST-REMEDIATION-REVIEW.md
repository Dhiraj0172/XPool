# XPool Stage C: Post-Remediation Security Verification

## 1. Namespace Boundary
- **Finding:** The public `allow_protected_namespace` parameter was completely removed from `RcloneRCAdapter`. All ordinary calls natively run through `_get_remote_path()`, which unconditionally throws `GatewayError(..., code=403)` if `.xpool_recovery` is the first path segment.
- **Internal Bypass Verification:** The `BackupManager` executes its operations by directly calling the private `_execute_rc` method on the adapter with manually crafted paths, entirely avoiding `_get_remote_path()`. Because `_execute_rc` is not exposed via standard Gateway REST API routes, ordinary users cannot invoke it.
- **Limitation:** The "internal" method relies solely on Python encapsulation. Because the Gateway and the Backup processes both share the same underlying Rclone RC daemon credentials and endpoint, there is no genuine cryptographic or network-level backend ACL enforcing this boundary if an attacker achieves local code execution.
- **Status:** Isolation remains `PARTIAL` as the backend does not enforce the boundary independently.

## 2. State Transition Enforcement
- **Finding:** The SQLite `OperationTracker` incorporates a strict `VALID_TRANSITIONS` Python dictionary modeling the Directed Acyclic Graph (DAG) for operations.
- **Atomicity:** `update_state()` performs an atomic `SELECT` inside a local `threading.Lock` and SQLite context manager to verify the current state against the DAG before issuing the `UPDATE`. Invalid jumps raise `ValueError`.
- **Failures:** `test_db_failure_blocks_mutation` confirms that if the database is inaccessible, mutations safely abort without reaching the backend.
- **Reconciliation:** `test_restart_reconciliation` verifies that operations caught in `MUTATION_EXECUTING` upon restart transition correctly to `UNCERTAIN`, not `DONE` or `FAILED`.

## 3. Backup and Mutation Ordering
- **Trace:** `SingleAuthoritativeExecutor.execute_write()` -> Hash Source (`SOURCE_VERSION_IDENTIFIED`) -> Backup via `manager.py` (`BACKUP_VERIFIED`) -> Re-hash Source -> `write()` (`MUTATION_EXECUTING`).
- **Source Revalidation:** The Executor executes `reval_hash = self.storage.hash(...)` immediately before `MUTATION_ALLOWED`, explicitly rejecting the mutation if the source was altered concurrently (proven via `test_concurrent_source_change_reval`).
- **TOCTOU Gap:** There is an explicit race condition between the successful completion of `self.storage.hash()` and the reception of the subsequent `self.storage.write()` packet by the rclone daemon. Because rclone lacks `If-Match` atomic preconditions, an external writer could alter the file in those few milliseconds. Re-hashing narrows the window but does not eliminate the race. TOCTOU remains structurally BLOCKED for external writers.

## 4. Recovery Cleanup
- **Finding:** The `get_active_backup_ids()` protocol correctly filters `backup_id`s that are tied to states not strictly `FAILED` or `DONE`.
- **GC Status:** As verified in source code and explicitly noted in documentation, **no actual background garbage collection loop exists**. Therefore, GC safety is formally NOT_IMPLEMENTED because there is no GC to be safe against. This implies that while the protocol is defined to be safe against active ops, recovery artifacts simply accumulate indefinitely.

## 5. Test Evidence
- **Execution:** `python3 -m pytest -v` executed successfully without errors or warnings.
- **Count:** 36 tests collected, 36 PASSED, 0 SKIPPED.
- **Coverage:** Verified test coverage for protected-prefix access blocks, valid/invalid state transitions, duplicate request idempotency, simulated DB failures, Concurrent source-change TOCTOU blocking, and restart reconciliation.
- **Mock vs Real:** **ALL** integration tests concerning the adapter or backend rely strictly on mocked classes (`LocalMockAdapter`, `MockStorageAdapter`). No tests are executed against a live Rclone daemon or Google Drive backend.

## 6. Git and Scope
- `git diff --check`: 0 errors. No whitespace trailing issues.
- `git status --short`:
  ```
  A  docs/stage-c/IMPLEMENTATION-REVIEW.md
  A  docs/stage-c/POST-REMEDIATION-REVIEW.md
  A  docs/stage-c/STAGE-C-BLOCKER-VERIFICATION.md
  A  docs/stage-c/STAGE-C-EVIDENCE-AUDIT-AND-REMEDIATION.md
  A  docs/stage-c/T04_SECURITY_DESIGN.md
  M  src/backup/manager.py
  A  src/gateway/__init__.py
  A  src/gateway/executor.py
  A  src/gateway/state.py
  M  src/storage/rclone_adapter.py
  A  tests/unit/test_adversarial.py
  M  tests/unit/test_backup_manager.py
  ```
- **Changes:** Only relevant, authorized Python files and Markdown documentation were added or modified. No production settings or configurations were touched.

## Recommended Next Action
Authorize Windows execution to integrate with the host OS and prove WinFsp pre-login mounting logic (`T05-WINDOWS-INTEGRATION`).
