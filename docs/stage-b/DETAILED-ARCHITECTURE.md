# Detailed Architecture and Data-Flow

## Legend
- **(E) Existing verified component**: A piece of infrastructure that we know currently exists in this state.
- **(P) Proposed component**: Code/logic to be built in Stage C.
- **(X) External dependency**: A system outside the gateway code (e.g., WinFsp).
- **(U) Unverified assumption**: Something we expect is configured a certain way, but lacks direct proof right now.

## Data-Flow and Boundaries Diagram

```text
========================================================================
1. Jules Request Flow & Authentication Boundaries
========================================================================

[Jules Client (U)]
       │ 1. HTTP Request + Auth Token
       ▼
[Gateway API Server (P)] ───────► [Auth Module (P)] (Verifies token)
       │ 2. Validated Schema Request
       ▼
[Path/AuthZ Module (P)] ────────► [Audit Logger (P)] (Logs decision)

========================================================================
2. JULES_ZONE vs Backup Isolation & Destructive Ordering
========================================================================

       │ 3. Canonicalized Request Path
       ▼
  Is it destructive? (Overwrite/Delete)
       ├── No ────────────┐
       │                  │
       ├── Yes            │
       ▼                  │
[Backup Manager (P)]      │
       │ 4. Read Orig     │
       ▼                  │
[Storage Adapter (P)]     │
       │ 5. Write to .xpool_recovery (P) (Isolated prefix)
       ▼                  │
  (Verify Backup Hash)    │
       ├── Fail -> 500 Abort
       │
       ├── Pass ──────────┘
       ▼
[Deduplication/CAS Engine (P)]
       │ 6. Deduplicate & resolve blob ref
       ▼

========================================================================
3. Storage Adapter and Cloud Backend Flow
========================================================================

[Storage Adapter (P)]
       │ 7. rclone rc commands / fs calls
       ▼
[Rclone RC Daemon (X)]
       │ 8. Network sync
       ▼
[Cloud Storage Backends (X)] (e.g., Google Drive)

========================================================================
4. Windows Mount & Session Visibility
========================================================================

[WinFsp FUSE Driver (X)] ◄──────► [Rclone Daemon (X)]
       │ 9. Global WinFsp Flags
       ▼
[Windows Subsystem (X)]
       │ 10. Maps as X:\
       ▼
[Interactive User Session (U)]

========================================================================
5. Failure & Recovery Paths
========================================================================

[Any Gateway Component (P)]
       │ Runtime Exception / Timeout
       ▼
[Gateway Error Handler (P)] ─────► [Audit Logger (P)] (Logs 'FATAL')
       │ Returns 50x to Jules Client
       ▼
[Safe Shutdown Hook (P)] (If process state is corrupted)
```

## System Boundaries
1.  **Jules Client**: Invokes local gateway endpoints.
2.  **API Gateway**: Terminates request, validates JSON schema, authenticates caller.
3.  **Authorization / JULES_ZONE Module**: Canonicalizes paths and enforces default-deny policies.
4.  **Backup Manager (Interceptor)**: Evaluates if operation is destructive. If yes, writes original data to `Protected Backup Store`.
5.  **Deduplication Engine**: Calculates SHA-256, maps file references to physical CAS blobs.
6.  **Storage Adapter**: Translates abstract operations to `rclone rc` commands.
7.  **Cloud Storage Backends**: Final resting place for data and backups.
8.  **Windows Mount**: WinFsp provides the `X:\` presentation layer parallel to the Gateway.

## Logical Components
- `src.gateway`: Web server / socket listener.
- `src.auth`: Token validation and identity mapping.
- `src.policy`: Path traversal defenses and capability matrix.
- `src.backup`: Copy-before-write workflows.
- `src.dedup`: CAS logic and SQLite/JSON reference mapping.
- `src.storage`: Rclone RC client and quota aggregator.

## Dependencies (Proposed)
- Python 3.12+
- `fastapi` & `uvicorn` (Gateway)
- `httpx` (Rclone RC communication)
- `structlog` (Audit Logging)
- `WinFsp` & `rclone` (Host dependencies)
