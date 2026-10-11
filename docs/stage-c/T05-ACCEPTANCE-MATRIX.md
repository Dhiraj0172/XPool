# T05: Windows Integration Acceptance Matrix

| Criterion ID | Requirement | Current Status | Evidence Collected | Test Environment | Remaining Risks | Next Required Action | Owner Approval Req |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **WIN-01** | Drive visibility in interactive session | `BLOCKED` | None | VM Provisioning Unavailable | WinFsp flags may fail on specific Win11 builds | Execute Test Plan Scenario 2 | Yes |
| **WIN-02** | Pre-login availability | `BLOCKED` | None | VM Provisioning Unavailable | Scheduled task SYSTEM context may delay mount | Execute Test Plan Scenario 1 | Yes |
| **WIN-03** | Service and process lifecycle | `BLOCKED` | None | VM Provisioning Unavailable | Silent failures without watchdog | Execute Test Plan Scenario 3 | Yes |
| **WIN-04** | User/session identity isolation | `BLOCKED` | None | VM Provisioning Unavailable | Credential Manager token leakage | Execute Test Plan Scenario 7 | Yes |
| **WIN-05** | Crash recovery / duplicate prevention | `BLOCKED` | None | VM Provisioning Unavailable | Missing lock file logic in wrapper script | Execute Test Plan Scenarios 4 & 5 | Yes |
| **WIN-06** | Network loss recovery | `BLOCKED` | None | VM Provisioning Unavailable | OS hanging due to FUSE timeouts | Execute Test Plan Scenario 6 | Yes |
| **WIN-07** | Credential isolation | `DOCUMENTED` | Offline Python DB schemas redact tokens | Linux (Offline) | Rclone logs might leak | Verify Rclone log redaction | No |
| **WIN-08** | Windows path/symlink handling | `BLOCKED` | None | VM Provisioning Unavailable | Junctions escaping the mount | Execute Test Plan Scenario 8 | Yes |
| **WIN-09** | Safe interaction with `.xpool_recovery` | `BLOCKED` | None | VM Provisioning Unavailable | Rclone `--exclude` flag insufficiency | Execute Test Plan Scenario 9 | Yes |
| **WIN-10** | Safe Observability / Health Checks | `BLOCKED` | None | VM Provisioning Unavailable | None | Define health check script | Yes |

## Legend:
- `DOCUMENTED`: Requirement is analyzed and documented based on static code.
- `READ_ONLY_DISCOVERY_COMPLETE`: Host discovery scripts ran safely.
- `BLOCKED`: An isolated VM plan exists but has not been executed.
- `TESTED_IN_ISOLATED_VM`: Tests passed on a disposable Windows VM.
- `VERIFIED_ON_TARGET_HOST`: Tests passed on the actual production host.
- `BLOCKED`: Dependency missing.
- `NOT_RUN`: Environment did not allow execution.
