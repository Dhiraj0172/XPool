# Threat Model

## Trust Boundaries
1.  **Jules Client Environment**: Untrusted input. Assumed capable of sending adversarial payloads, including malformed paths and rapid concurrency.
2.  **API Gateway**: Trusted execution environment parsing and normalizing input.
3.  **Backup/Snapshot Storage**: Isolated zone, requiring distinct privileges unavailable to standard requests.
4.  **Storage Adapter/Mount**: Trusted channel out to the physical/cloud storage backend.

## Identified Threats & Mitigations

### 1. Path Traversal & Escape
- **Threat**: Client sends payloads attempting to escape `JULES_ZONE` via `../`, absolute paths, symlinks, junctions, or Unicode normalization tricks.
- **Mitigation**: Strict path normalization and canonicalization. Deny-by-default outside the prefix. Prohibit symlink/junction following across boundaries.

### 2. Bypass of Backup Gates
- **Threat**: Destructive operation is executed without saving a successful backup, or malicious client cancels midway corrupting state.
- **Mitigation**: Code execution strictly sequences: backup creation -> verification -> mutation. A failed backup immediately halts the flow.

### 3. Backup Corruption or Deletion
- **Threat**: An authorized Jules client explicitly deletes a backup version it shouldn't have access to.
- **Mitigation**: Backups are mapped to distinct internal storage paths or use isolated provider identities not accessible via the normal `JULES_ZONE` API rules.

### 4. Hash Collision / Deduplication Poisoning
- **Threat**: Maliciously crafted files that share a hash but contain different data cause legitimate files to be overwritten or restored improperly.
- **Mitigation**: Employ strong cryptographic hashes (e.g., SHA-256 or better). Use comprehensive deduplication tests. Ensure GC processes only prune truly unreferenced blobs.

### 5. Quota Exhaustion & Denial of Service
- **Threat**: Runaway client scripts cause massive data ingest, exhausting backend quotas, or massive concurrent requests exhaust memory/connections.
- **Mitigation**: Gateway rate-limits, enforces concurrency bounds, bounds request payload size, and truthfully propagates quota-exhausted errors without simulating success.

### 6. Credential Leakage
- **Threat**: Logs contain active tokens, rclone configs, or system secrets.
- **Mitigation**: Ensure strict log redaction. Pass configuration safely (e.g., via secure memory or strict file permissions), away from command-line arguments.
