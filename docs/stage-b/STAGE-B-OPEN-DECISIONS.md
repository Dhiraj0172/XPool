# Stage B Open Decisions and Blockers

## Pending Owner Decisions
The following items require explicit owner feedback before implementation (Stage C) can proceed securely:

1. **Jules Integration Protocol (Decision A)**:
   - *Question:* Is a localhost HTTP REST API the correct interface for the target Jules environment, or is a specific plugin/MCP required?
2. **Backup Storage Mapping (Decision D)**:
   - *Question:* Do we have a distinct rclone remote/cloud account provisioned specifically for the `.xpool_recovery` data to guarantee strict isolation from the primary Jules tokens?

## Blocked Requirements
1. **Windows Mount Visibility (Decision F)**:
   - *Blocker:* `stage_2_host_credential_integration = UNAUTHORIZED_PENDING_APPROVAL`. We cannot write deployment scripts or verify WinFsp cross-session visibility without authorization for a Windows Integration Host.
2. **Quota Independence (Decision G)**:
   - *Blocker:* `QUOTA_INDEPENDENCE_STATUS = BLOCKED`. We must assume shared quota pools until authoritative evidence proves the underlying accounts do not overlap.
3. **General Implementation**:
   - *Blocker:* `authorization_gate_passed = false`. No code can be written or systems touched yet.
