# Stage B Design Decisions

## Decision A: Jules Integration Interface
- **Recommended Option:** Local HTTP REST API over localhost (127.0.0.1).
- **Viable Alternative:** Local gRPC socket.
- **Advantages:** REST is universally supported, easily mockable, and allows straightforward schema validation via OpenAPI.
- **Disadvantages:** Slightly higher serialization overhead compared to gRPC.
- **Security Implications:** API must be bound strictly to loopback to prevent external network access. Caller authentication relies on an API token or local process identity where applicable.
- **Prerequisites:** A web framework (e.g., FastAPI) and validation libraries.
- **Test Strategy:** E2E mock client invoking local endpoints.
- **Status:** **PROPOSED** (Needs confirmation of Jules capabilities).

## Decision B: Storage Backend and Adapter
- **Recommended Option:** Abstract FileSystem Adapter wrapping the supported `rclone rc` API or invoking isolated subprocesses against a designated test config.
- **Viable Alternative:** Wrapping `WinFsp` system calls directly.
- **Advantages:** Adapting `rclone rc` provides structured error codes (quotas, partial failures) better than parsing raw filesystem errors.
- **Disadvantages:** Requires rclone running with an active RC server.
- **Security Implications:** Keeps gateway authorization tightly coupled to adapter requests; isolates test backends by changing the target remote in the config.
- **Prerequisites:** Running rclone process.
- **Test Strategy:** Unit tests injecting mock adapter errors, and isolated integration tests using a local directory remote.
- **Status:** **PROPOSED**.

## Decision C: JULES_ZONE Authorization
- **Recommended Option:** Strict Canonical Path Resolution (`os.path.realpath` / `pathlib.Path.resolve`) combined with `is_relative_to(JULES_ZONE_ROOT)`.
- **Viable Alternative:** Independent filesystem user ACLs.
- **Advantages:** Prevent `../` and symlink escapes reliably before reaching the adapter.
- **Disadvantages:** Complex handling of edge-case Unicode normalizations.
- **Security Implications:** A string-prefix check is vulnerable to "prefix confusion" (e.g., `JULES_ZONE_fake`). Canonicalization ensures the final destination is strictly within the subtree.
- **Prerequisites:** Python's `pathlib`.
- **Test Strategy:** Adversarial payload tests injecting symlinks and `../` sequences.
- **Status:** **DECIDED**.

## Decision D: Backup and Recovery Architecture
- **Recommended Option:** Copy-Before-Write to an isolated `.xpool_recovery` remote/bucket mapping.
- **Viable Alternative:** Object versioning natively provided by Google Drive.
- **Advantages:** True isolation. Natively storing copies under a separate service account prevents Jules from accessing or deleting them, whereas native Drive versions share the same item permissions.
- **Disadvantages:** Increased latency and duplicated storage for every destructive op.
- **Security Implications:** Must enforce strict sequential guarantees: backup -> verify hash -> destroy original. If backup fails, gateway returns 500.
- **Prerequisites:** A separate cloud identity/remote configuration for backups.
- **Test Strategy:** Fault injection at the backup step ensuring the subsequent delete is skipped.
- **Status:** **PROPOSED**.

## Decision E: Deduplication and Versioning
- **Recommended Option:** Whole-file Content-Addressed Storage (CAS) with SHA-256.
- **Viable Alternative:** Chunk-based deduplication (e.g., restic-style).
- **Advantages:** Simplifies cloud syncing and recovery. Chunking introduces massive metadata overhead unsuitable for standard Google Drive backends.
- **Disadvantages:** Small changes to large files require re-hashing and re-uploading the entire file.
- **Security Implications:** SHA-256 prevents trivial collision poisoning. Garbage Collection (GC) must be a dry-run default to prevent deleting referenced versions.
- **Prerequisites:** Cryptographic hashing libraries.
- **Test Strategy:** Concurrent write tests and exact-hash verification tests.
- **Status:** **PROPOSED**.

## Decision F: Windows Mount and Availability
- **Recommended Option:** Scheduled Task triggered "On Startup" (running as SYSTEM but configured to expose the drive to all sessions via `WinFsp-FUSE` global mount flag) + separate scheduled task for the Jules Gateway.
- **Viable Alternative:** Standard Windows Service using NSSM.
- **Advantages:** Scheduled tasks handle pre-login states well. The global FUSE flag solves the cross-session drive letter visibility issue.
- **Disadvantages:** Complex deployment script.
- **Security Implications:** Credentials must be securely stored in the Windows Credential Manager or protected config files, not in the task XML arguments.
- **Prerequisites:** Windows 11 Pro, WinFsp installed.
- **Test Strategy:** Restarting a Windows test host, verifying `X:\` exists via remote shell before an RDP login.
- **Status:** **BLOCKED** (Requires authorization for a Windows Integration Host).

## Decision G: Quota and Capacity Reporting
- **Recommended Option:** Direct query to `rclone rc` for specific remote quotas.
- **Viable Alternative:** Polling the `X:\` drive properties.
- **Advantages:** Avoids the false sum of overlapping union remotes by tracking individual quotas.
- **Disadvantages:** `rc` stats can sometimes be stale depending on the remote type.
- **Security Implications:** Ensures we never falsely report independent usable capacity without authoritative evidence.
- **Prerequisites:** Rclone RC integration.
- **Test Strategy:** Edge-case mock tests simulating exhausted specific remotes.
- **Status:** **PROPOSED** (Awaiting independent capacity evidence).

## Decision H: Logging, Secrets, and Operational Reliability
- **Recommended Option:** Structured JSON logging (e.g., `structlog`) with strict redaction filters. Secrets loaded strictly via `.env` or secure vault, never CLI.
- **Viable Alternative:** Standard text logging.
- **Advantages:** JSON logs are easily parseable by audit tools. Redaction filters prevent token leaks.
- **Disadvantages:** Slightly harder to read in raw console.
- **Security Implications:** Protects credentials. Health checks ensure safe shutdown on repeated failure.
- **Prerequisites:** `structlog` or similar library.
- **Test Strategy:** Log output verification tests ensuring tokens are masked.
- **Status:** **DECIDED**.
