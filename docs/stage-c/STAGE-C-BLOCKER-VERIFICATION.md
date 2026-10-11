# XPool Stage C: Security Blocker Verification

## 1. Executive Summary

This report investigates the unresolved Stage C security blockers regarding Jules HTTP API support, Quota Independence, and Protected Namespace Isolation (T03/T04). This was a read-only validation exercise. No source code modifications, config changes, or production infrastructure probes were executed.

**Final Status Summary:**
`JULES_HTTP_API_STATUS: UNCONFIRMED`
`QUOTA_INDEPENDENCE_STATUS: BLOCKED`
`PROTECTED_NAMESPACE_ISOLATION: BLOCKED`
`T03_ACCEPTANCE: PENDING`
`BACKUP_ISOLATION: BLOCKED`
`TOCTOU_SAFETY: BLOCKED`
`authorization_gate_passed: false`
`stage_2_host_credential_integration: UNAUTHORIZED_PENDING_APPROVAL`
`PRODUCTION_AUTHORIZED: NO`

## 2. Evidence Inventory

- **API Contracts:** `docs/stage-c/API-AND-DATA-CONTRACTS.md`
- **Gateway Architecture:** `docs/stage-c/T04_SECURITY_DESIGN.md`
- **Jules Integration Design:** `docs/stage-b/JULES-INTEGRATION-DESIGN.md`
- **Quota Design:** `docs/stage-b/QUOTA-AND-CAPACITY-DESIGN.md`
- **Baseline Config:** `docs/BASELINE.md`
- **Storage Adapter Code:** `src/storage/rclone_adapter.py`
- **Backup Manager Code:** `src/backup/manager.py`
- **Tests Executed:** `tests/unit/test_backup_manager.py`, `tests/unit/test_storage_adapter.py`

## 3. Workstream 1: Jules HTTP API Confirmation

- **API Identity:** Localhost HTTP REST API over port 8080.
- **Evidence Sources:** `docs/stage-b/JULES-INTEGRATION-DESIGN.md`, `docs/stage-c/STAGE-C-OPEN-BLOCKERS.md`.
- **Confirmed vs Assumed Capabilities:** The project assumes Google Jules can execute raw HTTP REST requests to a localhost port via an injected Bearer token. No authoritative evidence, official Jules capability document, or live integration test confirms this assumption.
- **Permission & Auth Requirements:** Bearer token passed in the `Authorization` header.
- **Missing Evidence:** We lack confirmation from the Jules orchestration layer that standard HTTP networking to localhost is permitted, as opposed to requiring an MCP (Model Context Protocol) plugin or native FUSE mapping.
- **Safe Verification Procedure:** Deploy a minimal mock Python `http.server` on the Jules host and attempt to trigger an HTTP GET from the Jules agent.
- **Status:** `UNCONFIRMED`

## 4. Workstream 2: Quota Independence

- **Reported Remotes:** `gdrive_pro_1`, `gdrive_pro_2`, `gdrive_pro_3`, `gdrive_plus_1` all bound to `UnifiedStoragePool`.
- **Evidence-backed relationship:** `docs/BASELINE.md` lists these members. `docs/stage-b/QUOTA-AND-CAPACITY-DESIGN.md` explicitly warns that union remotes often falsely sum overlapping quotas.
- **Confidence/Unknowns:** We have absolutely no evidence that these four remotes correspond to distinct, independent provider accounts. If they are Shared Drives on the same Google Workspace account, their capacity is entirely pooled.
- **Historical Aggregate Capacity:** Not trustworthy. Summing 15.391 TiB across shared pool members inflates the true underlying usable capacity.
- **Missing Evidence Needed:** We must review the underlying rclone configuration (`rclone.conf` or admin console limits) or execute non-destructive queries to each underlying remote directly to prove independent limits.
- **Status:** `BLOCKED`

## 5. Workstream 3: Protected Namespace and T03 Findings (Isolation and TOCTOU)

### Invariant 1: Alternate paths/direct API bypass prevention
- **File/Function:** `docs/stage-c/T04_SECURITY_DESIGN.md`
- **Mechanism:** Gateway routing logic blocks `.xpool_recovery/`.
- **Bypass Analysis:** If users have direct backend access, or if the rclone adapter itself doesn't hard-block it, the logical gateway check is bypassable.
- **Status:** `PARTIALLY_SUPPORTED` (Designed but not fully isolated).

