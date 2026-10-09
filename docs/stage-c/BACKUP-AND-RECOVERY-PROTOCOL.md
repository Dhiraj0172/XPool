# Backup and Recovery Protocol

## The Mandatory Pre-Mutation Hook
Every destructive mutation (overwrite, delete, truncate) executed by the `StorageAdapter` must intercept the call and execute the Backup Sequence.

### Backup Sequence
1. **Identify Object:** Retrieve current object metadata and content via `StorageAdapter.read()`.
2. **Assign Recovery ID:** Generate `timestamp_UUID` for the recovery point.
3. **Write Backup:** Write the payload to `google_unified:/.xpool_recovery/<RecoveryID>_original_name`.
4. **Integrity Check:** Read the newly written backup and compare its SHA-256 hash to the original payload hash.
5. **Commit:** If hashes match, proceed with the destructive mutation on the primary object.
6. **Abort:** If backup writing or hashing fails, abort the operation entirely. Return `500 Internal Server Error`. The original primary object remains untouched.

## Recovery Point Isolation
- The `.xpool_recovery` namespace is filtered out of all `JULES_ZONE` responses.
- Jules tokens cannot issue `DELETE` or `WRITE` operations targeting `.xpool_recovery`.

## Garbage Collection
Backups are retained indefinitely until an Administrator issues a specific retention-pruning command.
