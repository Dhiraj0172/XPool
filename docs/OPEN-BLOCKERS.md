# Open Blockers and Safety Constraints

The project operates under strict safety guidelines. We must fail closed. Progression to subsequent stages (especially Stage C and E) cannot occur until the following constraints are explicitly resolved.

## Known Governance State (From User Specification)

The following governance variables are currently asserted and act as blockers against deployment or unauthorized action:

*   **PHASE1_FINAL_STATUS**: `PHASE_1_COMPLETE_WITH_BLOCKERS`
*   **authorization_gate_passed**: `false`
*   **stage_2_host_credential_integration**: `UNAUTHORIZED_PENDING_APPROVAL`
*   **ACTION_A_STATUS**: `PENDING_OWNER_APPROVAL`
*   **ACTION_A_EXECUTION_READINESS**: `NOT_READY`
*   **ACTION_B_STATUS**: `PENDING_OWNER_APPROVAL`
*   **ACTION_B_EXECUTION_READINESS**: `NOT_READY`
*   **PENDING_UPLOAD_SAFETY**: `UNKNOWN`
*   **QUOTA_INDEPENDENCE_STATUS**: `BLOCKED`

## Required Actions

1.  **Test Environment Provisioning**: An isolated environment (mock cloud backend/test accounts) must be authorized for Stage C/D testing.
2.  **Windows Integration Host**: To pass the Phase 2 requirements (Pre-login availability + Interactive session visibility), an explicit Windows test host and authorization are needed. We cannot test WinFsp behavior in an isolated Linux runner reliably without this.
3.  **No Action on `X:\`**: Absolutely no operations are to be performed against any live `X:\` or `google_unified:` mount without removing the `authorization_gate_passed = false` blocker.

## Outstanding Questions

- What specific API mechanism (e.g., REST API, Local gRPC, specific protocol) is the Jules Client natively configured to consume?
- Do we have dedicated test credentials available for the isolated backend testing phase?
