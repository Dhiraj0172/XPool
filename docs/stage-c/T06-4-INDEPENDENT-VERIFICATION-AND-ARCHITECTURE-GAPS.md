# T06-4: Independent Verification and Architecture Gaps

## 1. Executive Summary
This document summarizes the final state of the T04 Security Design and T06.x Remediation implementations before handoff to Stage T05 (Windows Integration). The offline repository has been verified to enforce the stated security invariants using the `pytest` test suite, but significant architectural gaps and blockers remain due to backend and environmental limitations.

## 2. Evidence of Verification
All 63 offline tests currently pass, confirming that the local application layer accurately adheres to the designed protocol constraints:
- `test_adversarial.py`: 22 tests passing, validating strict application-layer path traversal prevention, duplicate operation state enforcement, exception redaction, local TOCTOU mitigation via pre-mutation hash revalidation, and multi-process safety via SQLite locking.
- `test_api.py`: 19 tests passing, validating Gateway HTTP limits (10MB body max), content-length bounding, valid JSON schema enforcement, namespace protection on API routes, and rejection of unrecognized methods.
- `test_backup_manager.py`: 4 tests passing, covering CREATE_ONLY observation safety, integrity mismatch blocks, and backup path escapes.
- `test_common.py`: 6 tests passing, covering canonical path behaviors, config validation, and Pydantic field boundaries.
- `test_storage_adapter.py`: 12 tests passing, covering remote path mappings, conditional network retries, and fallback behaviors for missing operations.

## 3. Architecture Gaps & Unresolved Blockers
The following critical gaps cannot be resolved strictly within the current isolated gateway and necessitate owner awareness or changes to the backend infrastructure:

### Gap 1: TOCTOU / Missing Backend Atomic Mutations
**Description:** `rclone` does not natively expose or enforce `If-Match` ETags or conditional mutations across most remote storage targets (via RC).
**Status:** `BLOCKED`
**Consequence:** The local gateway uses double-hashing (pre/post-operation checks) to narrow the TOCTOU window locally. If a remote external writer mutates the source mid-flight, the Gateway may backup the old data and overwrite the new data. True atomic conditional operations require native provider support.

### Gap 2: Unified Backend Credentials
**Description:** Gateway user operations and the privileged Backup Manager operate using the exact same `rclone` daemon and authentication context.
**Status:** `PARTIAL`
**Consequence:** An exploit within the Gateway could hypothetically call `_execute_rc` directly and bypass the `.xpool_recovery/` application-layer block. Cryptographic namespace separation requires two distinct sets of cloud IAM credentials and potentially dual backend daemon instances.

### Gap 3: Garbage Collection Safety
**Description:** Backup Manager produces isolated CAS blobs in `.xpool_recovery/`.
**Status:** `NOT_IMPLEMENTED`
**Consequence:** The retention policy depends on a background Garbage Collection (GC) script that does not yet exist. The DB tracks active backup IDs, but there is no mechanism yet to safely reclaim remote quota.

### Gap 4: T05 Platform Constraints
**Description:** The system target environment is Windows 11 under WinFsp.
**Status:** `BLOCKED` (Awaiting Owner Execution)
**Consequence:** The development sandbox environment is Linux. End-to-end Windows execution and validation of path cases, authentication, and pipeline safety rely exclusively on the `T05-EXTERNAL-EXECUTION-PACKAGE.md` being performed independently by the Owner on an authorized node.

## 4. Final Final Handoff Status

`T04_DESIGN_STATUS: READY_FOR_OWNER_REVIEW`
`T03_ACCEPTANCE: PENDING_EXTERNAL_TESTING`
`IMPLEMENTATION_AUTHORIZED: NO`
`PRODUCTION_AUTHORIZED: NO`
`UNRESOLVED_SECURITY_BLOCKERS: [TOCTOU_RACE_CONDITION, UNIFIED_BACKEND_CREDENTIALS, GC_NOT_IMPLEMENTED, WINFSP_UNTESTED]`
