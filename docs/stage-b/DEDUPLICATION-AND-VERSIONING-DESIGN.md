# Deduplication and Versioning Design

## Strategy
Whole-file Content-Addressed Storage (CAS) using SHA-256.

## Mechanism
When a file is written:
1. The gateway computes the file's SHA-256 hash.
2. The blob is written to the CAS store using its hash as the filename (e.g., `CAS/sha256:abc123...`).
3. A metadata reference is updated in the database linking the logical JULES_ZONE path to the CAS blob.

## Concurrency Protection
Writes to the CAS store use atomic temporary file renames (where supported by rclone) or conditional writes to prevent concurrent uploads of the same blob from corrupting data.

## Garbage Collection (GC)
- GC operates strictly via a dry-run default.
- It scans the reference metadata database. Any CAS blob with zero references is marked for deletion.
- Recovery points (backups) maintain explicit references to CAS blobs to prevent deletion of historic data.

## Storage Savings Measurement
Actual savings are measured by comparing the sum of logical file sizes in the reference DB against the total physical size of the CAS blob store directory.
