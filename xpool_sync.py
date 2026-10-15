r"""XPool Storage Sync Utility (Git-style Auto-Pull / Auto-Fetch / Auto-Push).
Bridges Google Jules workspace directly to the user's 15.4 TiB Windows X:\ drive (google_unified:).
Supports:
  - pull:  Indexes the root pool and syncs /JULES_ZONE into ./x_drive/JULES_ZONE/
  - fetch: Pulls read-only files or folders from anywhere in the 15.4 TiB pool
  - push:  Synchronizes local edits/deletions in ./x_drive/JULES_ZONE back to live X:\JULES_ZONE
  - status: Shows pending changes compared to the baseline sync manifest
"""

import os
import sys
import json
import base64
import hashlib
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Set

try:
    from xpool_client import XPoolClient, sanitize_text
except ImportError:
    # Handle direct import if running within module path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from xpool_client import XPoolClient, sanitize_text

# Workspace directory definitions
DEFAULT_SYNC_ROOT = Path("x_drive")
INDEX_FILENAME = "_XPOOL_INDEX.json"
MANIFEST_FILENAME = ".sync_manifest.json"

# File patterns to exclude from push/pull tracking
IGNORED_NAMES = {
    MANIFEST_FILENAME,
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini"
}
IGNORED_EXTENSIONS = {
    ".tmp",
    ".swp",
    ".swo",
    ".pyc",
    ".pyo"
}


