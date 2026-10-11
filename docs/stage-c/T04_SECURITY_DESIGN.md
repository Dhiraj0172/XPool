# XPOOL T04: SECURITY DESIGN, CONCURRENCY PROTOCOL AND IMPLEMENTATION READINESS

## 1. Executive Summary

This document presents the detailed architectural design for the T04 Gateway API for XPool, strictly adhering to read-only audit constraints. It defines a protected recovery namespace, a Single Authoritative Executor model for concurrency (with explicitly acknowledged residual risks), an exhaustive fail-closed state machine without unsafe fallbacks, memory-bounded API streaming, and an expanded, highly detailed testing matrix.

**Status Summary:**
`T04_DESIGN_STATUS: READY_FOR_OWNER_REVIEW`
`T03_ACCEPTANCE: PENDING`
`IMPLEMENTATION_AUTHORIZED: NO`
`PRODUCTION_AUTHORIZED: NO`
`CONCURRENCY_GUARANTEE: GUARDED_BY_EXCLUSIVE_EXECUTOR`
`BACKUP_ISOLATION: BLOCKED`

## 2. Current Contract Assessment

Based on the inspection of actual source code (`src/`):
- **T01 Core Contracts:** Implements `JulesPath`, canonicalization via `pathlib.Path.resolve()`, and explicit schemas. (`VERIFIED_FROM_SOURCE`)
- **T02 Storage Adapter:** Integrates with rclone RC. Blocks target `.`, but lacks `.xpool_recovery/` enforcement. Does not support conditional writes. (`VERIFIED_FROM_SOURCE`)
- **T03 Backup Manager:** Creates backups via backend `copy()`/`hash()`. Returns `CREATE_ONLY` for `FileNotFoundError`. Writes to `.xpool_recovery/<ID>_<name>`. Does not implement CAS deduplication specification. (`VERIFIED_FROM_SOURCE`)

## 3. Protected Recovery Namespace Design

The `.xpool_recovery/` namespace must be strictly isolated.
- **Gateway-level:** Gateway routing (T04) rejects any resolved path starting with `.xpool_recovery/` for Jules tokens.
- **Adapter-level (Protected-prefix enforcement):** T02 must be updated to inherently reject `.xpool_recovery/`.
- **Backup-only Internal Authorization:** T03 should use an elevated configuration to perform recovery writes.
- **Credential Separation:** The current architecture shares a single rclone daemon and master credentials. Gateway checks are a logical bypassable boundary. Therefore, true independent namespace protection requires separate rclone daemons or backend ACLs.
- **Classification:** `BLOCKED` (Requires separate backend credentials or an independently protected backend namespace not currently available).

## 4. Concurrency Protocol

The rclone backend does not support atomic conditional writes or fencing tokens.

**Single Authoritative Executor Model:**
To prevent the stale worker race (Worker A pauses, Worker B writes, Worker A resumes and overwrites without checking the DB), XPool must implement operational exclusion of all alternate writers. All mutative rclone API calls MUST be dispatched by a single queue worker.

**Limitations and Residual Risks:**
- **Executor process crash / Host restart:** If the host or process crashes while an HTTP request to rclone is in flight, the state machine restarts in an `UNCERTAIN` state. The backend operation may still complete asynchronously.
- **Network partition / Delayed requests:** If a network partition occurs between the Gateway and the rclone daemon, the TCP request might be delayed. A lock or database state cannot stop the delayed TCP packet from eventually reaching rclone and executing.
- **Multiple gateway instances:** Operating multiple gateway instances connected to the same rclone daemon violates the "Single Authoritative Executor" model unless they all push to a single shared queue processed by only one worker.
- **Direct access / Manual external writers:** Any user or process interacting directly with the rclone daemon or the underlying cloud storage bypasses the Gateway Executor entirely, resulting in undetected races.
- **Residual Risk Acknowledgment:** Because the backend cannot enforce conditional writes natively, we assume the network link between Gateway and Rclone is strictly local/reliable, and no external writers exist. These operational assumptions cannot be cryptographically established by the Gateway alone.

## 5. Fail-Closed Mutation State Machine

All states and transitions for the authoritative Executor loop. If the DB is unavailable, operations fail closed (no local-file fallback).

