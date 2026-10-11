# T05 External Execution Package

## Purpose
This package provides the reproducible execution sequence for validating the T05 Windows Integration milestone. Due to Linux sandboxing constraints in Stage C, this package must be executed on a separately provisioned, disposable Windows 11 VM.

## Safety Constraints
**WARNING:** These tests must NOT target the production `X:\` drive or any production cloud remote.
All tests MUST execute against a synthetic local mock remote and be mounted exclusively to the `Z:\` drive letter. Production credentials must not be installed on this VM.

## Prerequisites Checklist
1. [ ] **Isolated Windows 11 Pro VM** accessible via RDP or WinRM.
2. [ ] **Python 3.12+** installed natively.
3. [ ] **Rclone** binary added to System PATH.
4. [ ] **WinFsp** (FUSE) installed.
5. [ ] **Synthetic Data Source:** Create `C:\MockCloud` and populate with placeholder text files.
6. [ ] **Rclone Config:** Create an unencrypted `rclone.conf` with a `local` backend named `local_mock:` pointing to `C:\MockCloud`.
7. [ ] **Scheduled Task Setup:** Import the deployment script to run `rclone mount local_mock: Z: --vfs-cache-mode full --volname "XPool" --fuse-flag --VolumePrefix=\server\xpool` triggered `At Startup` under `NT AUTHORITY\SYSTEM`.

## Execution Commands & Test Harness

### Phase 1: Pre-Login Validation
- **Goal:** Verify drive visibility before interactive user sessions.
- **Action:** Reboot the VM. Do not log in via RDP. Using an external WinRM shell, execute:
  `Test-Path Z:\`
- **Expected Result:** `True`.

### Phase 2: Interactive Session Visibility
- **Goal:** Verify standard user access.
- **Action:** Log in via RDP as a non-admin user. Open `explorer.exe` or PowerShell. Execute:
  `dir Z:\`
- **Expected Result:** Directory listing matches `C:\MockCloud`.

### Phase 3: Service Lifecycle & Duplicate Prevention
- **Goal:** Verify process ownership and single-instance safety.
- **Action 1:** Execute `Get-Process rclone -IncludeUserName`.
- **Expected Result 1:** Process belongs to `NT AUTHORITY\SYSTEM`.
- **Action 2:** Manually trigger the Scheduled Task again.
- **Expected Result 2:** Wrapper script exits cleanly; `Z:\` remains stable.

### Phase 4: Crash Recovery
- **Goal:** Verify watchdog/task recovery.
- **Action:** Execute `Stop-Process -Name rclone -Force`. Wait 60 seconds.
- **Expected Result:** Rclone process restarts automatically. `Test-Path Z:\` returns `True`.

### Phase 5: Permission & Traversal Boundaries
- **Goal:** Verify credential hiding and path containment.
- **Action 1:** As standard user, execute `cmdkey /list`.
- **Expected Result 1:** No SYSTEM-level credentials visible.
- **Action 2:** Create junction `mklink /J C:\MockCloud\Junction C:\Windows`. Attempt to read `Z:\Junction\System32\cmd.exe` as standard user.
- **Expected Result 2:** Access Denied / Target unresolvable via remote FUSE mapping.

## Evidence Collection
Upon completion, capture the following artifacts and securely transmit them back to the repository owner:
1. `T05-Test-Output.log` (stdout/stderr from PowerShell commands).
2. Windows Event Viewer logs for Rclone crashes/restarts.
3. Component versions (`rclone version`, `python --version`, Windows OS Build number).

## Safe Cleanup
Execute:
1. `Unregister-ScheduledTask -TaskName "XPool-Gateway" -Confirm:$false`
2. `Stop-Process -Name rclone -Force`
3. `Remove-Item -Recurse -Force C:\MockCloud`
