# XPool: Unified 15.4 TiB Cloud Storage Gateway & Jules Integration

XPool bridges cloud-hosted AI coding agents (such as Google Jules, Gemini, and Claude) directly to the user's live 15.4 TiB Windows storage pool (`google_unified:`, mounted on `X:\`).

---

## Autonomous Agent Zero-Prompt Protocol

Autonomous agents reading this repository follow a zero-prompt execution model:
1. **Start of Session**: Run `python xpool_sync.py pull` to fetch the root pool index (`./x_drive/_XPOOL_INDEX.json`) and synchronize `./x_drive/JULES_ZONE/`.
2. **Accessing Pool Assets**: Inspect `./x_drive/_XPOOL_INDEX.json` and run `python xpool_sync.py fetch "<remote_path>"` to retrieve files from `/AI-MEMORY`, `/AI-STORAGE`, `/Archives`, `/PC-FULL-BACKUP`, or `/SHARED_READONLY`.
3. **Workspace**: Perform all data creation and modifications inside `./x_drive/JULES_ZONE/`.
4. **End of Session**: Run `python xpool_sync.py push` to upload all changes back to `X:\JULES_ZONE` with automatic pre-delete CAS protection.

See [AGENTS.md](AGENTS.md) for full agent operating rules.

---

## Tooling & Architecture

- **`xpool_sync.py`**: Git-style synchronization CLI (`pull`, `fetch`, `push`, `status`).
- **`xpool_client.py`**: Authenticated Python SDK connecting over Cloudflare Quick Tunnels with automatic URL discovery from `CURRENT_TUNNEL_URL.json` and NXDOMAIN failover.
- **`CURRENT_TUNNEL_URL.json`**: Auto-published public endpoint metadata maintained by the host reverse tunnel publisher.
- **Security Invariant**: Strictly zero cloud credentials stored or exposed in this repository. All authentication uses scoped gateway tokens with fail-closed CAS vault pre-delete guarantees.