**State 1: REQUESTED**
- **Preconditions:** Client submits valid request, payload streamed to local staging area.
- **Trigger:** Gateway enqueues request to DB.
- **Durable state written:** Operation ID, `target_path`, `idempotency_key`, `PrincipalID`, Status=`REQUESTED`.
- **Lock ownership:** None.
- **Mutation permitted:** No.
- **Retry policy:** Safe to retry queue insertion.
- **Client-visible result:** Pending (or accepted for async).
- **Restart/reconciliation:** Remains `REQUESTED`; Executor picks it up on boot.

**State 2: LOCKED**
- **Preconditions:** Operation is `REQUESTED`.
- **Trigger:** Executor claims operation.
- **Durable state written:** Status=`LOCKED`, `ExecutorID`.
- **Lock ownership:** Held by specific `ExecutorID`.
- **Mutation permitted:** No.
- **Retry policy:** Internal loop retries claim if failed.
- **Client-visible result:** Pending.
- **Restart/reconciliation:** If Executor crashed, GC resets to `REQUESTED` after TTL.

**State 3: SOURCE_VERSION_IDENTIFIED**
- **Preconditions:** Status=`LOCKED`.
- **Trigger:** Executor queries backend hash.
- **Durable state written:** Status=`SOURCE_VERSION_IDENTIFIED`, `OriginalHash` (or `CREATE_ONLY`).
- **Lock ownership:** Held.
- **Mutation permitted:** No.
- **Retry policy:** Transient network errors retried 3 times.
- **Client-visible result:** Pending.
- **Restart/reconciliation:** Reset to `REQUESTED`.

**State 4: BACKUP_REQUIRED**
- **Preconditions:** Status=`SOURCE_VERSION_IDENTIFIED` and `OriginalHash` != `CREATE_ONLY`.
- **Trigger:** System determines operation destroys existing data.
- **Durable state written:** Status=`BACKUP_REQUIRED`.
- **Lock ownership:** Held.
- **Mutation permitted:** No.
- **Retry policy:** N/A (Internal logic).
- **Client-visible result:** Pending.
- **Restart/reconciliation:** Reset to `REQUESTED`.

**State 5: BACKUP_RUNNING**
- **Preconditions:** Status=`BACKUP_REQUIRED`.
- **Trigger:** Executor calls `T03.create_recovery_point()`.
- **Durable state written:** Status=`BACKUP_RUNNING`, `BackupID`.
- **Lock ownership:** Held.
- **Mutation permitted:** No.
- **Retry policy:** No retries on backup creation.
- **Client-visible result:** Pending.
- **Restart/reconciliation:** Transition to `FAILED`. Orphaned backup cleaned by DB-aware GC.

**State 6: BACKUP_VERIFIED**
- **Preconditions:** Status=`BACKUP_RUNNING`, T03 verifies backup hash equals `OriginalHash`.
- **Trigger:** T03 returns success.
- **Durable state written:** Status=`BACKUP_VERIFIED`.
- **Lock ownership:** Held.
- **Mutation permitted:** NO VERIFIED DURABLE PRE-OPERATION PROTECTION = NO DESTRUCTIVE MUTATION. (Allowed now).
- **Retry policy:** N/A.
- **Client-visible result:** Pending.
- **Restart/reconciliation:** Reset to `REQUESTED` (safer to redo backup check than assume safety).

**State 7: MUTATION_ALLOWED**
- **Preconditions:** Status=`BACKUP_VERIFIED` or (`OriginalHash` == `CREATE_ONLY` verified).
- **Trigger:** Executor prepares backend call.
- **Durable state written:** Status=`MUTATION_ALLOWED`.
- **Lock ownership:** Held.
- **Mutation permitted:** Yes.
- **Retry policy:** N/A.
- **Client-visible result:** Pending.
- **Restart/reconciliation:** Transition to `FAILED`.

**State 8: MUTATION_EXECUTING**
- **Preconditions:** Status=`MUTATION_ALLOWED`.
- **Trigger:** Executor calls `T02.write()`, `move()`, or `delete()`.
- **Durable state written:** Status=`MUTATION_EXECUTING`.
- **Lock ownership:** Held.
- **Mutation permitted:** Yes (in progress).
- **Retry policy:** Idempotent ops retried 3 times; Non-idempotent (Move) 0 times.
- **Client-visible result:** Pending.
- **Restart/reconciliation:** Transition to `UNCERTAIN`.

