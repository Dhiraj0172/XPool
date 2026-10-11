# T05: Windows Integration Requirements and Discovery

**Execution Environment Disclaimer:**
This discovery report was generated in a Linux environment. No live Windows host discovery, process inspection, or registry analysis was performed. All statements below distinguish strictly between documented assumptions and verified facts.

## A. Drive Visibility in the Interactive User Session
- **Requirement:** The `X:` drive must be visible and accessible within an interactive Desktop session (e.g., `explorer.exe`).
- **Assumption:** Using `rclone mount` with `--fuse-flag --VolumePrefix=\server\xpool` under the SYSTEM context will correctly expose the drive across session boundaries to interactive users.
- **Verified Fact:** Not verified.

## B. Pre-Login Availability
- **Requirement:** The drive must be mounted and available to background services before any user interactively logs in via RDP.
- **Assumption:** A Scheduled Task triggered `At Startup` under `NT AUTHORITY\SYSTEM` ensures pre-login mounting.
- **Verified Fact:** Not verified.

## C. WinFsp Service and Rclone Process Lifecycle
- **Requirement:** Rclone must run stably as a background process holding the WinFsp mount.
- **Assumption:** Rclone will run continuously without interactive UI Prompts and gracefully handle background execution.
- **Verified Fact:** Not verified on Windows.

## D. Correct User/Session Identity and Permissions
- **Requirement:** Gateway APIs and mounting processes must correctly authenticate and run under isolated permission scopes.
- **Assumption:** Windows Credential Manager under the `SYSTEM` context will securely store `rclone.conf` passwords and Gateway tokens, preventing ordinary users from extracting them.
- **Verified Fact:** Not verified.

## E. Startup Failure, Crash Recovery, Duplicate Prevention, and Clean Shutdown
- **Requirement:** The service must recover from crashes, prevent multiple instances from corrupting the mount, and unmount cleanly.
- **Assumption:** Windows Scheduled Tasks or a custom wrapper script will prevent duplicate executions of `rclone mount`.
- **Verified Fact:** Not verified. No script currently exists in the repository handling lock files or crash recovery.

## F. Network Loss, Stale Mounts, and Recovery Behavior
- **Requirement:** WinFsp must not lock the OS or `explorer.exe` permanently if cloud connectivity drops.
- **Assumption:** Rclone VFS caching (`--vfs-cache-mode full`) and WinFsp timeouts will gracefully handle network partitions.
- **Verified Fact:** Not verified.

## G. Credential Isolation and Secure Logging
- **Requirement:** Rclone and Gateway logs must not write plaintext tokens or passwords to disk.
- **Assumption:** Gateway DB schemas redact tokens (Verified via offline Python tests). Rclone logging will natively redact HTTP Authorization headers.
- **Verified Fact:** Gateway redaction verified offline. Rclone redaction assumed.

## H. Windows Path Handling, Reparse Points, Symlinks, and Path Traversal
- **Requirement:** `X:` must handle Windows path separators (`\`), junctions, and symlinks without escaping the root target directory.
- **Assumption:** Rclone VFS handles translation of Windows paths to remote paths securely.
- **Verified Fact:** Gateway API offline Python logic handles traversal correctly. WinFsp/Rclone integration behavior is not verified.

## I. Safe Interaction with Protected `.xpool_recovery` Namespace
- **Requirement:** The locally mounted `X:` drive must not expose the `.xpool_recovery` directory to the user.
- **Assumption:** Rclone filtering (e.g., `--exclude .xpool_recovery/**`) can hide the namespace from the WinFsp mount, while the internal BackupManager bypasses this by using separate Rclone RC commands.
- **Verified Fact:** Not verified. The exact filter flags required are not yet implemented or tested on Windows.

## J. Observability and Health Checks
- **Requirement:** The system must provide health checks that do not perform destructive operations.
- **Assumption:** Rclone RC `/core/stats` or `Test-Path X:\` can be used.
- **Verified Fact:** Not verified on Windows.
