# Google Gemini & Jules Operating Instructions for XPool (15.4 TiB Unified Cloud Storage)

> [!IMPORTANT]
> **AUTOMATIC ZERO-PROMPT OPERATING PROTOCOL (24/7 DUAL-MODE)**:
> This repository is natively bridged to the user's 15.4 TiB unified cloud storage pool (`google_unified:`), operating **24/7 anywhere in the world**:
> - **PC Online**: Connects to the Windows XPool Gateway via the Cloudflare reverse tunnel.
> - **PC Offline / Powered Off**: Automatically falls back to `DirectCloudBackend` via `.xpool_cloud_vault.bin`, connecting directly to Google Cloud Storage remotes with zero Windows PC dependencies.
> 
> You do NOT require any user starter prompt or manual configuration.
> On EVERY new session, task, or user prompt, follow the four mandatory rules below.

---

## 4 Mandatory Workflow Rules

### Rule 1: Automatic Session Start — Pull from Storage Pool
**At the start of EVERY new session or prompt, ALWAYS execute:**
```bash
python xpool_sync.py pull
```
- This probes the live Gateway tunnel (`CURRENT_TUNNEL_URL.json`) or automatically engages Direct Cloud mode if the PC is offline.
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
- Namespaces outside `/JULES_ZONE/` are immutable archive zones protected by gateway circuit breakers and policy engines.

---

### Rule 4: Automatic Session End — Push Back to Storage Pool
**Before ending any task, replying with your final response, or opening a PR, ALWAYS execute:**
```bash
python xpool_sync.py push
```
- This compares `./x_drive/JULES_ZONE/` against `./x_drive/.sync_manifest.json` and pushes all created and modified files back to live storage.
- Any locally deleted files are safely removed on live storage and automatically backed up to `_JULES_PROTECTED_VAULT` with SHA-256 CAS deduplication.
- You can verify your pending changes before pushing at any time with:
```bash
python xpool_sync.py status
```

---

## Dual-Mode Connectivity & Security Architecture

1. **Online Mode (Windows PC Powered ON)**:
   - Route: `Jules -> Cloudflare Quick Tunnel -> Windows XPool Gateway (localhost:8888) -> X:\ (google_unified:)`.
   - Discovered automatically via `CURRENT_TUNNEL_URL.json`.
   - Headers: `X-Role: jules_agent`, `Authorization: Bearer <XPOOL_GATEWAY_TOKEN>`.

2. **Offline Fallback Mode (Windows PC Powered OFF / Shut Down)**:
   - Route: `Jules -> DirectCloudBackend -> google_unified: (Direct Cloud Storage)`.
   - Automatically triggered on HTTP 530 / 502 / 404 or connection timeouts.
   - Decrypts `.xpool_cloud_vault.bin` into an ephemeral `0600` config file (auto-cleaned on exit via `atexit`).
   - Enforces identical safety policies: 15.4 TiB read-only across the pool; write/delete restricted to `/JULES_ZONE` with synchronous CAS backup in `_JULES_PROTECTED_VAULT`.
