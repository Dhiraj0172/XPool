# Windows Integration Specification

## Startup and Lifecycle
1. The integration relies on a Windows Scheduled Task named `XPool-Gateway`.
2. **Trigger:** `At Startup`.
3. **Identity:** `NT AUTHORITY\SYSTEM`.

## WinFsp / FUSE Configuration
- For a SYSTEM task to mount a drive (`X:\`) visible to an interactive Desktop user (e.g., `Domain\User`), `WinFsp` requires specific launch parameters.
- Command: `rclone mount google_unified: X: --vfs-cache-mode full --volname "XPool" --fuse-flag --VolumePrefix=\server\xpool` (Exact flags to be finalized in Stage D depending on WinFsp version).

## Credential Management
- `rclone.conf` must be encrypted.
- The password for `rclone.conf` and the Gateway API tokens will be stored in the Windows Credential Manager under the `SYSTEM` context.
- They are extracted via PowerShell at task startup.

## Testing Verification Plan
- **Status:** Currently BLOCKED.
- **Plan:** Provision a Windows 11 host. Install prerequisites. Run the automated task. Without logging in via RDP, execute a WinRM remote command to verify `Test-Path X:\`. Then log in via RDP and verify the drive appears in `explorer.exe`.
