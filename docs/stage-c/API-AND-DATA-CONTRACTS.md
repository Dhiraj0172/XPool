# API and Data Contracts

## Gateway REST API Contract

### Authentication
All requests must pass a `Bearer <token>` in the `Authorization` header.

### Endpoints

#### 1. `POST /api/v1/files/read`
- **Input Schema:** `{"target_path": "<string>"}`
- **Output Schema:** `{"status": "success", "data": "<base64_encoded_content>"}`
- **Errors:**
  - 404 Not Found
  - 403 Forbidden (Path outside JULES_ZONE)
- **Security Requirements:** Path canonicalization.

#### 2. `POST /api/v1/files/write`
- **Input Schema:** `{"target_path": "<string>", "data": "<base64_encoded_content>"}`
- **Output Schema:** `{"status": "success", "hash": "<sha256>"}`
- **Errors:**
  - 403 Forbidden
  - 500 Internal Server Error (Backup failure)
  - 429 Too Many Requests (Quota)
- **Security Requirements:** Mandatory backup interceptor trigger on overwrite.

#### 3. `POST /api/v1/files/delete`
- **Input Schema:** `{"target_path": "<string>"}`
- **Output Schema:** `{"status": "success"}`
- **Errors:** 404, 403, 500.
- **Security Requirements:** Mandatory backup interceptor trigger.

## Storage Adapter Backend Contract
- `read(path: str) -> bytes`: Returns raw bytes. Raises `FileNotFoundError`.
- `write(path: str, content: bytes) -> bool`: Returns True on sync success. Raises `IOError` or `QuotaExceededError`.
- `delete(path: str) -> bool`: Idempotent. Returns True if deleted or already gone.

## Deduplication (CAS) Metadata Contract
- Internal JSON/SQLite Schema:
  - `logical_path`: Primary key (e.g., `JULES_ZONE/docs/readme.txt`)
  - `cas_hash`: Reference to physical blob (e.g., `sha256:abc123...`)
  - `size_bytes`: Integer
  - `last_modified`: Unix timestamp
