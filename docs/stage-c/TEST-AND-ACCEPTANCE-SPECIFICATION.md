# Test and Acceptance Specification

## Test Categorization Matrix

| Test Type | Target Area | Environment Requirement | Execution Phase |
|---|---|---|---|
| **Unit** | Schemas, AuthZ logic, CAS Hashing | `OFFLINE_UNIT` | Pre-merge CI |
| **Integration** | Storage Adapter logic, Backup Engine | `ISOLATED_INTEGRATION` (Mock Remote) | Pre-merge CI |
| **Security** | Path Traversal, Credential Injection | `ISOLATED_INTEGRATION` | Nightly / Pre-merge CI |
| **Operations**| Pre-login FUSE visibility | `AUTHORIZED_WINDOWS_INTEGRATION` | Manual/Staging CI |

## Specific Acceptance Gates

1. **JULES_ZONE Escape Denied:** Sending `../` in a payload MUST result in a `403` or `400` and zero backend adapter calls.
2. **Backup Failure Blocks Deletion:** Injecting a mock fault into `BackupManager.write()` MUST prevent the primary file from being deleted.
3. **Data Integrity (Dedup):** Uploading the same 5MB file three times MUST result in only one physical 5MB CAS blob, and three logical database entries.
4. **Quota Transparency:** If the storage backend returns `429 Quota Exceeded`, the gateway MUST propagate the error to Jules, not queue it silently.

## Evidence Requirements
Tests cannot be marked "PASSED" via simple assertion. Evidence requires the raw output of `pytest` or `Playwright` captured in the session manifest.
