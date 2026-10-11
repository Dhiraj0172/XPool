# XPool Stage C: Security Remediation and Acceptance Plan

## 1. Current Baseline and Verified Facts
The repository contains a functioning, isolated `RcloneRCAdapter`, `BackupManager`, `OperationTracker` (SQLite), and a `SingleAuthoritativeExecutor`.
- **Tests:** Run strictly offline via deterministic mocks and local multi-process tests. No real backend is contacted.
- **Namespace Blocking:** The application layer strictly and reliably blocks `.xpool_recovery/` from public access.
- **SQLite Concurrency:** State transition updates are protected across multiple processes using `BEGIN IMMEDIATE` OS-level file locks.
- **TOCTOU Limitations:** `CREATE_ONLY` and general mutation TOCTOU races are mitigated locally by the executor thread-lock and pre-mutation re-validation, but remain vulnerable to external writers since the underlying backend lacks atomic conditional writes.
- **Deduplication:** `src/dedup/cas.py` is a placeholder. Content-addressed object reuse is not implemented.
- **Garbage Collection:** Active operation backup IDs are securely tracked to prevent premature deletion, but no actual deletion/GC loop exists in the codebase.

## 2. Four Blocker Analyses

**Blocker 1: Multi-Process SQLite Safety and Restart Reconciliation**
- **Analysis:** `OperationTracker` has been remediated. It correctly uses `isolation_level=None` and `BEGIN IMMEDIATE` to lock the SQLite DB file at the OS level across multiple Gateway processes, properly backing off during busy states. `reconcile_restarts()` accurately transitions abandoned `MUTATION_EXECUTING` operations to `UNCERTAIN` without claiming false success.
- **Status:** Process-level local tracking is safe. Atomicity across the network to remote storage remains fundamentally impossible for SQLite alone.

**Blocker 2: Enforceable Recovery Namespace Isolation**
- **Analysis:** Untrusted requests are perfectly blocked by `_get_remote_path()`. The internal `BackupManager` safely utilizes `_execute_rc()` avoiding public API routes.
- **Remaining Gap:** The entire application runs using a single Rclone RC daemon connection and a single credential set. If the application is compromised, the attacker inherits access to `.xpool_recovery/`.
- **Acceptance Decision:** Transitioning to `VERIFIED_WITH_EVIDENCE` requires provisioning a Dual Rclone instance setup or using Provider-level IAM ACLs to block the ordinary credentials. Status remains `PARTIAL`.

**Blocker 3: TOCTOU and Remote Mutation Guarantees**
- **Analysis:** The `operations/uploadfile` and `operations/deletefile` endpoints via Rclone RC lack atomic compare-and-swap preconditions.
- **Limit:** The executor re-evaluates the hash immediately before mutation. However, the network roundtrip gap between `hash()` and `uploadfile()` remains exposed. External writers can silently overwrite data.
- **Safe Interim Policy:** Completely restrict external users from directly editing files on the Google Drive backend. Status remains `BLOCKED`.

**Blocker 4: Recovery Retention and Garbage Collection**
- **Analysis:** `get_active_backup_ids()` correctly protects active operations (`BACKUP_VERIFIED`, `UNCERTAIN`).
- **Non-Destructive GC Design:** A background script MUST NOT delete files blindly. It must:
  1. Read remote objects via `rclone list`.
  2. Fetch `get_active_backup_ids()`.
  3. Discard any object ID present in the active set from the candidate list.
  4. Compare the age of remaining objects against an Owner-Approved Retention Policy (e.g., strictly > 30 days).
  5. Dry-run output the candidates for audit.
- **Status:** Since this GC logic is not implemented, safety relies on indefinite retention. `RECOVERY_GC_SAFETY: NOT_IMPLEMENTED`.

## 3. Threat Model and Explicit Trust Boundaries
- **Trust Boundary:** The Gateway application logic and the single Rclone RC daemon.
- **Threat (External Writer):** Users modifying Google Drive directly. *Risk: Unmitigated TOCTOU.*
- **Threat (Internal RCE):** Application compromise. *Risk: Unmitigated Backend Namespace bypass.*
- **Threat (Process Crash):** Gateway dies mid-mutation. *Mitigated:* DB state enforces `UNCERTAIN` and prevents false success.

## 4. Recommended Architecture and Implementation Sequence
1. **GC Script:** Implement the non-destructive GC dry-run script.
2. **Dual Rclone Instances:** Provision a second Rclone daemon strictly for backup operations to achieve true credential isolation.

## 5. Concrete Acceptance Criteria
See `docs/stage-c/STAGE-C-ACCEPTANCE-MATRIX.md`.

## 6. Required Tests and Expected Security Properties
- **Tested Offline:** Multi-process SQLite writes via `BEGIN IMMEDIATE`, GC active-id protection, adapter path traversal blocks, executor source re-validation, database persistence failures post-mutation.
- **Missing / Real-Backend Tests:** Real-backend IAM ACL isolation proofs, real-backend Rclone API behavior mapping.

## 7. Required Evidence for Acceptance
- Provider-level IAM configuration proving Gateway credentials natively lack permission to read/write `.xpool_recovery/`.

## 8. Dependencies on Unconfirmed Capabilities
- Rclone RC does not support `If-Match` conditional mutations.
- Google Jules HTTP REST integration capability remains unconfirmed.

## 9. Safe Interim Restrictions
- Do not allow external human users to modify the Google Drive backend directly.
- Preserve all `.xpool_recovery` artifacts indefinitely (no destructive GC).
- Do not claim CAS deduplication is implemented.

## 10. Owner Decisions Required
- Approve the shift to Dual Rclone daemons for backend namespace isolation.
- Accept the residual TOCTOU external-writer risk or authorize breaking the Rclone abstraction to use native Provider APIs.

## 11. Implemented vs Verified Behavior
- *Implemented & Tested Offline:* App-layer namespace blocking, local executor locking, multi-process SQLite DAG transitions, database failure handling.
- *Designed, Not Implemented:* GC cleanup loop, CAS Deduplication.
- *Blocked:* True backend namespace isolation, True atomic conditional writes against external writers.

## 12. Next-Stage Roadmap
1. Approve Residual Risks (Owner).
2. Execute Windows Integration (`T05-WINDOWS-INTEGRATION`) to prove WinFsp mounts securely pre-login using the safe interim policies.
