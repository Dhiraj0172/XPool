# Implementation Specification

## Common Contracts

This specification defines the strict API contracts and boundaries for all implementation tasks.

### 1. Types and Identifiers
- `JulesPath`: A canonical, fully resolved absolute string path ensuring no `../` traversal.
- `ContentHash`: A SHA-256 hex string (`sha256:[a-f0-9]{64}`).
- `RecoveryID`: A timestamped UUID string used to trace a backup to its original mutation.

### 2. Request and Response Schemas
- **Success Response**: `{"status": "ok", "data": <Any>}`
- **Error Response**: `{"status": "error", "code": <ErrorCode>, "message": <String>}`
- **Standard HTTP Error Codes**:
  - 400 (Bad Request / Invalid Schema)
  - 401 (Unauthorized Token)
  - 403 (Permission Denied / JULES_ZONE bounds exceeded)
  - 429 (Backend Quota Exceeded)
  - 500 (Backup verification failed / Backend inaccessible)
  - 504 (Timeout)

### 3. Storage Adapter Contract
```python
class StorageAdapter(Protocol):
    def read(self, path: JulesPath) -> bytes: ...
    def write(self, path: JulesPath, data: bytes) -> bool: ...
    def delete(self, path: JulesPath) -> bool: ...
    def list(self, path: JulesPath) -> List[str]: ...
    def stats(self, remote: str) -> Dict[str, Any]: ...
```

### 4. Backup and Recovery Protocol
- Any call to `StorageAdapter.write()` resulting in an overwrite, or `StorageAdapter.delete()`, MUST first trigger `BackupManager.create_recovery_point(path)`.
- If `create_recovery_point` raises an exception or returns `False`, the destructive operation is immediately cancelled and a `500` error is returned to the client.

### 5. Jules Integration Interface
- The Gateway will expose an HTTP REST API over localhost (127.0.0.1:8080).
- Authentication requires a static Bearer token configured via environment variables.

### 6. Windows Integration Contract
- The system expects a deployment script that configures a Scheduled Task.
- The task will execute `rclone mount google_unified: X: --volname "XPool" --vfs-cache-mode full`.
- Global visibility requires WinFsp registry flags or equivalent, to be strictly verified in `AUTHORIZED_WINDOWS_INTEGRATION` tests.

## Blockers and Invariants
- `stage_2_host_credential_integration = UNAUTHORIZED_PENDING_APPROVAL`: No credentials may be retrieved or utilized yet.
- `QUOTA_INDEPENDENCE_STATUS = BLOCKED`: Capacity calculations must assume shared underlying storage.
