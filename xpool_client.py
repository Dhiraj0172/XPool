"""XPool Storage Access Gateway Client SDK & CLI with Dual-Mode Auto-Fallback.

Provides authenticated access to the 15.4 TiB XPool storage across:
1. Primary Mode (PC Online): Windows XPool Gateway via local loopback or Cloudflare tunnel.
2. Automatic Fallback Mode (PC Offline / Powered Off): DirectCloudBackend connecting
   directly to google_unified: via ephemeral decrypted rclone vault config with zero
   Windows PC dependency.
"""

import os
import sys
import json
import base64
import re
import shutil
import platform
import subprocess
import tempfile
import atexit
import argparse
import socket
import http.client
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request
import urllib.error
import urllib.parse
import zipfile
import io
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

try:
    from xpool_vault import decrypt_vault, find_vault_file
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from xpool_vault import decrypt_vault, find_vault_file


def find_repo_root() -> Optional[Path]:
    """Finds repository root by searching upward for CURRENT_TUNNEL_URL.json or .git."""
    start = Path(__file__).resolve().parent
    for _ in range(6):
        if (start / "CURRENT_TUNNEL_URL.json").is_file():
            return start
        if (start / ".git").is_dir():
            return start
        if start.parent == start:
            break
        start = start.parent
    return None