**State 9: MUTATION_CONFIRMED**
- **Preconditions:** Status=`MUTATION_EXECUTING`.
- **Trigger:** Backend returns HTTP 200/Success.
- **Durable state written:** Status=`MUTATION_CONFIRMED`, `FinalHash`.
- **Lock ownership:** Held.
- **Mutation permitted:** Yes (completed).
- **Retry policy:** N/A.
- **Client-visible result:** Success.
- **Restart/reconciliation:** Re-verify hash, transition to `DONE`.

**State 10: DONE (Terminal)**
- **Preconditions:** Status=`MUTATION_CONFIRMED`.
- **Trigger:** Audit log finalized.
- **Durable state written:** Status=`DONE`.
- **Lock ownership:** Released.
- **Mutation permitted:** No.
- **Retry policy:** N/A.
- **Client-visible result:** HTTP 200 Success.
- **Restart/reconciliation:** Stable terminal state.

**State 11: FAILED (Terminal)**
- **Preconditions:** Any error before or during operation that guarantees no backend mutation occurred (e.g., checksum mismatch, quota exhaustion, network outage before `MUTATION_EXECUTING`).
- **Trigger:** Exception caught.
- **Durable state written:** Status=`FAILED`, `ErrorCode`.
- **Lock ownership:** Released.
- **Mutation permitted:** No.
- **Retry policy:** N/A.
- **Client-visible result:** HTTP 4xx or 5xx Error.
- **Restart/reconciliation:** Stable terminal state.

**State 12: ABORTED (Terminal)**
- **Preconditions:** Client cancelled the request stream before mutation began.
- **Trigger:** HTTP connection closed.
- **Durable state written:** Status=`ABORTED`.
- **Lock ownership:** Released.
- **Mutation permitted:** No.
- **Retry policy:** N/A.
- **Client-visible result:** N/A (Client disconnected).
- **Restart/reconciliation:** Stable terminal state.

**State 13: UNCERTAIN (Recoverable/Terminal)**
- **Preconditions:** Status=`MUTATION_EXECUTING`.
- **Trigger:** Network timeout, crash, or indeterminate backend response.
- **Durable state written:** Status=`UNCERTAIN`.
- **Lock ownership:** Held manually/administratively.
- **Mutation permitted:** No.
- **Retry policy:** N/A.
- **Client-visible result:** HTTP 504 Gateway Timeout or 500 Internal Error.
- **Restart/reconciliation:** Executor runs reconciliation script: Hashes backend file. If it matches target payload, transition to `DONE`. If it matches original payload, transition to `FAILED`. If neither, requires admin intervention.

## 6. API Contracts

No secrets (Bearer tokens, Admin tokens, keys) will be recorded in audit logs or the database. Instead, the AuthZ middleware derives a non-secret `PrincipalID`. Large files require streaming; `data: base64` is rejected to prevent OOM amplification.

1. **Read** (`GET /api/v1/files/read`)
   - *Input:* Query param `target_path`.
   - *Identity:* Valid Token -> `PrincipalID`.
   - *Canonicalization:* Resolved. Rejects `.xpool_recovery/`.
   - *Audit Fields:* Path, `PrincipalID`, RequestID.
2. **Write/Create/Overwrite** (`PUT /api/v1/files/write`)
   - *Input:* Bounded binary stream (Limit: configured max size). Headers: `X-Target-Path`, `X-Idempotency-Key`, `X-Expected-Hash`. Partial uploads aborted on client disconnect trigger immediate cleanup of the local staging file.
   - *Identity:* Valid Token -> `PrincipalID`.
   - *Errors:* 403, 409, 429, 500, 413 Payload Too Large.
   - *Audit Fields:* Path, `PrincipalID`, RequestID, BackupID, FinalHash.
3. **Copy** (`POST /api/v1/files/copy`)
   - *Input:* `{"src_path": "str", "dst_path": "str", "idempotency_key": "str"}`
   - *Identity:* Valid Token -> `PrincipalID`.
4. **Move/Rename** (`POST /api/v1/files/move`)
   - *Input:* `{"src_path": "str", "dst_path": "str", "idempotency_key": "str"}`
   - *Identity:* Valid Token -> `PrincipalID`.
5. **Delete** (`POST /api/v1/files/delete`)
   - *Input:* `{"target_path": "str", "idempotency_key": "str"}`
   - *Identity:* Valid Token -> `PrincipalID`.
