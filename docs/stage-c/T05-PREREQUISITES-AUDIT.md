# T05: Windows Integration Prerequisite Audit

## Environment Verification
The current execution environment is a **Linux** container (`Linux devbox 6.8.0 ... x86_64 GNU/Linux`). As such, no live Windows host or VM interactions could be performed. All isolated VM and target host test scenarios remain strictly untested in this context.

## Prerequisite Table

| Prerequisite | Status | Evidence | Minimum Action Needed |
| :--- | :--- | :--- | :--- |
| **Windows 11 Pro VM** | `MISSING` | Environment is Linux (`uname -a`) | Provision a disposable Windows 11 VM reachable via WinRM/RDP. |
| **Python 3.12 (on VM)** | `MISSING` | Requires VM provisioning | Install Python 3.12 natively on the target VM. |
| **Rclone Binary (on VM)** | `MISSING` | Requires VM provisioning | Deploy Rclone to the VM system path. |
| **WinFsp Binary (on VM)** | `MISSING` | Requires VM provisioning | Install the WinFsp FUSE dependency required by Rclone. |
| **Synthetic Local Backend** | `MISSING` | Requires VM provisioning | Create `C:\MockCloud` and configure `local_mock:` in `rclone.conf` on the VM. |
| **T05 Execution Script** | `AVAILABLE` | Existing T05 design docs outline the setup. | Execute the test script mapped against the mock local backend. |

## Test Plan Corrections
The `T05-ISOLATED-VM-TEST-PLAN.md` was reviewed. Scenario 6 originally stated it tested simulated network interruption via a mock HTTP server. It has been verified and properly contextualized that this test requires real `explorer.exe` and the WinFsp FUSE layer to prove how the Windows OS natively handles unresponsive I/O streams without crashing (BSOD), meaning it strictly relies on real Windows VM execution, not just a Python HTTP mock.