### Invariant 2: Protected-prefix enforcement at adapter
- **File/Function:** `src/storage/rclone_adapter.py` -> `_get_remote_path()`
- **Mechanism:** It blocks targeting `.` (JULES_ZONE_ROOT), but *lacks* `.xpool_recovery/` enforcement entirely.
- **Status:** `NOT_PROVEN`

### Invariant 3: Backup authority separation
- **File/Function:** `docs/stage-c/T04_SECURITY_DESIGN.md`
- **Mechanism:** Design proposes separate internal authorization, but current codebase shares a single `RcloneRCAdapter` instance.
- **Status:** `NOT_PROVEN`

### Invariant 4: Shared rclone credentials bypass
- **File/Function:** Architecture
- **Mechanism:** Gateway uses one RC daemon with full credentials.
- **Bypass Analysis:** A path traversal flaw in the Gateway or an external attacker reaching the RC port gives full access to `.xpool_recovery`.
- **Status:** `NOT_PROVEN`

### Invariant 5: TOCTOU on missing source (`CREATE_ONLY`)
- **File/Function:** `src/backup/manager.py` -> `create_recovery_point()`
- **Mechanism:** Returns `CREATE_ONLY` on `FileNotFoundError`.
- **Bypass Analysis:** The Gateway lacks native backend conditional writes. Worker A gets `CREATE_ONLY`, pauses. Worker B creates file. Worker A resumes and overwrites B's file.
- **Status:** `NOT_PROVEN` (TOCTOU Safety = BLOCKED).

### Invariant 6: Durable backup metadata before mutation
- **File/Function:** `src/backup/manager.py` -> `create_recovery_point()`
- **Mechanism:** Calculates backend hash, performs backend copy, verifies hash matches before returning.
- **Test Evidence:** `test_backup_integrity_mismatch_aborts` passes.
- **Status:** `PROVEN_BY_AVAILABLE_EVIDENCE` (At a single-request level, not cross-process).

### Invariant 7: Concurrent requests bypassing backup invariants
- **File/Function:** `docs/stage-c/T04_SECURITY_DESIGN.md` (Single Authoritative Executor)
- **Mechanism:** Documented design mitigates this, but it is not implemented, and residual risks (delayed network packets) remain.
- **Status:** `NOT_PROVEN`

### Invariant 8: Garbage Collection vs Active Operations
- **File/Function:** `docs/stage-c/T04_SECURITY_DESIGN.md`
- **Mechanism:** Documented DB-aware GC, but no code exists.
- **Status:** `NOT_PROVEN`

## 6. Tests/Checks Executed

**Command:** `python3 -m pytest -v tests/unit/test_backup_manager.py tests/unit/test_storage_adapter.py`
**Result:** 16 tests collected and passed in ~20 seconds.
**Relevance:** Proves the *isolated mock* logic of the `BackupManager` correctly aborts on write failure and hash mismatch. Proves path canonicalization blocks `C:/Windows/` escapes. It does *not* prove real backend enforcement or distributed concurrency safety.

## 7. Smallest Safe Next Steps (Ordered)

1. **Jules HTTP Verification:** Have the Owner execute a non-destructive curl/HTTP GET from the Jules agent to an arbitrary local socket to prove HTTP communication is allowed.
2. **Quota Verification:** Extract non-sensitive `rclone about` data for each individual sub-remote (`gdrive_pro_1`, etc.) independently to verify if their free space values are identical (indicating a pooled drive).
3. **Namespace Isolation Fix:** Modify `src/storage/rclone_adapter.py` to hardcode a block against `.xpool_recovery/` at the adapter level.
4. **Concurrency Implementation:** Authorize implementation of the proposed "Single Authoritative Executor" to mitigate the TOCTOU `CREATE_ONLY` race.

## 8. Explicit Confirmation

I confirm that no production changes, source code modifications, credential injections, active mutations, or config alterations occurred during this read-only validation exercise. All operations strictly adhered to the mandatory governance policies.
