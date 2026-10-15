# Claude & Agent Operating Instructions for XPool (15.4 TiB Unified Cloud Storage)

> [!IMPORTANT]
> **AUTOMATIC ZERO-PROMPT OPERATING PROTOCOL**:
> This repository is natively bridged to the user's live 15.4 TiB Windows storage pool (`google_unified:`, mounted on `X:\`).
> You do NOT require any user starter prompt or manual tunnel configuration.
> On EVERY new session, task, or user prompt, follow the four mandatory rules below.

---

## 4 Mandatory Workflow Rules

### Rule 1: Automatic Session Start — Pull from `X:\`
**At the start of EVERY new session or prompt, ALWAYS execute:**
```bash
python xpool_sync.py pull
```
- This automatically connects to the live Windows XPool Gateway via `CURRENT_TUNNEL_URL.json`.
- It refreshes `./x_drive/_XPOOL_INDEX.json`, giving you the complete directory map of the 15.4 TiB storage pool.
- It recursively pulls all active files from `/JULES_ZONE` into your local workspace directory `./x_drive/JULES_ZONE/` and establishes the baseline `./x_drive/.sync_manifest.json`.
- **Your primary operating workspace for all data is `./x_drive/JULES_ZONE/`**.

---

### Rule 2: Reading Any File on the 15.4 TiB Storage Pool
Whenever you need to inspect or read files outside `/JULES_ZONE` (e.g., from `/AI-MEMORY`, `/AI-STORAGE`, `/Archives`, `/PC-FULL-BACKUP`, or `/SHARED_READONLY`):
1. Check `./x_drive/_XPOOL_INDEX.json` to find the exact remote path.
2. Fetch the file or directory locally by running:
```bash
# Fetch a specific file:
python xpool_sync.py fetch "/AI-MEMORY/notes.txt"

# Fetch an entire folder:
python xpool_sync.py fetch "/SHARED_READONLY"
```
The content will be downloaded directly into `./x_drive/<remote_path>` for your local inspection and analysis.

---

### Rule 3: Writing & Editing Rules
- **All created or edited data files must be placed inside `./x_drive/JULES_ZONE/`** (and/or code files inside the repository structure as requested).
- You have full read/write/delete authority inside `./x_drive/JULES_ZONE/`.
- Namespaces outside `/JULES_ZONE/` are immutable archive zones protected by gateway circuit breakers.

---

### Rule 4: Automatic Session End — Push Back to `X:\`
**Before ending any task, replying with your final response, or opening a PR, ALWAYS execute:**
```bash
python xpool_sync.py push
```
- This compares `./x_drive/JULES_ZONE/` against `./x_drive/.sync_manifest.json` and pushes all created and modified files back to the user's live `X:\JULES_ZONE\` via the Gateway `POST /api/v1/write`.
- Any locally deleted files are safely removed on live storage and automatically backed up to `_JULES_PROTECTED_VAULT` with SHA-256 CAS deduplication.
- You can verify your pending changes before pushing at any time with:
```bash
python xpool_sync.py status
```

---

## Gateway Authentication & Connectivity

- **Endpoint Resolution**: Handled automatically by `xpool_client.py` and `xpool_sync.py` by reading `CURRENT_TUNNEL_URL.json` at the repo root.
- **Failover**: If the Cloudflare tunnel rotates, `xpool_client.py` auto-detects `NXDOMAIN` and reloads the fresh URL from `CURRENT_TUNNEL_URL.json`.
- **Headers & Authorization**:
  - `X-Role: jules_agent`
  - `Authorization: Bearer <XPOOL_GATEWAY_TOKEN>` (Resolved from environment or defaults to the gateway sandbox token `xpool-jules-sec-token-9b2f6a1e8c4d`).
