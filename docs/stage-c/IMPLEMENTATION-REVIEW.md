# XPool Stage C: Independent Security Review of the New Implementation

## 1. Protected Namespace
- **Finding:** The `allow_protected_namespace` toggle in `RcloneRCAdapter` is merely a public Boolean bypass (`self.allow_protected_namespace = allow_protected_namespace`). It does not create true capability-based isolation or use separate credentials. Any component (or attacker gaining code execution) can flip it. The boundary is partially enforced but bypassable.
- **Reference:** `src/storage/rclone_adapter.py` lines 12, 53-56.
- **Severity:** High
- **Remediation:** Implement true backend ACLs or separate rclone daemons for the recovery namespace. Until then, isolation remains PARTIAL.

## 2. Backup-before-mutation
- **Finding:** The executor correctly calculates the hash, runs `BackupManager`, and verifies the backup hash before mutating. Exceptions and checksum mismatches correctly trigger the fail-closed `FAILED` state.
- **Reference:** `src/gateway/executor.py` lines 39-51.
- **Severity:** Informational
- **Remediation:** None required for the local execution path.

## 3. TOCTOU & Concurrency
- **Finding:** `CREATE_ONLY` handling delegates missing file logic to the `SingleAuthoritativeExecutor`. The `execute_write` function wraps the *entire* process (hash -> backup -> mutate) inside a local `threading.Lock()`. This prevents local TOCTOU. However, it does not revalidate the source hash immediately before the `rclone.write()` call. More critically, as explicitly documented, this application-level lock provides **zero** protection against delayed backend packets or external writers.
- **Reference:** `src/gateway/executor.py` lines 29, 56.
- **Severity:** Critical (for distributed environments) / Informational (if operating under strictly assumed local-only execution).
- **Remediation:** Mark TOCTOU guarantees as BLOCKED for external writers. Add a pre-mutation hash re-verification immediately before the `write()` call for defense in depth.

## 4. SQLite Tracker
- **Finding:** The tracker uses `sqlite3` context managers for transaction safety and provides robust `reconcile_restarts` logic. However, the `update_state()` function lacks transition enforcement—it allows jumping directly from `REQUESTED` to `DONE` without going through the required DAG.
- **Reference:** `src/gateway/state.py` line 52.
- **Severity:** Medium
- **Remediation:** Implement a strict state-transition DAG validation inside `update_state()` before executing the SQL `UPDATE`.

## 5. Recovery Cleanup
- **Finding:** While the SQLite schema stores `backup_id` and operations track active states, there is **no garbage collection or cleanup logic** implemented anywhere to remove data referenced by failed/done operations. The only cleanup is the immediate try/except inside `create_recovery_point` on initial creation failure.
- **Reference:** `src/backup/manager.py` line 49.
- **Severity:** High (Operational / Capacity exhaustion risk).
- **Remediation:** Implement a background GC loop that queries the database for inactive `backup_id`s and safely deletes them via the adapter.

## 6. Tests
- **Finding:** 29 tests pass successfully. However, they rely exclusively on the `LocalMockAdapter`. The integration is unit-tested against mocks, not against isolated storage.
- **Missing Tests:** The 18 adversarial scenarios requested were condensed to 7. We are missing tests for: Database failure (locking the DB), Protected namespace as copy/move source/destination, Concurrent source changes (external writers), `CREATE_ONLY` races, and GC racing.
- **Reference:** `tests/unit/test_adversarial.py`
- **Severity:** Medium
- **Remediation:** Expand the test suite to include the missing 11 adversarial scenarios. Add real isolated backend integration tests.

## 7. Audit Security
- **Finding:** No secrets or payloads are leaked. The schema explicitly tracks `principal_id` and avoids raw tokens. Error outputs are clean.
- **Reference:** `src/gateway/state.py`
- **Severity:** Informational
- **Remediation:** None.

---

`IMPLEMENTATION_REVIEW: PASS_WITH_FINDINGS`

`PROTECTED_NAMESPACE_ISOLATION: PARTIAL`

`BACKUP_BEFORE_MUTATION: VERIFIED_IN_TESTS`

`TOCTOU_SAFETY: BLOCKED`

`RESTART_RECONCILIATION: VERIFIED_IN_TESTS`

`T03_ACCEPTANCE: PENDING`

`authorization_gate_passed: false`

`stage_2_host_credential_integration: UNAUTHORIZED_PENDING_APPROVAL`

`PRODUCTION_AUTHORIZED: NO`
