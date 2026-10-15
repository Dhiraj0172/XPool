# XPool: Unified 15.4 TiB Cloud Storage Gateway & Jules Integration

XPool bridges cloud-hosted AI coding agents (such as Google Jules, Gemini, and Claude) directly to the user's live 15.4 TiB storage pool (`google_unified:`), operating **24/7 both when the Windows PC is powered ON and when it is completely powered OFF**.

---

## 24/7 Dual-Mode Architecture

| Feature | Primary Mode (PC Online) | Fallback Mode (PC Offline / Shut Down) |
| :--- | :--- | :--- |
| **Route** | Jules $\rightarrow$ Cloudflare Quick Tunnel $\rightarrow$ Windows Gateway $\rightarrow$ `X:\` | Jules $\rightarrow$ `DirectCloudBackend` $\rightarrow$ `google_unified:` direct |
| **Endpoint** | Public URL in `CURRENT_TUNNEL_URL.json` | Ephemeral decrypted vault (`.xpool_cloud_vault.bin`) |
| **Availability** | When host PC is active | 24/7/365 uninterrupted anywhere worldwide |
| **Read Scope** | Full read/list across all 15.4 TiB directories | Full read/list across all 15.4 TiB directories |
| **Write Scope** | Restricted to `/JULES_ZONE` | Restricted to `/JULES_ZONE` |
| **CAS Protection** | Synchronous pre-delete/overwrite backup | Synchronous pre-delete/overwrite backup |

---

## Autonomous Agent Zero-Prompt Protocol

Autonomous agents reading this repository follow a zero-prompt execution model:
1. **Start of Session**: Run `python xpool_sync.py pull` to fetch the root pool index (`./x_drive/_XPOOL_INDEX.json`) and synchronize `./x_drive/JULES_ZONE/`.
2. **Accessing Pool Assets**: Inspect `./x_drive/_XPOOL_INDEX.json` and run `python xpool_sync.py fetch "<remote_path>"` to retrieve files from `/AI-MEMORY`, `/AI-STORAGE`, `/Archives`, `/PC-FULL-BACKUP`, or `/SHARED_READONLY`.
3. **Workspace**: Perform all data creation and modifications inside `./x_drive/JULES_ZONE/`.
4. **End of Session**: Run `python xpool_sync.py push` to upload all changes back to storage with automatic pre-delete CAS protection.

See [AGENTS.md](AGENTS.md) for full agent operating rules.

---

## Tooling & Architecture

- **`xpool_sync.py`**: Git-style synchronization CLI (`pull`, `fetch`, `push`, `status`) with automatic dual-mode fallback.
- **`xpool_client.py`**: Python SDK supporting both Gateway REST protocol and Direct Cloud `rclone` driver with zero cloud dependencies.
- **`xpool_vault.py`**: Multi-layer cryptographic packer and unpacker for `.xpool_cloud_vault.bin`.
- **`.xpool_cloud_vault.bin`**: Encrypted cloud config bundle (PBKDF2-HMAC-SHA256 + zlib compression) containing zero plaintext tokens or secrets.
- **`CURRENT_TUNNEL_URL.json`**: Auto-published public endpoint metadata maintained by the host reverse tunnel publisher.
