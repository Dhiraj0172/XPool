# XPool Stage C: Evidence Audit and Remediation Readiness

## 1. Verify Every Major Finding

### Finding 1: Jules HTTP API Identity, Auth, Ops, and Permissions
- **File/Doc:** `docs/stage-b/JULES-INTEGRATION-DESIGN.md` (Lines 3-10)
- **Status:** `INFERRED / UNKNOWN`. The documentation assumes an HTTP REST API over localhost:8080 with a Bearer token.
- **Test Evidence:** None. No integration tests verify the Jules runtime environment supports HTTP over localhost.
- **Security Impact:** If Jules relies on MCP or FUSE, the Gateway AuthZ boundary is completely bypassed or unusable.
- **Smallest Safe Next Action:** Owner to execute a curl/HTTP GET from the Jules agent to a local socket.

### Finding 2: Quota Relationships Among Four Remotes
- **File/Doc:** `docs/BASELINE.md` (Line 2) lists `gdrive_pro_1`, `gdrive_pro_2`, `gdrive_pro_3`, `gdrive_plus_1` as `UnifiedStoragePool` members.
- **Status:** `INFERRED / UNKNOWN`. The previous report suggested they share a Google Workspace pool. This is an unsupported inference. The actual relationship (independent vs pooled) is completely unverified.
- **Test Evidence:** None.
- **Security Impact:** Summing free space across potentially shared pooled drives creates false capacity metrics, risking data loss via unexpected backend quota exhaustion.
- **Smallest Safe Next Action:** Run `rclone about` on each sub-remote independently to verify if the reported free space bytes match exactly.

### Finding 3: Protected-prefix enforcement for `.xpool_recovery/`
- **File/Doc:** `src/storage/rclone_adapter.py` -> `_get_remote_path()` (Lines 53-56)
- **Status:** `VERIFIED (VULNERABLE)`. The code explicitly blocks `.` (JULES_ZONE_ROOT) via `if rel_path == pathlib.Path("."): raise GatewayError(...)`, but contains zero string matching or path checks restricting `.xpool_recovery/`.
- **Test Evidence:** `test_remote_path_mapping` passes, but it only tests valid mappings, not `.xpool_recovery` blocking.
- **Security Impact:** An attacker bypassing the HTTP gateway logical checks can directly read/delete backend backups.
- **Smallest Safe Next Action:** Add `if rel_path.parts[0] == ".xpool_recovery": raise GatewayError` in the adapter.

### Finding 4: Backup-manager behavior when source is missing
- **File/Doc:** `src/backup/manager.py` -> `create_recovery_point()` (Lines 26-27)
- **Status:** `VERIFIED`. Code catches `FileNotFoundError` and `return RecoveryID("CREATE_ONLY")`.
- **Test Evidence:** `test_backup_missing_file_skips` PASSED.
- **Security Impact:** Native behavior is correct, but relies heavily on the caller safely interpreting `CREATE_ONLY`.
- **Smallest Safe Next Action:** None for this specific component.

### Finding 5: Backup verification before destructive mutations
- **File/Doc:** `src/backup/manager.py` -> `create_recovery_point()` (Lines 44-46)
- **Status:** `VERIFIED`. Verifies `if original_hash != backup_hash: raise BackupVerificationError(...)`.
- **Test Evidence:** `test_backup_integrity_mismatch_aborts` PASSED.
- **Security Impact:** Strong integrity guarantee for single, serialized mutations.
- **Smallest Safe Next Action:** None for the component itself.

### Finding 6: Concurrency and TOCTOU exposure
- **File/Doc:** `docs/stage-c/T04_SECURITY_DESIGN.md` (Section 4)
- **Status:** `INFERRED (VULNERABLE)`. The rclone adapter lacks conditional writes. A TOCTOU race exists on `CREATE_ONLY` where Worker A observes missing file, pauses, Worker B writes, Worker A overwrites B.
- **Test Evidence:** None. No concurrency integration tests exist.
- **Security Impact:** Silent data corruption or data loss under high concurrency or external writer scenarios.
- **Smallest Safe Next Action:** Implement the Single Authoritative Executor queue to enforce serial mutative operations within the Gateway.

