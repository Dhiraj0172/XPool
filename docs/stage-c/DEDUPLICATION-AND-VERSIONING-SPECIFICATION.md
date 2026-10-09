# Deduplication and Versioning Specification

## Deduplication Strategy
- **Format:** Whole-file Content-Addressed Storage (CAS).
- **Algorithm:** SHA-256.

## Write Workflow
1. Client sends `POST /write` with payload.
2. Gateway streams payload into memory (or temp file) and computes SHA-256 hash (`H`).
3. Gateway queries Deduplication DB for `H`.
4. If `H` does not exist in physical storage, payload is written to `CAS/sha256:{H}`.
5. Reference metadata mapping `JULES_ZONE_PATH -> CAS/sha256:{H}` is created/updated.

## Versioning
When a file is overwritten, its previous logical reference is moved to a version history table linked to its backup `RecoveryID`. The physical CAS blob is left untouched.

## Garbage Collection (GC) Safety
- GC must operate in **dry-run mode** by default.
- It calculates `Set(All CAS blobs) - Set(Live References) - Set(Version History References)`.
- Physical blobs are only deleted if their reference count strictly equals 0.
- Interrupted writes generating orphaned CAS blobs will be cleaned up by GC on subsequent runs.
