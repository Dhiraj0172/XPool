# Windows Mount and Persistence Design

## Architecture
The system utilizes WinFsp wrapped by rclone to map the cloud `google_unified:` remote to `X:\`.

## Pre-login and Interactive Visibility
To fulfill the requirement of availability before interactive login AND visibility within the user session:
- **Service Identity**: A Windows Scheduled Task configured to trigger "At Startup" running under the `SYSTEM` account.
- **Drive Letter Visibility**: Standard SYSTEM drives are hidden from user sessions. The mount command will explicitly use WinFsp's globally visible FUSE flags (e.g., via registry or `WinFsp-FUSE` launcher parameters) to broadcast `X:\` to all sessions.

## Safe Startup Ordering
1. Network availability check.
2. Credentials loaded from secure vault (Windows Credential Manager) by a bootstrap script.
3. Rclone RC daemon starts.
4. Rclone mount command initiates the `X:\` drive.
5. Gateway service starts.

## Failure Recovery
The task is configured to restart automatically on failure. Cache directories are explicitly bounded (`--vfs-cache-max-size`) to prevent filling the C:\ drive and are retained across reboots to recover interrupted uploads.

## Testing Strategy
This configuration explicitly requires testing on an Authorized Windows Integration Host. We will simulate a reboot, remotely verify the RC server is up, and then log in via RDP to verify `X:\` is visible in Explorer.