def read_tunnel_url_file() -> Optional[str]:
    """Reads CURRENT_TUNNEL_URL.json from repo root, cwd, or well-known system paths."""
    candidates = []

    repo_root = find_repo_root()
    if repo_root:
        candidates.append(repo_root / "CURRENT_TUNNEL_URL.json")

    candidates.append(Path.cwd() / "CURRENT_TUNNEL_URL.json")
    candidates.append(Path(r"C:\Users\ADMIN\jules-repo-staging\CURRENT_TUNNEL_URL.json"))
    candidates.append(Path(r"X:\JULES_ZONE\CURRENT_TUNNEL_URL.json"))
    candidates.append(Path(r"D:\xpool-gateway-sandbox\config\current_tunnel_url.json"))

    for candidate in candidates:
        if candidate.is_file():
            try:
                with open(candidate, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                    url = data.get("tunnel_url") or data.get("url")
                    if url and isinstance(url, str) and url.startswith("http"):
                        return url.strip().rstrip("/")
            except Exception:
                continue
    return None


def resolve_default_gateway_url(provided_url: Optional[str] = None) -> str:
    """Resolves gateway URL with precedence: provided -> env -> CURRENT_TUNNEL_URL.json -> loopback."""
    if provided_url and provided_url.strip():
        return provided_url.strip().rstrip("/")

    env_url = os.environ.get("XPOOL_GATEWAY_URL")
    if env_url and env_url.strip():
        return env_url.strip().rstrip("/")

    discovered = read_tunnel_url_file()
    if discovered:
        return discovered

    return "http://127.0.0.1:8888"


DEFAULT_GATEWAY_URL = resolve_default_gateway_url()
DEFAULT_TOKEN = os.environ.get("XPOOL_GATEWAY_TOKEN", "xpool-jules-sec-token-9b2f6a1e8c4d")

# Sensitive Credential Masking Patterns
_CREDENTIAL_KEY_PATTERN = re.compile(
    r'(?i)\b(access[_-]?token|refresh[_-]?token|bearer|token|secret|client[_-]?secret|password|passwd|api[_-]?key|apikey|credential[s]?|auth[a-z]*|signature|sig)\b(\s*[:=]\s*|\s+)["\']?[^\s"\'&,;]+["\']?'
)
_TOKEN_VALUE_PATTERN = re.compile(
    r'(?i)\b(?:ya29\.[a-zA-Z0-9_\-]+|ey[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]+|[a-zA-Z0-9_\-]*synthetic[a-zA-Z0-9_\-]*)\b'
)


def sanitize_text(text: Any) -> str:
    """Masks credentials and tokens with [REDACTED] to prevent credential leakage."""
    if not text or not isinstance(text, str):
        return ""
    clean = " ".join(text.strip().splitlines())
    clean = _CREDENTIAL_KEY_PATTERN.sub(r'\1\2[REDACTED]', clean)
    clean = _TOKEN_VALUE_PATTERN.sub('[REDACTED]', clean)
    if len(clean) > 300:
        clean = clean[:297] + "..."
    return clean


class DirectCloudBackend:
    """Direct Cloud Storage Backend for PC-Offline mode.
    Connects directly to google_unified: via rclone using an ephemeral decrypted config.
    Zero Windows PC dependencies; operates 24/7 anywhere in the world.
    """
    def __init__(self, vault_path: Optional[Path] = None):
        self.vault_path = vault_path or find_vault_file()
        if not self.vault_path or not self.vault_path.is_file():
            raise FileNotFoundError(f"Cloud vault file (.xpool_cloud_vault.bin) not found.")

        self._lock = threading.Lock()
        self.rclone_bin = self._find_or_install_rclone()
        self.ephemeral_conf = self._create_ephemeral_config()
        atexit.register(self.cleanup)

    def _find_or_install_rclone(self) -> str:
        """Finds existing rclone or downloads official standalone binary with zero root/sudo."""
        rc = shutil.which("rclone")
        if rc:
            return rc

        def _download_archive(url: str) -> bytes:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            req = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return resp.read()
            except Exception as url_err:
                try:
                    res = subprocess.run(
                        ["curl", "-fsSL", "-A", "Mozilla/5.0", url],
                        capture_output=True,
                        check=True
                    )
                    return res.stdout
                except Exception as curl_err:
                    raise RuntimeError(
                        f"Failed to download rclone from {url}: urllib error ({url_err}), curl fallback error ({curl_err})"
                    ) from url_err

        system = platform.system().lower()
        if system == "windows":
            candidates = [
                os.path.expanduser(r"~\AppData\Local\Microsoft\WinGet\Links\rclone.exe"),
                r"C:\Program Files\rclone\rclone.exe"
            ]
            for c in candidates:
                if os.path.isfile(c):
                    return c
            # Download standalone windows binary
            bin_dir = Path(tempfile.gettempdir()) / "xpool_bin"
            bin_exe = bin_dir / "rclone.exe"
            if bin_exe.is_file():
                return str(bin_exe)
            print("[DirectCloudBackend] Downloading standalone rclone for Windows...", file=sys.stderr)
            bin_dir.mkdir(parents=True, exist_ok=True)
            url = "https://downloads.rclone.org/rclone-current-windows-amd64.zip"
            zip_bytes = _download_archive(url)
            zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
            for name in zf.namelist():
                if name.endswith("rclone.exe"):
                    with open(bin_exe, "wb") as f:
                        f.write(zf.read(name))
                    break
            return str(bin_exe)
        else:
            # Linux standalone download strictly inside tempfile.gettempdir() (/tmp/xpool_bin)
            tmp_bin_dir = Path(tempfile.gettempdir()) / "xpool_bin"
            candidates = [
                tmp_bin_dir / "rclone",
                Path("/tmp/xpool_bin/rclone"),
                Path(os.path.expanduser("~/.local/bin/rclone"))
            ]
            for c in candidates:
                if c.is_file() and os.access(c, os.X_OK):
                    return str(c)

            bin_dir = tmp_bin_dir
            bin_exe = bin_dir / "rclone"
            if bin_exe.is_file() and os.access(bin_exe, os.X_OK):
                return str(bin_exe)

            print("[DirectCloudBackend] Downloading standalone rclone for Linux...", file=sys.stderr)
            bin_dir.mkdir(parents=True, exist_ok=True)
            url = "https://downloads.rclone.org/rclone-current-linux-amd64.zip"
            zip_bytes = _download_archive(url)
            zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
            for name in zf.namelist():
                if name.endswith("/rclone") and not name.endswith("/"):
                    with open(bin_exe, "wb") as f:
                        f.write(zf.read(name))
                    bin_exe.chmod(0o755)
                    break
            return str(bin_exe)

    def _create_ephemeral_config(self) -> Path:
        """Decrypts .xpool_cloud_vault.bin into an ephemeral config file (mode 0600)."""
        with open(self.vault_path, "rb") as f:
            enc_data = f.read()

        plain_bytes = decrypt_vault(enc_data)
        fd, tmp_path_str = tempfile.mkstemp(prefix="xpool_ephem_", suffix=".conf")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(plain_bytes)
            tmp_path = Path(tmp_path_str)
            try:
                os.chmod(tmp_path, 0o600)
            except Exception:
                pass
            return tmp_path
        except Exception:
            try:
                os.close(fd)
            except Exception:
                pass
            raise

    def cleanup(self):
        """Wipes and deletes the ephemeral config file on exit."""
        if hasattr(self, "ephemeral_conf") and self.ephemeral_conf and self.ephemeral_conf.is_file():
            try:
                size = self.ephemeral_conf.stat().st_size
                with open(self.ephemeral_conf, "r+b") as f:
                    f.write(b"\x00" * size)
                self.ephemeral_conf.unlink(missing_ok=True)
            except Exception:
                pass

    def _run_rclone(self, args: List[str], input_data: Optional[bytes] = None, timeout: int = 60) -> subprocess.CompletedProcess:
        """Executes rclone command against ephemeral config."""
        cmd = [
            self.rclone_bin,
            "--config", str(self.ephemeral_conf),
            "--drive-pacer-min-sleep", "10ms",
            "--drive-use-trash=false",
            "--server-side-across-configs"
        ] + args
        return subprocess.run(
            cmd,
            input=input_data,
            capture_output=True,
            timeout=timeout
        )

    def health(self) -> Dict[str, Any]:
        """Queries health in DirectCloud mode."""
        proc = self._run_rclone(["version"], timeout=10)
        return {
            "status": "healthy",
            "mode": "direct_cloud",
            "backend": "rclone",
            "remote": "google_unified",
            "rclone_bin": self.rclone_bin,
            "rclone_version": proc.stdout.decode("utf-8", errors="replace").splitlines()[0] if proc.stdout else "unknown"
        }

    def list(self, path: str = "/") -> Dict[str, Any]:
        """Lists directory contents on google_unified: (allowed across all 15.4 TiB)."""
        clean = path.replace("\\", "/").strip("/")
        remote_target = f"google_unified:{clean}" if clean else "google_unified:"

        proc = self._run_rclone(["lsjson", remote_target], timeout=45)
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Direct cloud list failed on '{path}': {err}")

        items_raw = json.loads(proc.stdout.decode("utf-8"))
        items = []
        for it in items_raw:
            if len(items_raw) == 1 and not it.get("IsDir", False) and (clean == it.get("Path") or clean.endswith("/" + it.get("Path"))):
                sub_path = clean
            else:
                sub_path = f"/{clean}/{it['Path']}".strip("/") if clean else it["Path"]
            items.append({
                "name": it.get("Name"),
                "path": "/" + sub_path,
                "is_dir": it.get("IsDir", False),
                "size_bytes": it.get("Size", 0) if not it.get("IsDir", False) else 0,
                "modified_at": it.get("ModTime", "")
            })

        return {
            "status": "ok",
            "path": "/" + clean,
            "items": items
        }

    def list_recursive(self, path: str = "/") -> List[Dict[str, Any]]:
        """Fast recursive directory listing using rclone lsjson -R."""
        clean = path.replace("\\", "/").strip("/")
        remote_target = f"google_unified:{clean}" if clean else "google_unified:"

        proc = self._run_rclone(["lsjson", "-R", remote_target], timeout=60)
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Direct cloud recursive list failed on '{path}': {err}")

        items_raw = json.loads(proc.stdout.decode("utf-8"))
        items = []
        for it in items_raw:
            if it.get("IsDir", False):
                continue
            if len(items_raw) == 1 and not it.get("IsDir", False) and (clean == it.get("Path") or clean.endswith("/" + it.get("Path"))):
                sub_path = clean
            else:
                sub_path = f"/{clean}/{it['Path']}".strip("/") if clean else it["Path"]
            items.append({
                "name": it.get("Name"),
                "path": "/" + sub_path,
                "is_dir": False,
                "size_bytes": it.get("Size", 0),
                "modified_at": it.get("ModTime", "")
            })
        return items

    def stat(self, path: str) -> Optional[Dict[str, Any]]:
        """Returns metadata for a file or directory on google_unified:."""
        clean = path.replace("\\", "/").strip("/")
        remote_target = f"google_unified:{clean}" if clean else "google_unified:"
        proc = self._run_rclone(["lsjson", remote_target], timeout=30)
        if proc.returncode != 0:
            return None
        try:
            items_raw = json.loads(proc.stdout.decode("utf-8"))
        except Exception:
            return None
        if not items_raw:
            return None
        if len(items_raw) == 1 and not items_raw[0].get("IsDir", False):
            it = items_raw[0]
            return {
                "name": it.get("Name"),
                "path": "/" + clean,
                "is_dir": False,
                "size_bytes": it.get("Size", 0),
                "modified_at": it.get("ModTime", "")
            }
        return {
            "name": Path(clean).name if clean else "",
            "path": "/" + clean,
            "is_dir": True,
            "size_bytes": 0,
            "modified_at": ""
        }

    def read_file(self, path: str) -> Dict[str, Any]:
        """Reads file contents on google_unified: (alias for read)."""
        return self.read(path)

    def read(self, path: str) -> Dict[str, Any]:
        """Reads file contents on google_unified: (allowed across all 15.4 TiB)."""
        clean = path.replace("\\", "/").strip("/")
        if not clean:
            raise ValueError("Cannot read root directory as a file")

        remote_target = f"google_unified:{clean}"
        proc = self._run_rclone(["cat", remote_target], timeout=60)
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Direct cloud read failed on '{path}': {err}")

        raw_bytes = proc.stdout
        try:
            content_str = raw_bytes.decode("utf-8")
            is_b64 = False
        except UnicodeDecodeError:
            content_str = base64.b64encode(raw_bytes).decode("ascii")
            is_b64 = True

        return {
            "status": "ok",
            "path": "/" + clean,
            "content": content_str,
            "is_base64": is_b64
        }

    def _ensure_cas_backup(self, clean_path: str) -> Optional[str]:
        """Synchronously backs up an existing file into _JULES_PROTECTED_VAULT before mutation via server-side copy."""
        remote_target = f"google_unified:{clean_path}"
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        fname = os.path.basename(clean_path)
        token = hashlib.sha256(f"{clean_path}_{ts}".encode()).hexdigest()[:16]
        backup_name = f"{ts}_{token}_{fname}"
        vault_target = f"google_unified:_JULES_PROTECTED_VAULT/{backup_name}"
        copy_proc = self._run_rclone(["copyto", remote_target, vault_target, "--no-traverse"], timeout=30)
        if copy_proc.returncode == 0:
            print(f"[DirectCloudBackend] CAS Backup secured in vault: {backup_name}", file=sys.stderr)
            return backup_name
        return None

    def bulk_cas_backup(
        self,
        rel_paths: List[str],
        remote_prefix: str = "JULES_ZONE",
        transfers: int = 16,
        checkers: int = 32
    ) -> Dict[str, str]:
        """High-speed bulk server-side CAS backup into _JULES_PROTECTED_VAULT using rclone copy."""
        if not rel_paths:
            return {}
        clean_prefix = remote_prefix.replace("\\", "/").strip("/")
        norm_paths = [p.replace("\\", "/").lstrip("/") for p in rel_paths]
        
        fd, tmp_list_str = tempfile.mkstemp(prefix="xpool_bulk_cas_", suffix=".txt")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                tmp.write("\n".join(norm_paths) + "\n")
            
            vault_dest = f"google_unified:_JULES_PROTECTED_VAULT"
            args = [
                "copy",
                f"google_unified:{clean_prefix}",
                vault_dest,
                "--files-from-raw", tmp_list_str,
                "--transfers", str(transfers),
                "--checkers", str(checkers),
                "--fast-list"
            ]
            proc = self._run_rclone(args, timeout=120)
            if proc.returncode != 0:
                print(f"[DirectCloudBackend] Notice: Bulk CAS backup returned {proc.returncode}, falling back to parallel copyto...", file=sys.stderr)
                return self.parallel_cas_backup([f"{clean_prefix}/{p}" for p in norm_paths])
            
            return {p: f"_JULES_PROTECTED_VAULT/{p}" for p in norm_paths}
        finally:
            Path(tmp_list_str).unlink(missing_ok=True)

    def parallel_cas_backup(self, clean_paths: List[str], max_workers: int = 16) -> Dict[str, Optional[str]]:
        """Synchronously backs up multiple existing files in parallel into _JULES_PROTECTED_VAULT."""
        if not clean_paths:
            return {}
        results: Dict[str, Optional[str]] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_path = {
                executor.submit(self._ensure_cas_backup, p): p for p in clean_paths
            }
            for future in as_completed(future_to_path):
                p = future_to_path[future]
                try:
                    results[p] = future.result()
                except Exception as e:
                    print(f"[DirectCloudBackend] CAS Backup warning for '{p}': {e}", file=sys.stderr)
                    results[p] = None
        return results

    def bulk_copy_to_cloud(
        self,
        local_base: Path,
        rel_paths: List[str],
        remote_prefix: str = "JULES_ZONE",
        transfers: int = 16,
        checkers: int = 32
    ) -> Dict[str, Any]:
        """High-speed bulk upload of files to cloud using rclone --files-from-raw."""
        clean_prefix = remote_prefix.replace("\\", "/").strip("/")
        if not (clean_prefix == "JULES_ZONE" or clean_prefix.startswith("JULES_ZONE/")):
            raise PermissionError(f"DirectCloudBackend safety policy violation: Mutations strictly restricted to /JULES_ZONE (attempted: '{remote_prefix}')")

        norm_paths = [p.replace("\\", "/").lstrip("/") for p in rel_paths]
        fd, tmp_list_str = tempfile.mkstemp(prefix="xpool_bulk_up_", suffix=".txt")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                tmp.write("\n".join(norm_paths) + "\n")
            remote_dest = f"google_unified:{clean_prefix}"
            args = [
                "copy",
                str(local_base),
                remote_dest,
                "--files-from-raw", tmp_list_str,
                "--transfers", str(transfers),
                "--checkers", str(checkers),
                "--fast-list",
                "--no-traverse",
                "--drive-chunk-size", "32M",
                "--drive-upload-cutoff", "32M"
            ]
            proc = self._run_rclone(args, timeout=300)
            if proc.returncode != 0:
                err = proc.stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"Direct cloud bulk copy to cloud failed: {err}")
            return {"status": "ok", "transferred_count": len(norm_paths)}
        finally:
            Path(tmp_list_str).unlink(missing_ok=True)

    def bulk_copy_from_cloud(
        self,
        local_base: Path,
        rel_paths: List[str],
        remote_prefix: str = "JULES_ZONE",
        transfers: int = 16,
        checkers: int = 32
    ) -> Dict[str, Any]:
        """High-speed bulk download of files from cloud using rclone --files-from-raw."""
        clean_prefix = remote_prefix.replace("\\", "/").strip("/")
        norm_paths = [p.replace("\\", "/").lstrip("/") for p in rel_paths]
        fd, tmp_list_str = tempfile.mkstemp(prefix="xpool_bulk_dl_", suffix=".txt")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                tmp.write("\n".join(norm_paths) + "\n")
            remote_src = f"google_unified:{clean_prefix}"
            local_base.mkdir(parents=True, exist_ok=True)
            args = [
                "copy",
                remote_src,
                str(local_base),
                "--files-from-raw", tmp_list_str,
                "--transfers", str(transfers),
                "--checkers", str(checkers),
                "--fast-list",
                "--drive-chunk-size", "32M"
            ]
            proc = self._run_rclone(args, timeout=300)
            if proc.returncode != 0:
                err = proc.stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"Direct cloud bulk copy from cloud failed: {err}")
            return {"status": "ok", "transferred_count": len(norm_paths)}
        finally:
            Path(tmp_list_str).unlink(missing_ok=True)

    def bulk_delete_cloud(
        self,
        rel_paths: List[str],
        remote_prefix: str = "JULES_ZONE",
        transfers: int = 16,
        checkers: int = 32
    ) -> Dict[str, Any]:
        """High-speed bulk deletion of files on cloud using rclone --files-from-raw."""
        clean_prefix = remote_prefix.replace("\\", "/").strip("/")
        if not (clean_prefix == "JULES_ZONE" or clean_prefix.startswith("JULES_ZONE/")):
            raise PermissionError(f"DirectCloudBackend safety policy violation: Mutations strictly restricted to /JULES_ZONE (attempted: '{remote_prefix}')")

        norm_paths = [p.replace("\\", "/").lstrip("/") for p in rel_paths]
        fd, tmp_list_str = tempfile.mkstemp(prefix="xpool_bulk_del_", suffix=".txt")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                tmp.write("\n".join(norm_paths) + "\n")
            remote_dest = f"google_unified:{clean_prefix}"
            args = [
                "delete",
                remote_dest,
                "--files-from-raw", tmp_list_str,
                "--transfers", str(transfers),
                "--checkers", str(checkers),
                "--fast-list"
            ]
            proc = self._run_rclone(args, timeout=120)
            if proc.returncode != 0:
                err = proc.stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"Direct cloud bulk delete failed: {err}")
            return {"status": "deleted", "deleted_count": len(norm_paths)}
        finally:
            Path(tmp_list_str).unlink(missing_ok=True)

    def write(self, path: str, content: str, is_base64: bool = False) -> Dict[str, Any]:
        """Writes/overwrites a file inside /JULES_ZONE with CAS backup."""
        clean = path.replace("\\", "/").strip("/")
        # Safety policy: mutations strictly restricted to /JULES_ZONE
        if not (clean == "JULES_ZONE" or clean.startswith("JULES_ZONE/")):
            raise PermissionError(f"DirectCloudBackend safety policy violation: Mutations strictly restricted to /JULES_ZONE (attempted: '{path}')")

        if is_base64:
            raw_bytes = base64.b64decode(content)
        else:
            raw_bytes = content.encode("utf-8")

        # 1. Pre-overwrite CAS backup
        backup_id = self._ensure_cas_backup(clean)

        # 2. Write to remote via ephemeral temp file
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(raw_bytes)
            tmp_path = tmp.name

        try:
            remote_target = f"google_unified:{clean}"
            proc = self._run_rclone(["copyto", tmp_path, remote_target], timeout=60)
            if proc.returncode != 0:
                err = proc.stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"Direct cloud write failed on '{path}': {err}")
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        return {
            "status": "written",
            "path": "/" + clean,
            "size_bytes": len(raw_bytes),
            "backup_vault_id": backup_id
        }

    def delete(self, path: str) -> Dict[str, Any]:
        """Deletes a file inside /JULES_ZONE with pre-delete CAS backup."""
        clean = path.replace("\\", "/").strip("/")
        # Safety policy: mutations strictly restricted to /JULES_ZONE
        if not (clean == "JULES_ZONE" or clean.startswith("JULES_ZONE/")):
            raise PermissionError(f"DirectCloudBackend safety policy violation: Mutations strictly restricted to /JULES_ZONE (attempted: '{path}')")

        # 1. Pre-delete CAS backup
        backup_id = self._ensure_cas_backup(clean)

        # 2. Delete file
        remote_target = f"google_unified:{clean}"
        proc = self._run_rclone(["deletefile", remote_target], timeout=45)
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Direct cloud delete failed on '{path}': {err}")

        return {
            "status": "deleted",
            "path": "/" + clean,
            "recovery_version_id": backup_id or "not_found_on_remote"
        }

    def restore(self, version_id: str, target_path: Optional[str] = None) -> Dict[str, Any]:
        """Restores a version from _JULES_PROTECTED_VAULT."""
        clean_target = (target_path or f"JULES_ZONE/{version_id.split('_')[-1]}").replace("\\", "/").strip("/")
        vault_source = f"google_unified:_JULES_PROTECTED_VAULT/{version_id}"
        dest_target = f"google_unified:{clean_target}"

        proc = self._run_rclone(["copyto", vault_source, dest_target], timeout=60)
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Direct cloud restore failed: {err}")

        return {
            "status": "restored",
            "version_id": version_id,
            "target_path": "/" + clean_target
        }