6. **Recovery-point Lookup** (`POST /api/v1/recovery/lookup`)
   - *Input:* `{"target_path": "str"}`
   - *Identity:* Admin Token -> `AdminPrincipalID`.
7. **Operation-status Lookup** (`GET /api/v1/operations/status`)
   - *Input:* Query param `operation_id`.
   - *Identity:* Valid Token -> `PrincipalID`.
8. **Recovery/Restore** (`POST /api/v1/recovery/restore`)
   - *Input:* `{"recovery_id": "str", "dst_path": "str"}`
   - *Identity:* Admin Token -> `AdminPrincipalID`.

## 7. Backup and Deduplication Guarantees

- **T03 Current Guarantees:** Backup identity via timestamped UUID. Destination verification via hash. (`VERIFIED_FROM_SOURCE`)
- **Missing Guarantees:** T03 does not implement CAS deduplication specification. (`VERIFIED_FROM_SOURCE`).
- **GC Semantics:** Active and uncertain operations record `BackupID` in the DB.
  - **Ownership:** Backups belong to the system, linked to operations via `BackupID`.
  - **Safe Cleanup Eligibility:** A backup is eligible for GC ONLY if its operation state is `FAILED`, or if it exceeds retention policy for `DONE` operations, AND is NOT in an active/uncertain state.
  - **Concurrent GC Coordination:** GC locks rows in DB before deletion.
  - **Cleanup Failure:** Skip and retry on next cycle. No operational impact.

## 8. Threat Model and Residual Risks

- **Threat:** Malicious path traversal (`../`) bypassing namespace restrictions. (Defended via Canonicalization).
- **Threat:** Secret leakage in logs. (Defended via strict DB schema stripping headers).
- **Threat:** Memory Exhaustion (OOM) via base64 amplification. (Defended via strict streaming limits).
- **Residual Risk:** See Section 4. Backend lacks conditional writes. Total isolation relies on operational trust of single executor model.

## 9. Test and Acceptance Matrix

1. **Path traversal and protected-prefix bypass**
   - *Scenario ID:* `TEST-SCEN-01`
   - *Threat:* Path traversal (`../`) bypasses boundaries.
   - *Setup:* Isolated storage with Gateway API running.
   - *Test action:* Submit `PUT` request with `target_path` containing `../.xpool_recovery/`.
   - *Expected result:* 403 Forbidden or 400 Bad Request.
   - *Evidence captured:* HTTP response code and Gateway logs.
   - *Proves:* Canonicalization layer rejects traversal.
   - *Does not prove:* Adapter-level namespace isolation.

2. **Unauthorized access to the recovery namespace**
   - *Scenario ID:* `TEST-SCEN-02`
   - *Threat:* Unprivileged user reads backups.
   - *Setup:* Authenticated Jules token (non-admin).
   - *Test action:* Call `POST /api/v1/recovery/lookup` or read `.xpool_recovery/`.
   - *Expected result:* 403 Forbidden.
   - *Evidence captured:* HTTP response payload.
   - *Proves:* Admin authentication separates backup access.
   - *Does not prove:* External attacker cannot access rclone directly.

3. **Backup verification failure and checksum mismatch**
   - *Scenario ID:* `TEST-SCEN-03`
   - *Threat:* Corrupt backup allows destruction of original file.
   - *Setup:* Mock T03 to return a mismatched backup SHA-256 hash.
   - *Test action:* Submit Overwrite request.
   - *Expected result:* Operation transitions to `FAILED`. Original file untouched.
   - *Evidence captured:* State machine DB row, backend audit log.
   - *Proves:* Destination integrity verification blocks mutations.
   - *Does not prove:* Backend storage durability over time.

4. **Backup quota exhaustion and rate limiting**
   - *Scenario ID:* `TEST-SCEN-04`
   - *Threat:* Storage exhaustion leads to silent failures or hangs.
   - *Setup:* Mock rclone to return HTTP 429 during backup write.
   - *Test action:* Submit Delete request (requiring backup).
   - *Expected result:* Gateway catches quota error, operation transitions to `FAILED`, Gateway returns 429.
   - *Evidence captured:* Gateway response and DB error code.
   - *Proves:* Quota transparency and fail-closed handling.
   - *Does not prove:* Accuracy of backend quota calculation.

