# T05: Isolated VM Test Plan

## Overview
This plan defines the exact procedures for verifying the Windows integration architecture on a **disposable, isolated Windows 11 VM**.
**CRITICAL:** Under no circumstances will these tests target the production `X:` drive or production cloud remotes. All tests must use a synthetic local backend (`C:\MockCloud`) and a non-production drive letter (e.g., `Z:`).

## Setup Prerequisites
1. Provision an isolated Windows 11 Pro VM.
2. Install Python 3.12, Rclone, and WinFsp.
3. Create a mock local remote in `rclone.conf` pointing to `C:\MockCloud`.
4. Deploy the Gateway Scheduled Task configured to mount the mock remote to `Z:\`.
5. Enable WinRM for remote execution.

---

## Test Scenarios

### 1. Baseline Drive Enumeration & Pre-login Availability
- **Setup:** VM is booted, stopped at the Windows login screen. No user has logged in interactively.
- **Action:** Execute a remote WinRM script: `Test-Path Z:\`.
- **Expected Result:** Returns `True`. The drive is mounted by SYSTEM successfully in the background.
- **Evidence:** WinRM PowerShell output.
- **Cleanup:** None.

### 2. Interactive-Session Visibility
- **Setup:** Proceed from Scenario 1.
- **Action:** Log in via RDP as a standard user. Open `explorer.exe`. Navigate to `Z:\`.
- **Expected Result:** The `Z:\` drive is visible, browsable, and matches the contents of `C:\MockCloud`.
- **Evidence:** Screenshot of `explorer.exe` or local PowerShell `dir Z:\` output under the user context.
- **Cleanup:** None.

### 3. Service and Process Lifecycle
- **Setup:** Rclone is actively mounting `Z:\`.
- **Action:** Query the process list for `rclone.exe`. Ensure it is running under `NT AUTHORITY\SYSTEM`.
- **Expected Result:** Process owner is SYSTEM. No interactive console window is visible to the user.
- **Evidence:** `Get-Process rclone -IncludeUserName` output.
- **Cleanup:** None.

### 4. Duplicate Startup Attempts
- **Setup:** Rclone is actively mounting `Z:\`.
- **Action:** Manually trigger the `XPool-Gateway` Scheduled Task a second time.
- **Expected Result:** The wrapper script detects the existing lock/process and safely exits without corrupting the existing `Z:\` mount.
- **Evidence:** Task execution history logs (Event Viewer).
- **Cleanup:** None.

### 5. Crash and Restart Recovery
- **Setup:** Rclone is actively mounting `Z:\`.
- **Action:** forcefully terminate the rclone process: `Stop-Process -Name rclone -Force`. Wait 60 seconds.
- **Expected Result:** The Windows Scheduled Task recovery trigger (or a watchdog service) restarts the process. `Test-Path Z:\` returns `True` again.
- **Evidence:** Process PID changes; `Test-Path` output over time.
- **Cleanup:** None.

### 6. Simulated Network Interruption
- **Setup:** Rclone is mounting `Z:\` targeting an isolated local mock HTTP server (e.g., `respx` or `http.server` running locally on the VM) to test WinFsp behavior during network loss.
- **Action:** Terminate the mock HTTP server. Attempt to open a text file on `Z:\` via `explorer.exe`.
- **Expected Result:** `explorer.exe` hangs temporarily, then returns a standard Windows I/O error timeout. The OS itself does not crash or bluescreen (BSOD). This explicitly verifies how the Windows OS and WinFsp FUSE layer handle unresponsive storage, requiring the real Windows integration stack.
- **Evidence:** Windows Event Logs.
- **Cleanup:** Restart mock HTTP server.

### 7. Permission Boundaries and Credential Isolation
- **Setup:** `rclone.conf` password stored in SYSTEM Credential Manager.
- **Action:** As a standard interactive user, execute `cmdkey /list`.
- **Expected Result:** The SYSTEM-level credentials are not visible or exportable.
- **Evidence:** `cmdkey` output.
- **Cleanup:** None.

### 8. Path Traversal and Reparse-Point Handling
- **Setup:** Create a Windows Directory Junction inside `Z:\` pointing to `C:\Windows`.
- **Action:** Attempt to read `Z:\Junction\System32\cmd.exe`.
- **Expected Result:** Access is denied or the junction fails to resolve remotely, preventing arbitrary local file read via the mount.
- **Evidence:** PowerShell error output.
- **Cleanup:** Delete junction.

### 9. Protected Namespace Access Attempts
- **Setup:** Configure Rclone mount with `--exclude .xpool_recovery/**`. Create `.xpool_recovery` in `C:\MockCloud`.
- **Action:** In the user session, attempt `cd Z:\.xpool_recovery` or `cat Z:\.xpool_recovery\file.txt`.
- **Expected Result:** `Path not found` or `Access Denied`. The directory is invisible to WinFsp.
- **Evidence:** PowerShell command failure output.
- **Cleanup:** None.

### 10. Safe Cleanup of Synthetic Test Resources
- **Setup:** All previous tests completed.
- **Action:** Run a defined uninstallation script.
- **Expected Result:** `Z:\` unmounts. Scheduled task is removed. `C:\MockCloud` is deleted.
- **Evidence:** Script execution success output.
- **Cleanup:** N/A.