class XPoolClient:
    """Official Python Client for XPool + Jules Storage Gateway with Dual-Mode Auto-Fallback."""
    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        mode: str = "auto"
    ):
        self.mode = mode.lower()
        self.base_url = resolve_default_gateway_url(base_url)
        self.token = token or os.environ.get("XPOOL_GATEWAY_TOKEN", DEFAULT_TOKEN)
        self._direct_backend: Optional[DirectCloudBackend] = None
        self._active_backend: str = "gateway" if self.mode != "direct" else "direct_cloud"
        self._lock = threading.Lock()

        # Explicit direct mode
        if self.mode == "direct":
            self._init_direct_backend()

    def _init_direct_backend(self) -> DirectCloudBackend:
        """Instantiates DirectCloudBackend if not already initialized (thread-safe)."""
        with self._lock:
            if self._direct_backend is None:
                self._direct_backend = DirectCloudBackend()
            self._active_backend = "direct_cloud"
        return self._direct_backend

    def is_gateway_offline_url(self, url: str) -> bool:
        """Checks if URL is explicitly designated for offline simulation."""
        return "offline-pc-simulation" in url.lower()

    def probe_gateway(self, timeout: int = 3) -> bool:
        """Performs a lightweight 3-second probe to check if the Gateway is reachable."""
        if self.is_gateway_offline_url(self.base_url):
            return False

        probe_url = f"{self.base_url}/api/v1/health"
        req = urllib.request.Request(
            probe_url,
            headers={"Authorization": f"Bearer {self.token}", "X-Role": "jules_agent"}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _request(
        self,
        method: str,
        endpoint: str,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = 35,
        retried_after_failover: bool = False
    ) -> Dict[str, Any]:
        """Executes JSON HTTP request against gateway with auto-failover to DirectCloudBackend."""
        if self._active_backend == "direct_cloud" or self.mode == "direct":
            raise RuntimeError("FAILOVER_TO_DIRECT_CLOUD")

        # Check for simulated offline URL
        if self.is_gateway_offline_url(self.base_url) and self.mode in ("auto", "gateway", "direct"):
            print(
                f"[XPoolClient] Notice: Offline PC simulation detected ({self.base_url}). "
                f"Auto-switching to DirectCloudBackend (15.4 TiB google_unified: direct connection)...",
                file=sys.stderr
            )
            self._init_direct_backend()
            raise RuntimeError("FAILOVER_TO_DIRECT_CLOUD")

        url = f"{self.base_url}{endpoint}"
        if params:
            url += "?" + urllib.parse.urlencode(params)

        data = None
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "X-Role": "jules_agent"
        }
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp_bytes = resp.read()
                try:
                    return json.loads(resp_bytes.decode("utf-8"))
                except Exception:
                    return {"raw": resp_bytes.decode("utf-8", errors="replace")}
        except urllib.error.HTTPError as e:
            # Cloudflare / Gateway timeout / connection failure codes (500, 502, 503, 504, 520-530, 404)
            if e.code in (500, 502, 503, 504, 520, 521, 522, 523, 524, 525, 526, 530, 404) and self.mode in ("auto", "gateway"):
                print(
                    f"[XPoolClient] Notice: Gateway returned HTTP {e.code} (Windows PC uplink saturated / offline / timeout). "
                    f"Auto-switching to DirectCloudBackend (15.4 TiB google_unified: direct connection)...",
                    file=sys.stderr
                )
                self._init_direct_backend()
                raise RuntimeError("FAILOVER_TO_DIRECT_CLOUD")

            err_body = e.read().decode("utf-8", errors="replace")
            clean_err = sanitize_text(err_body)
            try:
                parsed = json.loads(err_body)
                msg = parsed.get("detail") or parsed.get("error") or clean_err
            except Exception:
                msg = clean_err
            raise RuntimeError(f"Gateway HTTP {e.code} Error on {endpoint}: {msg}")
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionResetError, http.client.RemoteDisconnected) as e:
            reason_str = str(getattr(e, "reason", e)).lower()
            is_nxdomain = any(term in reason_str for term in [
                "getaddrinfo failed",
                "not known",
                "could not be resolved",
                "11001",
                "nodename nor servname provided"
            ])
            # NXDOMAIN: Attempt to reload live tunnel URL first
            if is_nxdomain and not retried_after_failover:
                fresh_url = read_tunnel_url_file()
                if fresh_url and fresh_url != self.base_url:
                    print(
                        f"[XPoolClient] Notice: Gateway '{self.base_url}' returned NXDOMAIN. "
                        f"Auto-failing over to live URL: '{fresh_url}'",
                        file=sys.stderr
                    )
                    self.base_url = fresh_url
                    return self._request(
                        method=method,
                        endpoint=endpoint,
                        json_body=json_body,
                        params=params,
                        timeout=timeout,
                        retried_after_failover=True
                    )

            # If still unreachable or timed out and in auto/gateway mode, switch to DirectCloudBackend
            if self.mode in ("auto", "gateway"):
                print(
                    f"[XPoolClient] Notice: Gateway connection error/timeout ({sanitize_text(str(e))}). "
                    f"Auto-switching to DirectCloudBackend (15.4 TiB google_unified: direct connection)...",
                    file=sys.stderr
                )
                self._init_direct_backend()
                raise RuntimeError("FAILOVER_TO_DIRECT_CLOUD")

            clean_reason = sanitize_text(str(e))
            raise RuntimeError(f"Gateway Connection Error on {endpoint}: {clean_reason}")

    def health(self) -> Dict[str, Any]:
        """Queries health of active backend (Gateway or DirectCloud)."""
        if self._active_backend == "direct_cloud" or self.mode == "direct":
            return self._init_direct_backend().health()
        try:
            return self._request("GET", "/api/v1/health")
        except Exception as e:
            if str(e) == "FAILOVER_TO_DIRECT_CLOUD" or self._active_backend == "direct_cloud":
                return self._init_direct_backend().health()
            raise

    def list(self, path: str = "/") -> Dict[str, Any]:
        """Lists directory contents via Gateway or DirectCloudBackend."""
        if self._active_backend == "direct_cloud" or self.mode == "direct":
            return self._init_direct_backend().list(path)
        try:
            return self._request("POST", "/api/v1/list", json_body={"path": path})
        except Exception as e:
            if str(e) == "FAILOVER_TO_DIRECT_CLOUD" or self._active_backend == "direct_cloud":
                return self._init_direct_backend().list(path)
            raise

    def read_file(self, path: str) -> Dict[str, Any]:
        """Reads file contents via Gateway or DirectCloudBackend (alias for read)."""
        return self.read(path)

    def read(self, path: str) -> Dict[str, Any]:
        """Reads file contents via Gateway or DirectCloudBackend."""
        if self._active_backend == "direct_cloud" or self.mode == "direct":
            return self._init_direct_backend().read(path)
        try:
            return self._request("POST", "/api/v1/read", json_body={"path": path})
        except Exception as e:
            if str(e) == "FAILOVER_TO_DIRECT_CLOUD" or self._active_backend == "direct_cloud":
                return self._init_direct_backend().read(path)
            raise

    def stat(self, path: str) -> Optional[Dict[str, Any]]:
        """Returns metadata for path via Gateway or DirectCloudBackend."""
        if self._active_backend == "direct_cloud" or self.mode == "direct":
            return self._init_direct_backend().stat(path)
        try:
            return self._request("POST", "/api/v1/stat", json_body={"path": path})
        except Exception:
            try:
                return self._init_direct_backend().stat(path)
            except Exception:
                return None

    def write(self, path: str, content: str, is_base64: bool = False) -> Dict[str, Any]:
        """Writes or overwrites a file via Gateway or DirectCloudBackend under fail-closed protection."""
        if self._active_backend == "direct_cloud" or self.mode == "direct":
            return self._init_direct_backend().write(path, content, is_base64)
        try:
            return self._request("POST", "/api/v1/write", json_body={
                "path": path,
                "content": content,
                "is_base64": is_base64
            })
        except Exception as e:
            if str(e) == "FAILOVER_TO_DIRECT_CLOUD" or self._active_backend == "direct_cloud":
                return self._init_direct_backend().write(path, content, is_base64)
            raise

    def delete(self, path: str) -> Dict[str, Any]:
        """Deletes a file via Gateway or DirectCloudBackend with synchronous pre-delete backup."""
        if self._active_backend == "direct_cloud" or self.mode == "direct":
            return self._init_direct_backend().delete(path)
        try:
            return self._request("POST", "/api/v1/delete", json_body={"path": path})
        except Exception as e:
            if str(e) == "FAILOVER_TO_DIRECT_CLOUD" or self._active_backend == "direct_cloud":
                return self._init_direct_backend().delete(path)
            raise

    def restore(self, version_id: str, target_path: Optional[str] = None) -> Dict[str, Any]:
        """Restores a version from the protected CAS vault."""
        if self._active_backend == "direct_cloud" or self.mode == "direct":
            return self._init_direct_backend().restore(version_id, target_path)
        payload: Dict[str, Any] = {"version_id": version_id}
        if target_path:
            payload["target_path"] = target_path
        try:
            return self._request("POST", "/api/v1/restore", json_body=payload)
        except Exception as e:
            if str(e) == "FAILOVER_TO_DIRECT_CLOUD" or self._active_backend == "direct_cloud":
                return self._init_direct_backend().restore(version_id, target_path)
            raise

    def approve(self, approval_id: str, decision: str = "APPROVED") -> Dict[str, Any]:
        """Resolves an owner approval request (Gateway only)."""
        return self._request("POST", "/api/v1/approve", json_body={
            "approval_id": approval_id,
            "decision": decision
        })