5. **Network outage and ambiguous mutation timeout**
   - *Scenario ID:* `TEST-SCEN-05`
   - *Threat:* Split brain or untracked state changes.
   - *Setup:* Mock network disconnect immediately after Gateway sends HTTP request to `rclone` during `MUTATION_EXECUTING`.
   - *Test action:* Submit Write request.
   - *Expected result:* Executor timeout. Operation transitions to `UNCERTAIN`.
   - *Evidence captured:* DB status log showing `UNCERTAIN`.
   - *Proves:* Gateway tracks indeterminate backend states safely.
   - *Does not prove:* Actual file state on the backend.

6. **Gateway process crash and host restart**
   - *Scenario ID:* `TEST-SCEN-06`
   - *Threat:* Transient failure causes lost mutation tracking.
   - *Setup:* Force process kill `SIGKILL` while operation is `BACKUP_RUNNING`. Restart Gateway.
   - *Test action:* Submit Write request, trigger crash, reboot.
   - *Expected result:* Executor sweep on boot marks operation `FAILED`.
   - *Evidence captured:* Gateway boot log and DB sweep trace.
   - *Proves:* Safe recovery from process death before mutation.
   - *Does not prove:* That the backup artifact is immediately deleted.

7. **Duplicate requests and concurrent mutations**
   - *Scenario ID:* `TEST-SCEN-07`
   - *Threat:* TOCTOU (Time-of-Check Time-of-Use) duplicate writes.
   - *Setup:* Submit two Create requests for the exact same path simultaneously.
   - *Test action:* Send requests A and B concurrently.
   - *Expected result:* Executor queues both. First succeeds, second sees file exists and returns 409 Conflict.
   - *Evidence captured:* Queue processing log, DB output.
   - *Proves:* Executor serialization prevents TOCTOU races.
   - *Does not prove:* Atomic guarantees natively from the backend.

8. **Stale worker attempting a delayed mutation**
   - *Scenario ID:* `TEST-SCEN-08`
   - *Threat:* Stale overwrite race.
   - *Setup:* Architecture review of the Executor.
   - *Test action:* Verify only one Executor thread processes mutative queues.
   - *Expected result:* Single Executor design.
   - *Evidence captured:* System architecture specification.
   - *Proves:* Avoidance of multi-worker stale write race.
   - *Does not prove:* Protection against delayed TCP packets natively.

9. **Database or durable-metadata failure**
   - *Scenario ID:* `TEST-SCEN-09`
   - *Threat:* Silent failures when tracking state is impossible.
   - *Setup:* Remove write permissions to SQLite DB.
   - *Test action:* Submit Delete request.
   - *Expected result:* Immediate 500 error. No backend call made.
   - *Evidence captured:* Gateway stderr log.
   - *Proves:* Fail-closed database dependency.
   - *Does not prove:* Ability to recover damaged DB rows.

10. **Recovery and reconciliation after restart**
    - *Scenario ID:* `TEST-SCEN-10`
    - *Threat:* Unresolved operations block future writes.
    - *Setup:* Inject `UNCERTAIN` state into DB. Start Gateway.
    - *Test action:* Run automatic reconciliation script.
    - *Expected result:* Script hashes backend file and resolves to `DONE` or `FAILED`.
    - *Evidence captured:* Reconciliation script stdout.
    - *Proves:* Automated state recovery from `UNCERTAIN`.
    - *Does not prove:* Perfect resolution without admin intervention.

11. **Garbage collection racing with active or uncertain operations**
    - *Scenario ID:* `TEST-SCEN-11`
    - *Threat:* GC deletes a backup artifact still needed by an active operation.
    - *Setup:* Inject `UNCERTAIN` operation with `BackupID=123`.
    - *Test action:* Trigger GC cron script.
    - *Expected result:* GC skips artifact 123.
    - *Evidence captured:* GC dry-run log.
    - *Proves:* DB-aware GC protects active artifacts.
    - *Does not prove:* Long-term retention policy functionality.

12. **Large-file streaming and bounded-memory enforcement**
    - *Scenario ID:* `TEST-SCEN-12`
    - *Threat:* OOM vulnerability via Base64 amplification or unchecked buffers.
    - *Setup:* Configure Gateway limit to 50MB.
    - *Test action:* Attempt to `PUT` a 2GB file stream.
    - *Expected result:* Gateway rejects stream early with 413 Payload Too Large.
    - *Evidence captured:* Memory profiler log, HTTP 413 response.
    - *Proves:* Bounded memory limits are enforced.
    - *Does not prove:* Storage I/O throughput limits.

