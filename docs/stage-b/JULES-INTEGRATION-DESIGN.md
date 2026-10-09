# Jules Integration Design

## Target Interface
A localhost HTTP REST API bound to `127.0.0.1` and a designated port (e.g., 8080).

## Caller Authentication
Requests must include a Bearer token in the `Authorization` header. This token is securely injected into the Jules runtime environment upon initiation and verified strictly by the API Gateway.

## Request/Response Schemas
- **Request Format**: JSON payload containing `operation` (read, write, delete), `target_path` (relative to JULES_ZONE), and optional `data` or `source_path`.
- **Response Format**: JSON containing `status` (success, failure), `error_code` (if applicable), and `data` (e.g., file contents or metadata).

## Error and Timeout Handling
- Client timeout configured to 30 seconds. Gateway applies a 25-second timeout to backend operations to gracefully return a `504 Gateway Timeout` rather than hanging.
- Exact error translation: `backend_quota_exceeded` maps to HTTP `429 Too Many Requests`.

## Blockers
We need explicit confirmation that the intended Google Jules runtime environment supports making authenticated HTTP requests to `localhost`. If it strictly uses an MCP (Model Context Protocol) or FUSE interface directly, this design is **BLOCKED**.
