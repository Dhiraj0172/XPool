r"""XPool Storage Sync Utility (Git-style Auto-Pull / Auto-Fetch / Auto-Push).
Bridges Google Jules workspace directly to the 15.4 TiB cloud storage pool (google_unified:).
Supports Dual-Mode Operation:
  - Online Mode: Windows XPool Gateway via Cloudflare tunnel.
  - Offline Mode: Direct Cloud connection (google_unified:) via ephemeral decrypted vault.

Commands:
  - pull:   Indexes the root pool and syncs /JULES_ZONE into ./x_drive/JULES_ZONE/
  - fetch:  Pulls read-only files or folders from anywhere in the 15.4 TiB pool
  - push:   Synchronizes local edits/deletions in ./x_drive/JULES_ZONE back to live storage
  - status: Shows pending changes compared to the baseline sync manifest
"""

import os
import sys
import json
import base64
import hashlib
import argparse
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Set

try:
    from xpool_client import XPoolClient, sanitize_text
except ImportError:
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
    r"""Manages bidirectional file synchronization between local workspace and live storage pool."""
    def __init__(
        self,
        workspace_root: Optional[Path] = None,
        client: Optional[XPoolClient] = None,
        mode: str = "auto"
    ):
        self.workspace_root = (workspace_root or Path.cwd()).resolve()
        self.x_drive_dir = self.workspace_root / DEFAULT_SYNC_ROOT
        self.jules_zone_dir = self.x_drive_dir / "JULES_ZONE"
        self.manifest_path = self.x_drive_dir / MANIFEST_FILENAME
        self.index_path = self.x_drive_dir / INDEX_FILENAME
        self.client = client or XPoolClient(mode=mode)

    def _ensure_connected(self):
        """Probes gateway availability and prepares backend connection."""
        if self.client.mode == "auto" and self.client._active_backend != "direct_cloud":
            if self.client.probe_gateway(timeout=2):
                print(f"[xpool_sync] Connecting to Windows XPool Gateway: {self.client.base_url}")
            else:
                print(f"[xpool_sync] Windows PC Gateway offline / unreachable. Connecting to Direct Cloud Pool (google_unified:)...")
                self.client._init_direct_backend()
        elif self.client._active_backend == "direct_cloud" or self.client.mode == "direct":
            print(f"[xpool_sync] Operating in Direct Cloud Pool mode (google_unified:)")
        else:
            print(f"[xpool_sync] Connecting to XPool Gateway: {self.client.base_url}")

    def list_recursive(self, remote_dir: str) -> List[Dict[str, Any]]:
        """Recursively lists all files under a remote directory."""
        # Fast path if DirectCloudBackend is active
        if self.client._active_backend == "direct_cloud" and self.client._direct_backend:
            return self.client._direct_backend.list_recursive(remote_dir)

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

        self._ensure_connected()

        # 1. Index Root Directory (15.4 TiB Pool Map)
        try:
            root_res = self.client.list("/")
            backend_label = self.client._active_backend
            with open(self.index_path, "w", encoding="utf-8") as f:
                json.dump({
                    "synced_at": root_res.get("synced_at") or "",
                    "backend_mode": backend_label,
                    "endpoint": self.client.base_url if backend_label == "gateway" else "google_unified:",
                    "pool_root": "/",
                    "items": root_res.get("items", [])
                }, f, indent=2)
            print(f"[xpool_sync] Updated live pool index: {self.index_path.relative_to(self.workspace_root)} ({backend_label})")
        except Exception as e:
            print(f"[xpool_sync] Warning: Could not index root directory: {e}", file=sys.stderr)

        # 2. Recursively Sync /JULES_ZONE
        remote_files = self.list_recursive("/JULES_ZONE")
        manifest = load_manifest(self.manifest_path)
        updated_manifest = dict(manifest)
        pulled_count = 0
        total_bytes = 0

        print(f"[xpool_sync] Syncing /JULES_ZONE ({len(remote_files)} remote entries found)...")

        files_to_download: List[Tuple[str, str]] = []
        for rfile in remote_files:
            rpath = rfile["path"]
            # Relative path inside JULES_ZONE
            rel_path = rpath[len("/JULES_ZONE/"):].lstrip("/\\") if rpath.startswith("/JULES_ZONE/") else rpath.lstrip("/\\")
            if not rel_path:
                continue

            local_target = self.jules_zone_dir / rel_path
            needs_download = True
            if local_target.is_file():
                local_sha, local_size = compute_file_sha256(local_target)
                if rel_path in manifest and manifest[rel_path].get("sha256") == local_sha:
                    needs_download = False
                    updated_manifest[rel_path] = {
                        "sha256": local_sha,
                        "size_bytes": local_size,
                        "remote_path": rpath
                    }

            if needs_download:
                files_to_download.append((rel_path, rpath))

        if not files_to_download:
            save_manifest(self.manifest_path, updated_manifest)
            print(f"[xpool_sync] Pull complete: 0 files synced (all up to date).")
            return {"pulled_count": 0, "total_bytes": 0}

        # Concurrency & High-Speed Batching
        if self.client._active_backend == "direct_cloud" and self.client._direct_backend:
            # High-speed bulk rclone download with --transfers 16 --checkers 32 --fast-list
            rel_list = [rel for rel, _ in files_to_download]
            try:
                print(f"[xpool_sync] Executing bulk cloud download ({len(rel_list)} files, --transfers 16 --checkers 32 --fast-list)...")
                self.client._direct_backend.bulk_copy_from_cloud(
                    local_base=self.jules_zone_dir,
                    rel_paths=rel_list,
                    remote_prefix="JULES_ZONE"
                )
                for rel_path, rpath in files_to_download:
                    local_target = self.jules_zone_dir / rel_path
                    if local_target.is_file():
                        local_sha, local_size = compute_file_sha256(local_target)
                        updated_manifest[rel_path] = {
                            "sha256": local_sha,
                            "size_bytes": local_size,
                            "remote_path": rpath
                        }
                        pulled_count += 1
                        total_bytes += local_size
                        print(f"  + pulled: JULES_ZONE/{rel_path} ({local_size} bytes)")
            except Exception as bulk_err:
                print(f"[xpool_sync] Notice: Bulk pull failed ({bulk_err}), falling back to ThreadPoolExecutor(max_workers=8)...", file=sys.stderr)
                def _dl_worker(item: Tuple[str, str]):
                    r_rel, r_rpath = item
                    dest = self.jules_zone_dir / r_rel
                    read_res = self.client.read(r_rpath)
                    content_raw = read_res.get("content", "")
                    b = base64.b64decode(content_raw) if read_res.get("is_base64") else content_raw.encode("utf-8")
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with open(dest, "wb") as f:
                        f.write(b)
                    return r_rel, r_rpath, hashlib.sha256(b).hexdigest(), len(b)

                with ThreadPoolExecutor(max_workers=8) as executor:
                    futures = [executor.submit(_dl_worker, it) for it in files_to_download]
                    for fut in as_completed(futures):
                        try:
                            r_rel, r_rpath, sha, sz = fut.result()
                            updated_manifest[r_rel] = {"sha256": sha, "size_bytes": sz, "remote_path": r_rpath}
                            pulled_count += 1
                            total_bytes += sz
                            print(f"  + pulled: JULES_ZONE/{r_rel} ({sz} bytes)")
                        except Exception as e:
                            print(f"[xpool_sync] Error pulling file: {e}", file=sys.stderr)
        else:
            # GatewayBackend mode: ThreadPoolExecutor(max_workers=6)
            print(f"[xpool_sync] Pulling {len(files_to_download)} files via Gateway (ThreadPoolExecutor max_workers=6)...")
            manifest_lock = threading.Lock()

            def _gateway_dl_worker(item: Tuple[str, str]):
                r_rel, r_rpath = item
                dest = self.jules_zone_dir / r_rel
                read_res = self.client.read(r_rpath)
                content_raw = read_res.get("content", "")
                b = base64.b64decode(content_raw) if read_res.get("is_base64") else content_raw.encode("utf-8")
                dest.parent.mkdir(parents=True, exist_ok=True)
                with open(dest, "wb") as f:
                    f.write(b)
                sha = hashlib.sha256(b).hexdigest()
                sz = len(b)
                with manifest_lock:
                    updated_manifest[r_rel] = {"sha256": sha, "size_bytes": sz, "remote_path": r_rpath}
                return r_rel, sz

            with ThreadPoolExecutor(max_workers=6) as executor:
                futures = [executor.submit(_gateway_dl_worker, it) for it in files_to_download]
                for fut in as_completed(futures):
                    try:
                        r_rel, sz = fut.result()
                        pulled_count += 1
                        total_bytes += sz
                        print(f"  + pulled: JULES_ZONE/{r_rel} ({sz} bytes)")
                    except Exception as e:
                        print(f"[xpool_sync] Error pulling file: {e}", file=sys.stderr)

        save_manifest(self.manifest_path, updated_manifest)
        print(f"[xpool_sync] Pull complete: {pulled_count} files synced ({total_bytes} bytes).")
        return {"pulled_count": pulled_count, "total_bytes": total_bytes}

    def fetch(self, remote_path: str) -> Dict[str, Any]:
        """Fetches any read-only file or folder from anywhere in the 15.4 TiB pool into ./x_drive/."""
        clean_path = "/" + remote_path.strip("/\\")
        self._ensure_connected()
        print(f"[xpool_sync] Fetching '{clean_path}'...")

        read_fn = getattr(self.client, "read_file", getattr(self.client, "read", None))

        # Check if remote_path is a single file (via stat, read_file, or list)
        is_single_file = False
        stat_fn = getattr(self.client, "stat", None)
        if callable(stat_fn):
            try:
                st = stat_fn(clean_path)
                if st is not None:
                    is_single_file = not st.get("is_dir", False)
            except Exception:
                pass

        if not is_single_file:
            try:
                list_res = self.client.list(clean_path)
                items = list_res.get("items", [])
                if len(items) == 1 and not items[0].get("is_dir", False):
                    is_single_file = True
                elif len(items) == 0:
                    # Test if read_file succeeds
                    try:
                        read_fn(clean_path)
                        is_single_file = True
                    except Exception:
                        is_single_file = False
            except Exception:
                # If list failed, check if read_file succeeds
                try:
                    read_fn(clean_path)
                    is_single_file = True
                except Exception:
                    is_single_file = False

        fetched_files = []
        if is_single_file:
            rel_from_root = clean_path.lstrip("/\\")
            local_dest = self.x_drive_dir / rel_from_root
            try:
                read_res = read_fn(clean_path)
                content_raw = read_res.get("content", "")
                if read_res.get("is_base64"):
                    file_bytes = base64.b64decode(content_raw)
                elif isinstance(content_raw, str):
                    file_bytes = content_raw.encode("utf-8")
                else:
                    file_bytes = bytes(content_raw)
                local_dest.parent.mkdir(parents=True, exist_ok=True)
                with open(local_dest, "wb") as f:
                    f.write(file_bytes)
                fetched_files.append({"path": str(local_dest), "size": len(file_bytes)})
                print(f"[xpool_sync] Fetched single file to {local_dest.relative_to(self.workspace_root)} ({len(file_bytes)} bytes)")
            except Exception as e:
                raise RuntimeError(f"Failed to fetch '{clean_path}': {e}")
        else:
            remote_files = self.list_recursive(clean_path)
            def _fetch_worker(rfile):
                rpath = rfile["path"]
                rel_from_root = rpath.lstrip("/\\")
                local_dest = self.x_drive_dir / rel_from_root
                read_res = read_fn(rpath)
                content_raw = read_res.get("content", "")
                if read_res.get("is_base64"):
                    file_bytes = base64.b64decode(content_raw)
                elif isinstance(content_raw, str):
                    file_bytes = content_raw.encode("utf-8")
                else:
                    file_bytes = bytes(content_raw)
                local_dest.parent.mkdir(parents=True, exist_ok=True)
                with open(local_dest, "wb") as f:
                    f.write(file_bytes)
                return {"path": str(local_dest), "size": len(file_bytes), "rel": rel_from_root}

            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = [executor.submit(_fetch_worker, rf) for rf in remote_files]
                for fut in as_completed(futures):
                    try:
                        res = fut.result()
                        fetched_files.append({"path": res["path"], "size": res["size"]})
                        print(f"  + fetched: {res['rel']} ({res['size']} bytes)")
                    except Exception as e:
                        print(f"[xpool_sync] Error fetching file: {e}", file=sys.stderr)

        return {"status": "ok", "remote_path": clean_path, "fetched_files": fetched_files}

    def status(self) -> Dict[str, Any]:
        """Compares ./x_drive/JULES_ZONE against baseline manifest and returns diff."""
        if not self.jules_zone_dir.is_dir():
            return {"created": [], "modified": [], "deleted": []}

        manifest = load_manifest(self.manifest_path)
        created = []
        modified = []
        current_local_files: Set[str] = set()

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
        r"""Pushes created/modified files in ./x_drive/JULES_ZONE and removes deleted files on live storage."""
        if not self.jules_zone_dir.is_dir():
            print("[xpool_sync] No local JULES_ZONE directory found. Nothing to push.")
            return {"created": 0, "modified": 0, "deleted": 0}

        diff = self.status()
        created = diff["created"]
        modified = diff["modified"]
        deleted = diff["deleted"]

        total_changes = len(created) + len(modified) + len(deleted)
        if total_changes == 0:
            print("[xpool_sync] Everything up to date with live storage. No changes to push.")
            return {"created": 0, "modified": 0, "deleted": 0}

        self._ensure_connected()
        backend_name = self.client._active_backend
        print(f"[xpool_sync] Pushing {total_changes} changes to live storage ({backend_name})...")

        manifest = load_manifest(self.manifest_path)
        updated_manifest = dict(manifest)

        manifest_lock = threading.Lock()
        success_created = 0
        success_modified = 0
        success_deleted = 0

        if self.client._active_backend == "direct_cloud" and self.client._direct_backend:
            # 1. High-speed bulk CAS backup pass to google_unified:_JULES_PROTECTED_VAULT/
            to_backup_rel = [p for p in (modified + deleted)]
            if to_backup_rel:
                print(f"[xpool_sync] Running high-speed CAS backup pass for {len(to_backup_rel)} target files...")
                backup_results = self.client._direct_backend.bulk_cas_backup(to_backup_rel, remote_prefix="JULES_ZONE")
                backed_up_count = sum(1 for v in backup_results.values() if v)
                print(f"[xpool_sync] CAS backup pass complete: {backed_up_count} existing versions secured in vault.")

            # 2. Bulk upload created and modified files
            uploads = created + modified
            if uploads:
                print(f"[xpool_sync] Executing bulk cloud upload ({len(uploads)} files, --transfers 16 --checkers 32 --fast-list)...")
                try:
                    self.client._direct_backend.bulk_copy_to_cloud(
                        local_base=self.jules_zone_dir,
                        rel_paths=uploads,
                        remote_prefix="JULES_ZONE"
                    )
                    for rel_path in uploads:
                        local_path = self.jules_zone_dir / rel_path
                        file_sha, file_size = compute_file_sha256(local_path)
                        remote_path = f"/JULES_ZONE/{rel_path}"
                        updated_manifest[rel_path] = {
                            "sha256": file_sha,
                            "size_bytes": file_size,
                            "remote_path": remote_path
                        }
                        if rel_path in created:
                            success_created += 1
                            print(f"  + create: JULES_ZONE/{rel_path} ({file_size} bytes)")
                        else:
                            success_modified += 1
                            print(f"  * update: JULES_ZONE/{rel_path} ({file_size} bytes)")
                except Exception as upload_err:
                    print(f"[xpool_sync] Notice: Bulk upload failed ({upload_err}), falling back to ThreadPoolExecutor(max_workers=8)...", file=sys.stderr)
                    def _up_worker(rel_p):
                        loc_p = self.jules_zone_dir / rel_p
                        rem_p = f"/JULES_ZONE/{rel_p}"
                        with open(loc_p, "rb") as f:
                            d = f.read()
                        try:
                            c_str = d.decode("utf-8")
                            b64 = False
                        except UnicodeDecodeError:
                            c_str = base64.b64encode(d).decode("ascii")
                            b64 = True
                        res = self.client.write(path=rem_p, content=c_str, is_base64=b64)
                        f_sha, f_sz = compute_file_sha256(loc_p)
                        return rel_p, rem_p, f_sha, f_sz, res.get("backup_vault_id")

                    with ThreadPoolExecutor(max_workers=8) as executor:
                        futs = [executor.submit(_up_worker, p) for p in uploads]
                        for fut in as_completed(futs):
                            try:
                                rel_p, rem_p, sha, sz, b_id = fut.result()
                                updated_manifest[rel_p] = {"sha256": sha, "size_bytes": sz, "remote_path": rem_p}
                                if rel_p in created:
                                    success_created += 1
                                    print(f"  + create: JULES_ZONE/{rel_p} ({sz} bytes)")
                                else:
                                    success_modified += 1
                                    print(f"  * update: JULES_ZONE/{rel_p} ({sz} bytes)")
                            except Exception as e:
                                print(f"[xpool_sync] Failed to push file: {e}", file=sys.stderr)

            # 3. Bulk delete removed files
            if deleted:
                print(f"[xpool_sync] Executing bulk cloud deletion ({len(deleted)} files, --transfers 16 --checkers 32 --fast-list)...")
                try:
                    self.client._direct_backend.bulk_delete_cloud(
                        rel_paths=deleted,
                        remote_prefix="JULES_ZONE"
                    )
                    for rel_path in deleted:
                        if rel_path in updated_manifest:
                            del updated_manifest[rel_path]
                        success_deleted += 1
                        print(f"  - delete: JULES_ZONE/{rel_path} (protected in vault)")
                except Exception as del_err:
                    print(f"[xpool_sync] Notice: Bulk delete failed ({del_err}), falling back to ThreadPoolExecutor(max_workers=8)...", file=sys.stderr)
                    def _del_worker(rel_p):
                        rem_p = f"/JULES_ZONE/{rel_p}"
                        self.client.delete(path=rem_p)
                        return rel_p

                    with ThreadPoolExecutor(max_workers=8) as executor:
                        futs = [executor.submit(_del_worker, p) for p in deleted]
                        for fut in as_completed(futs):
                            try:
                                rel_p = fut.result()
                                if rel_p in updated_manifest:
                                    del updated_manifest[rel_p]
                                success_deleted += 1
                                print(f"  - delete: JULES_ZONE/{rel_p} (protected in vault)")
                            except Exception as e:
                                print(f"[xpool_sync] Failed to delete file: {e}", file=sys.stderr)

        else:
            # GatewayBackend mode: ThreadPoolExecutor(max_workers=6)
            uploads = created + modified
            if uploads:
                print(f"[xpool_sync] Pushing {len(uploads)} files via Gateway (ThreadPoolExecutor max_workers=6)...")
                def _gateway_up_worker(rel_p):
                    loc_p = self.jules_zone_dir / rel_p
                    rem_p = f"/JULES_ZONE/{rel_p}"
                    with open(loc_p, "rb") as f:
                        d = f.read()
                    try:
                        c_str = d.decode("utf-8")
                        b64 = False
                    except UnicodeDecodeError:
                        c_str = base64.b64encode(d).decode("ascii")
                        b64 = True
                    action = "create" if rel_p in created else "update"
                    res = self.client.write(path=rem_p, content=c_str, is_base64=b64)
                    f_sha, f_sz = compute_file_sha256(loc_p)
                    with manifest_lock:
                        updated_manifest[rel_p] = {"sha256": f_sha, "size_bytes": f_sz, "remote_path": rem_p}
                    return rel_p, action, f_sz, res.get("backup_vault_id")

                with ThreadPoolExecutor(max_workers=6) as executor:
                    futs = [executor.submit(_gateway_up_worker, p) for p in uploads]
                    for fut in as_completed(futs):
                        try:
                            rel_p, act, sz, b_id = fut.result()
                            if act == "create":
                                success_created += 1
                                print(f"  + create: JULES_ZONE/{rel_p} ({sz} bytes)")
                            else:
                                success_modified += 1
                                print(f"  * update: JULES_ZONE/{rel_p} ({sz} bytes)")
                        except Exception as e:
                            print(f"[xpool_sync] Failed to push file: {e}", file=sys.stderr)

            if deleted:
                print(f"[xpool_sync] Deleting {len(deleted)} files via Gateway (ThreadPoolExecutor max_workers=6)...")
                def _gateway_del_worker(rel_p):
                    rem_p = f"/JULES_ZONE/{rel_p}"
                    res = self.client.delete(path=rem_p)
                    with manifest_lock:
                        if rel_p in updated_manifest:
                            del updated_manifest[rel_p]
                    return rel_p, res.get("recovery_version_id", "yes")

                with ThreadPoolExecutor(max_workers=6) as executor:
                    futs = [executor.submit(_gateway_del_worker, p) for p in deleted]
                    for fut in as_completed(futs):
                        try:
                            rel_p, v_id = fut.result()
                            success_deleted += 1
                            print(f"  - delete: JULES_ZONE/{rel_p} (protected in vault: {v_id})")
                        except Exception as e:
                            print(f"[xpool_sync] Failed to delete file: {e}", file=sys.stderr)

        save_manifest(self.manifest_path, updated_manifest)
        print(f"[xpool_sync] Push complete: +{success_created} created, *{success_modified} modified, -{success_deleted} deleted.")

        # Automatic v27 Zero-Touch Brain Sync Post-Push Hook
        try:
            script_path = Path(__file__).resolve().parent / "scripts" / "jules_brain_sync.py"
            if script_path.is_file():
                summary_done = f"Pushed {success_created} created, {success_modified} modified, {success_deleted} deleted files to /JULES_ZONE/"
                cmd = [
                    sys.executable, str(script_path), "update",
                    "--agent", "Google-Jules (@google/jules)",
                    "--prompt", "Pushed task deliverables to /JULES_ZONE/ storage pool",
                    "--done", summary_done,
                    "--next", "Ready for Operator / Gemini architectural review"
                ]
                subprocess.run(cmd, capture_output=True, timeout=30)
                print("[xpool_sync] [HOOK] Auto-logged task deliverables to Universal Brain Ledger (v27).")
        except Exception:
            pass

        return {
            "created": success_created,
            "modified": success_modified,
            "deleted": success_deleted
        }


def main():
    parser = argparse.ArgumentParser(
        description="XPool Storage Sync Utility: 24/7 Git-style sync tool for 15.4 TiB pool (Online Gateway + Offline Direct Cloud)"
    )
    parser.add_argument("--mode", default="auto", choices=["auto", "gateway", "direct"], help="Operating backend mode")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # pull
    subparsers.add_parser("pull", help="Index root pool and sync /JULES_ZONE into ./x_drive/JULES_ZONE")

    # fetch
    p_fetch = subparsers.add_parser("fetch", help="Fetch any file or folder from the 15.4 TiB pool into ./x_drive")
    p_fetch.add_argument("remote_path", help="Canonical remote path (e.g. /AI-MEMORY/notes.txt or /SHARED_READONLY)")

    # push
    subparsers.add_parser("push", help="Push all created, modified, and deleted files in ./x_drive/JULES_ZONE back to live storage")

    # status
    subparsers.add_parser("status", help="Show working tree status comparing ./x_drive/JULES_ZONE to baseline manifest")

    args = parser.parse_args()
    manager = XPoolSyncManager(mode=args.mode)

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
