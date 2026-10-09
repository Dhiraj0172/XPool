# Logging, Secrets, and Operations

## Secret Management
Credentials (API keys, rclone configurations, Windows passwords) are never stored in source code, `.md` files, command-line arguments, or JSON logs.
- They are securely mounted via environment variables (in memory) or stored in protected, OS-level secure vaults (e.g., Windows Credential Manager) and injected at runtime.

## Structured Audit Logging
- We use a structured JSON logger.
- **Fields included:** timestamp, operation_type, canonical_path, caller_identity, success/failure, error_code, latency_ms.
- **Redaction:** A custom filter runs over every log object, replacing known secret keys or values matching authorization token formats with `[REDACTED]`.

## Health Monitoring & Shutdown
- A `/health` endpoint exposes gateway readiness, rclone RC connectivity, and backup store availability.
- On catastrophic failure (e.g., unhandled exception escaping the request boundary), the gateway logs a `FATAL` event and gracefully shuts down to fail closed, rather than operating in an inconsistent state.