### Finding 7: Recovery metadata durability and GC safety
- **File/Doc:** `docs/stage-c/T04_SECURITY_DESIGN.md` (Section 7)
- **Status:** `UNKNOWN`. The DB-aware GC and durable state metadata are documented as a design proposal, but absolutely no implementation or SQLite schemas exist in the codebase.
- **Test Evidence:** None.
- **Security Impact:** A crash during an operation leaves orphaned backups indefinitely. An overly aggressive external GC script could delete active backups.
- **Smallest Safe Next Action:** Implement the SQLite state-tracking tables defined in T04.

### Finding 8: The reported 23 passing tests and their actual scope
- **File/Doc:** `tests/unit/*.py`
- **Status:** `VERIFIED`. Exactly 23 tests exist and pass via `python3 -m pytest -v`.
- **Scope:** These are strictly isolated, offline, mocked unit tests. They prove local python logic (e.g. string canonicalization, schema rejection, mock error catching). They DO NOT prove the real backend behavior, quota transparency, or concurrency safety.

## 2. Correct Unsupported Claims

- **Quota Independence:** It is strictly UNKNOWN if the remotes share a Google Workspace quota. Evidence does not exist to support that conclusion. They are separate remote names, but could be shared drives on the same account. `QUOTA_INDEPENDENCE_STATUS = BLOCKED`.
- **Namespace Isolation:** Not proven. The `RcloneRCAdapter` does not enforce the boundary. `PROTECTED_NAMESPACE_ISOLATION = BLOCKED`.
- **TOCTOU Safety:** Not proven. `TOCTOU_SAFETY = BLOCKED`.

## 3. Bounded Remediation Plan

**Goal:** Address repository-only issues without affecting production.

1. **Protected Namespace Enforcement (Adapter Level)**
   - *Affected File:* `src/storage/rclone_adapter.py`
   - *Change:* Modify `_get_remote_path()` to check `if rel_path.parts[0] == ".xpool_recovery": raise AuthorizationError`.
   - *Tests Required:* New unit test in `test_storage_adapter.py` verifying 403 on `.xpool_recovery` paths.
   - *Remaining Risks:* External attackers hitting the rclone RC port directly still bypass this.

2. **Concurrency / TOCTOU Race Handling (Single Executor)**
   - *Affected File:* `src/gateway/executor.py` (New), `src/gateway/state.py` (New)
   - *Change:* Implement an async in-memory or SQLite-backed queue worker that strictly serializes all mutative `T02.write/delete` calls.
   - *Tests Required:* Integration test spawning two concurrent `write` threads targeting the same path, verifying one gets 409 Conflict or blocks.
   - *Remaining Risks:* This application-level executor does NOT solve races involving external writers or delayed rclone TCP backend mutations. Those remain residual risks as the backend itself lacks conditional locking.

3. **Durable Operation State and GC Safety**
   - *Affected File:* `src/gateway/state.py` (New)
   - *Change:* Implement the 13-state fail-closed SQLite tracker. Store `BackupID` to prevent GC races.
   - *Tests Required:* Unit test simulating a crash at `MUTATION_EXECUTING` recovering to `UNCERTAIN`.

## 4. Safety Restrictions
(Acknowledged and adhered to. No implementation occurred.)

## 5. Final Report

**Code Assessed:** `src/`, `tests/`, `docs/`.
**Commands Run:** `python3 -m pytest -v`.

`JULES_HTTP_API_STATUS: UNCONFIRMED`
`QUOTA_INDEPENDENCE_STATUS: BLOCKED`
`PROTECTED_NAMESPACE_ISOLATION: BLOCKED`
`T03_ACCEPTANCE: PENDING`
`BACKUP_ISOLATION: BLOCKED`
`TOCTOU_SAFETY: BLOCKED`
`authorization_gate_passed: false`
`stage_2_host_credential_integration: UNAUTHORIZED_PENDING_APPROVAL`
`PRODUCTION_AUTHORIZED: NO`
