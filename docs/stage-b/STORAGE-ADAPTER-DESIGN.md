# Storage Adapter Design

## Interface Boundary
The `StorageAdapter` is an abstract Python class. The production implementation connects via HTTP to the `rclone rc` (Remote Control) daemon.

## Remote Selection
The configured remotes (e.g., `gdrive_pro_1`) are specified in the backend configuration. The adapter directs operations to the unified union remote (e.g., `google_unified:`) for transparent load balancing as per the `epall/epmfs` policies.

## Test vs Production Backends
- **Production**: Uses the `google_unified:` rclone configuration.
- **Isolated Tests**: The adapter is instantiated pointing to a `local_mock:` remote (a temporary local directory) via the same `rclone rc` interface, guaranteeing identical behavior mapping without risking real data.

## Failure Handling
The adapter detects partial writes and automatically retries safe (idempotent) operations up to 3 times with exponential backoff. Non-recoverable errors (e.g., permanent permission denied) are passed immediately to the gateway layer to halt processing.
