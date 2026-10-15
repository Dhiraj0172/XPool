# Google Jules & Autonomous Agent Operating Instructions for XPool (15.4 TiB Storage)

> [!IMPORTANT]
> **AUTOMATIC ZERO-PROMPT OPERATING PROTOCOL (24/7 DUAL-MODE)**:
> This repository is natively bridged to the user's 15.4 TiB unified cloud storage pool (`google_unified:`), operating **24/7 anywhere in the world**:
> - **PC Online**: Connects to the Windows XPool Gateway via the Cloudflare reverse tunnel.
> - **PC Offline / Powered Off**: Automatically falls back to `DirectCloudBackend` via `.xpool_cloud_vault.bin`, connecting directly to Google Cloud Storage remotes with zero Windows PC dependencies.
> 
> You do NOT require any user starter prompt or manual configuration.
> On EVERY new session, task, or user prompt, follow the five mandatory rules below.

---

## 5 Mandatory Workflow Rules

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

### Rule 5: Pure `X:\` Drive Tasks vs. Repo Code Tasks
When the user's request is to read, create, edit, or sync files on the `X:\` drive (`./x_drive/JULES_ZONE/`) rather than modifying this repository's Python source code:
1. Do NOT download files into the repository root (always use `./x_drive/JULES_ZONE/` or `/tmp/`).
2. Do NOT run `uv run pytest` (which pollutes `.egg-info`) unless you edited repo `.py` files.
3. Once `python xpool_sync.py push` succeeds, DO NOT invoke the `submit` (GitHub PR) tool if no repository source files were changed—simply clean up `./x_drive/` and reply directly to the user confirming the files are live on `X:\JULES_ZONE\`.

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

---

## Section 4: Universal Lifetime Brain (v26) Two-Way Sync Protocol

This repository is connected to the **5-Node Unified AI Brain (v26)** spanning:
- **4x Gemini Accounts** (Continuous Backup, Knowledge, Strategy, Deep Review)
- **Google Jules** (Autonomous Cloud VM Execution & Heavy Benchmarking)
- **Antigravity & Hermes** (Workstation Pair-Programming & System Automation)

### 1. Two-Way Sync Ledger Files (on `/JULES_ZONE/`)
- `/JULES_ZONE/BRAIN_SYNC_LEDGER.json`: Machine-readable state containing storage telemetry, active pipeline metrics, handoff sessions, and agent task queues.
- `/JULES_ZONE/BRAIN_SYNC_LEDGER.md`: Human & model-readable ledger logging latest operator prompts, completed tasks, stress test summaries, and immediate next actions.
- `/JULES_ZONE/X_DRIVE_LIVE_INDEX.md`: Live broadcast index containing the authoritative structure of the 15.4 TiB storage pool, mirrored automatically every 120s from the Windows PC workstation.

### 2. Session Start Protocol (Reading Brain Context)
At the beginning of your task or session, read the brain state to learn what tasks Gemini, Antigravity, or the Operator have completed and what next action is assigned to you:
```bash
# Read current brain state via CLI helper:
python3 scripts/jules_brain_sync.py status

# Or inspect the markdown ledger directly if pulled locally:
cat x_drive/JULES_ZONE/BRAIN_SYNC_LEDGER.md
```

### 3. Session End Protocol (Logging Task Handoff)
When you complete your task, run tests, or produce deliverables in `./x_drive/JULES_ZONE/`:
1. Push your deliverables back to storage:
   ```bash
   python xpool_sync.py push
   ```
2. Log your completed work and hand off the next action to Gemini/Antigravity:
   ```bash
   python3 scripts/jules_brain_sync.py update \
     --prompt "Operator's instruction or task brief" \
     --done "Summary of completed changes and verified test results" \
     --next "Actionable next steps for Gemini or Operator"
   ```
This updates `/JULES_ZONE/BRAIN_SYNC_LEDGER.json` and `/JULES_ZONE/BRAIN_SYNC_LEDGER.md` across the storage pool and local workstation manifests immediately.

