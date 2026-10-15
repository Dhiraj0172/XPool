#!/usr/bin/env python3
"""
Jules <-> Gemini Universal Brain Sync CLI (v26)
==================================================
Allows Google Jules (inside its ephemeral Ubuntu VM) or the local PC to read and update
/JULES_ZONE/BRAIN_SYNC_LEDGER.json and /JULES_ZONE/BRAIN_SYNC_LEDGER.md via the xpool CLI
bridge (PC-Online mode) or Direct Cloud fallback (PC-Offline mode).

Usage inside Jules VM / local workstation:
  1. Read current Brain state on session start:
       python3 scripts/jules_brain_sync.py status
  2. Log completed task & next steps back to Universal Brain:
       python3 scripts/jules_brain_sync.py update \
         --prompt "Implemented feature X" \
         --done "Updated server.py and passed all unit tests" \
         --next "Ready for Gemini architectural review"
"""

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
LOCAL_CACHE_DIR = Path("/tmp/jules_brain_sync") if os.name != "nt" else Path(os.environ.get("TEMP", r"C:\Temp")) / "jules_brain_sync"

# Try locating and importing XPoolClient
for candidate_dir in [
    Path(__file__).resolve().parent.parent,
    Path(__file__).resolve().parent.parent / "client",
    Path(__file__).resolve().parent.parent / "sdk",
]:
    if (candidate_dir / "xpool_client.py").is_file():
        sys.path.insert(0, str(candidate_dir))
        break

try:
    from xpool_client import XPoolClient
except Exception:
    XPoolClient = None


def run_xpool(args_list):
    xpool_bin = os.environ.get("XPOOL_BIN", "xpool")
    if shutil.which(xpool_bin):
        cmd = [xpool_bin] + args_list
        return subprocess.run(cmd, capture_output=True, text=True)
    return subprocess.CompletedProcess(args=[], returncode=127, stdout="", stderr="xpool binary not found in PATH")