13. **Credential and secret redaction in audit logs**
    - *Scenario ID:* `TEST-SCEN-13`
    - *Threat:* Secret leakage in persistent DB.
    - *Setup:* Submit valid request with Bearer token.
    - *Test action:* Inspect generated DB audit row.
    - *Expected result:* Token is absent, only `PrincipalID` exists.
    - *Evidence captured:* SQLite DB query output.
    - *Proves:* Schema enforces redaction.
    - *Does not prove:* External network monitoring security.

14. **Lost client connection during an operation**
    - *Scenario ID:* `TEST-SCEN-14`
    - *Threat:* Incomplete staging file wastes disk space, or backend left in indeterminate state.
    - *Setup:* Client begins `PUT` stream, drops TCP connection halfway.
    - *Test action:* Monitor Executor queue.
    - *Expected result:* Staging file cleaned up immediately, operation marked `ABORTED`.
    - *Evidence captured:* Gateway filesystem event log, DB status.
    - *Proves:* Safe cleanup on client disconnect.
    - *Does not prove:* Network bandwidth recovery.

15. **External writers, multiple gateway instances, and direct rclone access**
    - *Scenario ID:* `TEST-SCEN-15`
    - *Threat:* External bypass invalidates Gateway locks.
    - *Setup:* External script modifies file via rclone daemon directly while Gateway holds lock.
    - *Test action:* Gateway performs `MUTATION_EXECUTING`.
    - *Expected result:* Gateway blindly overwrites external modification.
    - *Evidence captured:* Backend audit history.
    - *Proves:* Gateway cannot protect against external writers (Residual Risk identified).
    - *Does not prove:* Gateway lock failure.

16. **Cleanup failure and orphaned recovery artifacts**
    - *Scenario ID:* `TEST-SCEN-16`
    - *Threat:* Disk space exhaustion via failed cleanups.
    - *Setup:* Mock T03 delete failure during `ABORTED` transition.
    - *Test action:* Submit failing Write request.
    - *Expected result:* Operation safely aborts. DB logs cleanup error. Later GC run successfully sweeps it.
    - *Evidence captured:* Application error log, GC success log.
    - *Proves:* Cleanup failures don't bypass security or crash the gateway.
    - *Does not prove:* Underlying storage reliability.

## 10. File Ownership and Implementation Plan

- **T04 Consumes:** `src/common/schemas.py`, `src/common/types.py`, `src/common/errors.py`, `src/backup/manager.py`.
- **T04 Owns:** `src/gateway/main.py`, `src/auth/token.py`, `src/policy/bounds.py`, `src/gateway/executor.py`.

## 11. Explicit Blockers and Decisions

- **Unresolved T03 Blocker:** T03 lacks CAS deduplication. (`VERIFIED_FROM_SOURCE`).
- **Adapter Authorization:** T02 requires update to block `.xpool_recovery/`. (`VERIFIED_FROM_SOURCE`).
- **Protected Namespace Isolation:** Requires separate backend credentials. (`BLOCKED`).
- **Jules HTTP API Confirmation:** (`BLOCKED`).
- **Quota Independence:** (`BLOCKED`).

## 12. Acceptance Checklist

- [ ] Single Authoritative Executor (Design documented).
- [ ] Fail-Closed State Machine (Design documented).
- [ ] Bounded streaming / No Base64 (Design documented).
- [ ] Audit Log Redaction (Design documented).
- [ ] Adapter-level `.xpool_recovery/` block (Not Implemented - Unit-tested pending).
- [ ] Test matrix scenarios executed against Mock (Not Implemented - Integration-tested in isolated storage pending).
- [ ] Host integration verification (Not Implemented - Verified against real backend pending).
- [ ] Final architecture approved (Not Implemented - Approved by owner pending).

---

`T04_DESIGN_STATUS: READY_FOR_OWNER_REVIEW`

`T03_ACCEPTANCE: PENDING`

`IMPLEMENTATION_AUTHORIZED: NO`

`PRODUCTION_AUTHORIZED: NO`

`CONCURRENCY_GUARANTEE: GUARDED_BY_EXCLUSIVE_EXECUTOR`

`BACKUP_ISOLATION: BLOCKED`

`UNRESOLVED_SECURITY_BLOCKERS: [Jules HTTP API Confirmation, Quota Independence Status, Protected Namespace Isolation]`