def compute_file_sha256(file_path: Path) -> Tuple[str, int]:
    """Calculates SHA-256 digest and byte size of a file."""
    hasher = hashlib.sha256()
    total_bytes = 0
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(128 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
            total_bytes += len(chunk)
    return hasher.hexdigest(), total_bytes


def is_ignored_file(path: Path) -> bool:
    """Checks whether a file should be excluded from sync tracking."""
    if path.name in IGNORED_NAMES:
        return True
    if path.suffix.lower() in IGNORED_EXTENSIONS:
        return True
    if "__pycache__" in path.parts:
        return True
    return False


def load_manifest(manifest_path: Path) -> Dict[str, Any]:
    """Loads sync manifest with BOM-safe parsing."""
    if not manifest_path.is_file():
        return {}
    try:
        with open(manifest_path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
            return data.get("files", {})
    except Exception as e:
        print(f"[xpool_sync] Warning: Could not read manifest {manifest_path}: {e}", file=sys.stderr)
        return {}


def save_manifest(manifest_path: Path, files_map: Dict[str, Any], extra_meta: Optional[Dict[str, Any]] = None):
    """Saves sync manifest in clean UTF-8."""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": "1.0.0",
        "description": "Baseline sync manifest for ./x_drive/JULES_ZONE",
        "files": files_map
    }
    if extra_meta:
        payload.update(extra_meta)

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


class XPoolSyncManager:
    r"""Manages bidirectional file synchronization between local workspace and live X:\ pool."""
    def __init__(self, workspace_root: Optional[Path] = None, client: Optional[XPoolClient] = None):
        self.workspace_root = (workspace_root or Path.cwd()).resolve()
        self.x_drive_dir = self.workspace_root / DEFAULT_SYNC_ROOT
        self.jules_zone_dir = self.x_drive_dir / "JULES_ZONE"
        self.manifest_path = self.x_drive_dir / MANIFEST_FILENAME
        self.index_path = self.x_drive_dir / INDEX_FILENAME
        self.client = client or XPoolClient()

    def list_recursive(self, remote_dir: str) -> List[Dict[str, Any]]:
        """Recursively lists all files under a remote directory using the gateway list API."""
        norm_dir = "/" + remote_dir.strip("/\\")
        files = []
        dirs_queue = [norm_dir]

        while dirs_queue:
            curr_dir = dirs_queue.pop(0)
            try:
                res = self.client.list(curr_dir)
            except Exception as e:
                print(f"[xpool_sync] Warning: Failed listing '{curr_dir}': {e}", file=sys.stderr)
                continue

            for item in res.get("items", []):
                item_path = item.get("path")
                if item.get("is_dir"):
                    dirs_queue.append(item_path)
                else:
                    files.append(item)

        return files

    def pull(self) -> Dict[str, Any]:
        """Pulls root index and synchronizes /JULES_ZONE into ./x_drive/JULES_ZONE."""
        self.x_drive_dir.mkdir(parents=True, exist_ok=True)
        self.jules_zone_dir.mkdir(parents=True, exist_ok=True)

        print(f"[xpool_sync] Connecting to XPool Gateway: {self.client.base_url}")

        # 1. Index Root Directory (15.4 TiB Pool Map)
        try:
            root_res = self.client.list("/")
            with open(self.index_path, "w", encoding="utf-8") as f:
                json.dump({
                    "synced_at": root_res.get("synced_at") or "",
                    "gateway_url": self.client.base_url,
                    "pool_root": "/",
                    "items": root_res.get("items", [])
                }, f, indent=2)
            print(f"[xpool_sync] Updated live pool index: {self.index_path.relative_to(self.workspace_root)}")
        except Exception as e:
            print(f"[xpool_sync] Warning: Could not index root directory: {e}", file=sys.stderr)

        # 2. Recursively Sync /JULES_ZONE
        remote_files = self.list_recursive("/JULES_ZONE")
        manifest = load_manifest(self.manifest_path)
        updated_manifest = dict(manifest)
        pulled_count = 0
        total_bytes = 0

        print(f"[xpool_sync] Syncing /JULES_ZONE ({len(remote_files)} remote entries found)...")

        for rfile in remote_files:
            rpath = rfile["path"]
            # Rel path inside JULES_ZONE
            rel_path = rpath[len("/JULES_ZONE/"):].lstrip("/\\")
            if not rel_path:
                continue

            local_target = self.jules_zone_dir / rel_path
            expected_size = rfile.get("size_bytes", 0)

            needs_download = True
            if local_target.is_file():
                local_sha, local_size = compute_file_sha256(local_target)
                if rel_path in manifest and manifest[rel_path].get("sha256") == local_sha:
                    # File matches baseline manifest
                    needs_download = False
                    updated_manifest[rel_path] = {
                        "sha256": local_sha,
                        "size_bytes": local_size,
                        "remote_path": rpath
                    }

            if needs_download:
                try:
                    read_res = self.client.read(rpath)
                    content_raw = read_res.get("content", "")
                    is_b64 = read_res.get("is_base64", False)

                    if is_b64:
                        file_bytes = base64.b64decode(content_raw)
                    else:
                        file_bytes = content_raw.encode("utf-8")

                    local_target.parent.mkdir(parents=True, exist_ok=True)
                    with open(local_target, "wb") as f:
                        f.write(file_bytes)

                    file_sha = hashlib.sha256(file_bytes).hexdigest()
                    updated_manifest[rel_path] = {
                        "sha256": file_sha,
                        "size_bytes": len(file_bytes),
                        "remote_path": rpath
                    }
                    pulled_count += 1
                    total_bytes += len(file_bytes)
                    print(f"  + pulled: JULES_ZONE/{rel_path} ({len(file_bytes)} bytes)")
                except Exception as e:
                    print(f"[xpool_sync] Error pulling '{rpath}': {e}", file=sys.stderr)

        save_manifest(self.manifest_path, updated_manifest)
        print(f"[xpool_sync] Pull complete: {pulled_count} files synced ({total_bytes} bytes).")
        return {"pulled_count": pulled_count, "total_bytes": total_bytes}

    def fetch(self, remote_path: str) -> Dict[str, Any]:
        """Fetches any read-only file or folder from anywhere in the 15.4 TiB pool into ./x_drive/."""
        clean_path = "/" + remote_path.strip("/\\")
        print(f"[xpool_sync] Fetching '{clean_path}' from XPool Gateway...")

        # Check if remote_path is a directory
        is_dir = False
        try:
            list_res = self.client.list(clean_path)
            items = list_res.get("items", [])
            # If list returns items and does not equal a single file with matching path
            if len(items) > 1 or (len(items) == 1 and items[0].get("is_dir")):
                is_dir = True
            elif len(items) == 1 and items[0].get("path") == clean_path and not items[0].get("is_dir"):
                is_dir = False
            else:
                is_dir = True
        except Exception:
            # Fall back to file read
            is_dir = False

        fetched_files = []
        if is_dir:
            remote_files = self.list_recursive(clean_path)
            for rfile in remote_files:
                rpath = rfile["path"]
                rel_from_root = rpath.lstrip("/\\")
                local_dest = self.x_drive_dir / rel_from_root

                try:
                    read_res = self.client.read(rpath)
                    content_raw = read_res.get("content", "")
                    file_bytes = base64.b64decode(content_raw) if read_res.get("is_base64") else content_raw.encode("utf-8")
                    local_dest.parent.mkdir(parents=True, exist_ok=True)
                    with open(local_dest, "wb") as f:
                        f.write(file_bytes)
                    fetched_files.append({"path": str(local_dest), "size": len(file_bytes)})
                    print(f"  + fetched: {rel_from_root} ({len(file_bytes)} bytes)")
                except Exception as e:
                    print(f"[xpool_sync] Error fetching '{rpath}': {e}", file=sys.stderr)
        else:
            rel_from_root = clean_path.lstrip("/\\")
            local_dest = self.x_drive_dir / rel_from_root
            try:
                read_res = self.client.read(clean_path)
                content_raw = read_res.get("content", "")
                file_bytes = base64.b64decode(content_raw) if read_res.get("is_base64") else content_raw.encode("utf-8")
                local_dest.parent.mkdir(parents=True, exist_ok=True)
                with open(local_dest, "wb") as f:
                    f.write(file_bytes)
                fetched_files.append({"path": str(local_dest), "size": len(file_bytes)})
                print(f"[xpool_sync] Fetched file to {local_dest.relative_to(self.workspace_root)} ({len(file_bytes)} bytes)")
            except Exception as e:
                raise RuntimeError(f"Failed to fetch '{clean_path}': {e}")

        return {"status": "ok", "remote_path": clean_path, "fetched_files": fetched_files}

    def status(self) -> Dict[str, Any]:
        """Compares ./x_drive/JULES_ZONE against baseline manifest and returns diff."""
        if not self.jules_zone_dir.is_dir():
            return {"created": [], "modified": [], "deleted": []}

        manifest = load_manifest(self.manifest_path)
        created = []
        modified = []
        current_local_files: Set[str] = set()

        # Scan local directory
        for root, dirs, files in os.walk(self.jules_zone_dir):
            for fname in files:
                fpath = Path(root) / fname
                if is_ignored_file(fpath):
                    continue

                rel_path = str(fpath.relative_to(self.jules_zone_dir)).replace("\\", "/")
                current_local_files.add(rel_path)

                local_sha, local_size = compute_file_sha256(fpath)

                if rel_path not in manifest:
                    created.append(rel_path)
                elif manifest[rel_path].get("sha256") != local_sha:
                    modified.append(rel_path)

        deleted = [p for p in manifest if p not in current_local_files]

        return {
            "created": created,
            "modified": modified,
            "deleted": deleted
        }

    def push(self) -> Dict[str, Any]:
        r"""Pushes created/modified files in ./x_drive/JULES_ZONE and removes deleted files on live X:\."""
        if not self.jules_zone_dir.is_dir():
            print("[xpool_sync] No local JULES_ZONE directory found. Nothing to push.")
            return {"created": 0, "modified": 0, "deleted": 0}

        diff = self.status()
        created = diff["created"]
        modified = diff["modified"]
        deleted = diff["deleted"]

        total_changes = len(created) + len(modified) + len(deleted)
        if total_changes == 0:
            print("[xpool_sync] Everything up to date with live X:\\JULES_ZONE. No changes to push.")
            return {"created": 0, "modified": 0, "deleted": 0}

        print(f"[xpool_sync] Pushing {total_changes} changes to live X:\\JULES_ZONE via {self.client.base_url}...")

        manifest = load_manifest(self.manifest_path)
        updated_manifest = dict(manifest)

        # 1. Upload Created and Modified Files
        for rel_path in (created + modified):
            local_path = self.jules_zone_dir / rel_path
            remote_path = f"/JULES_ZONE/{rel_path}"

            with open(local_path, "rb") as f:
                data = f.read()

            try:
                # Attempt UTF-8 decode; fallback to base64 for binary files
                content_str = data.decode("utf-8")
                is_b64 = False
            except UnicodeDecodeError:
                content_str = base64.b64encode(data).decode("ascii")
                is_b64 = True

            action_label = "create" if rel_path in created else "update"
            try:
                res = self.client.write(path=remote_path, content=content_str, is_base64=is_b64)
                file_sha, file_size = compute_file_sha256(local_path)
                updated_manifest[rel_path] = {
                    "sha256": file_sha,
                    "size_bytes": file_size,
                    "remote_path": remote_path
                }
                symbol = "+" if action_label == "create" else "*"
                print(f"  {symbol} {action_label}: JULES_ZONE/{rel_path} ({file_size} bytes)")
            except Exception as e:
                print(f"[xpool_sync] Failed to push '{remote_path}': {e}", file=sys.stderr)

        # 2. Delete Removed Files (with synchronous pre-delete backup in CAS vault)
        for rel_path in deleted:
            remote_path = f"/JULES_ZONE/{rel_path}"
            try:
                res = self.client.delete(path=remote_path)
                if rel_path in updated_manifest:
                    del updated_manifest[rel_path]
                print(f"  - delete: JULES_ZONE/{rel_path} (protected in vault: {res.get('recovery_version_id', 'yes')})")
            except Exception as e:
                print(f"[xpool_sync] Failed to delete remote '{remote_path}': {e}", file=sys.stderr)

        save_manifest(self.manifest_path, updated_manifest)
        print(f"[xpool_sync] Push complete: +{len(created)} created, *{len(modified)} modified, -{len(deleted)} deleted.")
        return {
            "created": len(created),
            "modified": len(modified),
            "deleted": len(deleted)
        }


def main():
    parser = argparse.ArgumentParser(
        description="XPool Storage Sync Utility: Git-style sync tool for live Windows X:\\ drive"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # pull
    subparsers.add_parser("pull", help="Index root pool and sync /JULES_ZONE into ./x_drive/JULES_ZONE")

    # fetch
    p_fetch = subparsers.add_parser("fetch", help="Fetch any file or folder from the 15.4 TiB pool into ./x_drive")
    p_fetch.add_argument("remote_path", help="Canonical remote path (e.g. /AI-MEMORY/notes.txt or /SHARED_READONLY)")

    # push
    subparsers.add_parser("push", help="Push all created, modified, and deleted files in ./x_drive/JULES_ZONE back to live X:\\")

    # status
    subparsers.add_parser("status", help="Show working tree status comparing ./x_drive/JULES_ZONE to baseline manifest")

    args = parser.parse_args()
    manager = XPoolSyncManager()

    try:
        if args.command == "pull":
            manager.pull()
        elif args.command == "fetch":
            manager.fetch(args.remote_path)
        elif args.command == "push":
            manager.push()
        elif args.command == "status":
            diff = manager.status()
            print("=== XPool Working Tree Status (./x_drive/JULES_ZONE) ===")
            if not diff["created"] and not diff["modified"] and not diff["deleted"]:
                print("Working tree clean. No changes since last pull/push.")
            else:
                for c in diff["created"]:
                    print(f"  + untracked/new: {c}")
                for m in diff["modified"]:
                    print(f"  * modified:      {m}")
                for d in diff["deleted"]:
                    print(f"  - deleted:       {d}")
    except Exception as e:
        print(f"Error: {sanitize_text(str(e))}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