def pull_ledger() -> dict:
    LOCAL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    local_json = LOCAL_CACHE_DIR / "BRAIN_SYNC_LEDGER.json"

    # 1. Local disk / X: mount check
    local_x_path = Path(r"X:\JULES_ZONE\BRAIN_SYNC_LEDGER.json")
    if local_x_path.exists():
        try:
            return json.loads(local_x_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    manifest_path = Path(r"D:\PC-Continuous-Backup\manifests\BRAIN_SYNC_LEDGER.json")
    if manifest_path.exists():
        try:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # 2. xpool CLI check (PC-Online mode)
    res = run_xpool(["get", "/JULES_ZONE/BRAIN_SYNC_LEDGER.json", str(local_json)])
    if res.returncode == 0 and local_json.exists():
        try:
            return json.loads(local_json.read_text(encoding="utf-8"))
        except Exception:
            pass

    # 3. XPoolClient SDK check (Dual-Mode / Direct Cloud fallback)
    if XPoolClient is not None:
        try:
            client = XPoolClient()
            read_fn = getattr(client, "read_file", client.read)
            r = read_fn("/JULES_ZONE/BRAIN_SYNC_LEDGER.json")
            content = r.get("content", "{}")
            if r.get("is_base64"):
                import base64
                content = base64.b64decode(content).decode("utf-8")
            data = json.loads(content)
            local_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return data
        except Exception:
            pass

    # 4. Direct rclone fallback
    if shutil.which("rclone"):
        try:
            proc = subprocess.run(["rclone", "cat", "google_unified:JULES_ZONE/BRAIN_SYNC_LEDGER.json", "--no-console"], capture_output=True, text=True)
            if proc.returncode == 0 and proc.stdout:
                data = json.loads(proc.stdout)
                local_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
                return data
        except Exception:
            pass

    return {
        "schema_version": "v27_zero_touch_brain_mesh",
        "updated_at_ist": datetime.datetime.now(IST).isoformat(),
        "latest_handoff": {},
        "history": [],
    }


def push_ledger(data: dict, md_text: str):
    LOCAL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    local_json = LOCAL_CACHE_DIR / "BRAIN_SYNC_LEDGER.json"
    local_md = LOCAL_CACHE_DIR / "BRAIN_SYNC_LEDGER.md"

    local_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
    local_md.write_text(md_text, encoding="utf-8")

    # Local X: mount write
    local_x_dir = Path(r"X:\JULES_ZONE")
    if local_x_dir.exists():
        try:
            (local_x_dir / "BRAIN_SYNC_LEDGER.json").write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
            (local_x_dir / "BRAIN_SYNC_LEDGER.md").write_text(md_text, encoding="utf-8")
            print("[PASS] Synced BRAIN_SYNC_LEDGER.json & .md directly to X:\\JULES_ZONE")
        except Exception as e:
            print(f"[WARN] Local X: write: {e}")

    # Local manifest write
    manifest_dir = Path(r"D:\PC-Continuous-Backup\manifests")
    if manifest_dir.exists():
        try:
            (manifest_dir / "BRAIN_SYNC_LEDGER.json").write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
            (manifest_dir / "BRAIN_SYNC_LEDGER.md").write_text(md_text, encoding="utf-8")
        except Exception:
            pass

    # Try xpool CLI (PC-Online mode)
    pushed_online = False
    r1 = run_xpool(["put", str(local_json), "/JULES_ZONE/BRAIN_SYNC_LEDGER.json"])
    r2 = run_xpool(["put", str(local_md), "/JULES_ZONE/BRAIN_SYNC_LEDGER.md"])
    if r1.returncode == 0 and r2.returncode == 0:
        pushed_online = True
        print("[PASS] Pushed updated Brain Ledger to /JULES_ZONE/ via xpool gateway.")

    # Try XPoolClient SDK (Dual-Mode / Direct Cloud fallback)
    if not pushed_online and XPoolClient is not None:
        try:
            client = XPoolClient()
            client.write("/JULES_ZONE/BRAIN_SYNC_LEDGER.json", json.dumps(data, indent=2))
            client.write("/JULES_ZONE/BRAIN_SYNC_LEDGER.md", md_text)
            print("[PASS] Pushed updated Brain Ledger to /JULES_ZONE/ via XPoolClient fallback.")
            pushed_online = True
        except Exception as err:
            print(f"[NOTE] XPoolClient write fallback: {err}")

    # Direct rclone fallback
    if not pushed_online and shutil.which("rclone"):
        try:
            subprocess.run(["rclone", "copyto", str(local_json), "google_unified:JULES_ZONE/BRAIN_SYNC_LEDGER.json", "--no-console"], check=True)
            subprocess.run(["rclone", "copyto", str(local_md), "google_unified:JULES_ZONE/BRAIN_SYNC_LEDGER.md", "--no-console"], check=True)
            print("[PASS] Pushed updated Brain Ledger to google_unified:JULES_ZONE/ via rclone direct.")
        except Exception as rclone_err:
            print(f"[WARN] rclone fallback error: {rclone_err}")


def main():
    parser = argparse.ArgumentParser(description="Jules <-> Gemini Universal Brain Sync CLI (v27)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Read current Universal Brain Ledger state")

    up = sub.add_parser("update", help="Record prompt, completed work, and next steps to Brain Ledger")
    up.add_argument("--agent", default="Google-Jules (@google/jules)", help="Agent identity")
    up.add_argument("--prompt", required=True, help="Prompt or task objective executed")
    up.add_argument("--done", required=True, help="Summary of completed work and files modified")
    up.add_argument("--next", default="Ready for next operator/Gemini review", help="Next action")

    args = parser.parse_args()
    data = pull_ledger()

    if args.cmd == "status":
        print(json.dumps(data, indent=2))
        return

    now_str = datetime.datetime.now(IST).strftime("%d %b %Y, %I:%M:%S %p IST")
    prev = data.get("latest_handoff", {})
    if prev:
        hist = data.setdefault("history", [])
        hist.insert(0, prev)
        data["history"] = hist[:25]

    completed_list = [x.strip() for x in args.done.split(";") if x.strip()]
    data["updated_at_ist"] = datetime.datetime.now(IST).isoformat()
    data["latest_handoff"] = {
        "session_id": f"SESSION-{datetime.datetime.now(IST).strftime('%Y%m%d-%H%M%S')}-IST",
        "source_agent": args.agent,
        "target_agents": ["Gemini-1", "Gemini-2", "Gemini-3", "Gemini-4", "Google-Jules", "Antigravity"],
        "last_user_prompt": args.prompt,
        "completed_tasks": completed_list,
        "next_actions": {
            "jules": args.next,
            "gemini": f"Review {args.agent} update from {now_str}: {args.done}",
            "pc_workstation": "Continue active continuous sync and index broadcast",
        },
    }

    md_lines = [
        f"# 🧠 UNIVERSAL LIFETIME BRAIN — JULES + 4-GEMINI SYNC LEDGER (`v27`)",
        f"> **Updated at:** `{now_str}` | **Last Active Agent:** `{args.agent}`",
        "",
        "## LATEST HANDOFF SUMMARY",
        f"- **Prompt / Objective:** {args.prompt}",
        "- **Completed Tasks:**",
    ]
    for c in completed_list:
        md_lines.append(f"  - [x] {c}")
    md_lines.append(f"- **Next Action:** {args.next}")
    md_lines.append("")

    push_ledger(data, "\n".join(md_lines))


if __name__ == "__main__":
    main()