def main():
    parser = argparse.ArgumentParser(description="XPool Storage Access Gateway Client CLI (Dual-Mode Auto-Fallback)")
    parser.add_argument("--url", default=None, help="Gateway base URL (default: $XPOOL_GATEWAY_URL or CURRENT_TUNNEL_URL.json)")
    parser.add_argument("--token", default=None, help="Bearer authorization token (default: $XPOOL_GATEWAY_TOKEN)")
    parser.add_argument("--mode", default="auto", choices=["auto", "gateway", "direct"], help="Operating backend mode")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # health
    subparsers.add_parser("health", help="Check storage backend health")

    # list
    p_list = subparsers.add_parser("list", help="List directory contents")
    p_list.add_argument("path", nargs="?", default="/", help="Path to list (default: /)")

    # read
    p_read = subparsers.add_parser("read", help="Read file contents")
    p_read.add_argument("path", help="Path of file to read")

    # write
    p_write = subparsers.add_parser("write", help="Write content to a file")
    p_write.add_argument("path", help="Target path to write")
    p_write.add_argument("content", help="String content to write")

    # delete
    p_del = subparsers.add_parser("delete", help="Delete a file")
    p_del.add_argument("path", help="Target path to delete")

    # restore
    p_rest = subparsers.add_parser("restore", help="Restore a version from the backup vault")
    p_rest.add_argument("version_id", help="Version ID to restore")
    p_rest.add_argument("--target", default=None, help="Optional target restoration path")

    # approve
    p_appr = subparsers.add_parser("approve", help="Approve or reject a circuit breaker request")
    p_appr.add_argument("approval_id", help="Approval ID")
    p_appr.add_argument("--decision", default="APPROVED", choices=["APPROVED", "REJECTED"], help="Decision")

    args = parser.parse_args()
    client = XPoolClient(base_url=args.url, token=args.token, mode=args.mode)

    try:
        if args.command == "health":
            res = client.health()
        elif args.command == "list":
            res = client.list(args.path)
        elif args.command == "read":
            res = client.read(args.path)
        elif args.command == "write":
            res = client.write(args.path, args.content)
        elif args.command == "delete":
            res = client.delete(args.path)
        elif args.command == "restore":
            res = client.restore(args.version_id, args.target)
        elif args.command == "approve":
            res = client.approve(args.approval_id, args.decision)
        else:
            parser.print_help()
            return

        print(json.dumps(res, indent=2))
    except Exception as e:
        print(f"Error: {sanitize_text(str(e))}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
