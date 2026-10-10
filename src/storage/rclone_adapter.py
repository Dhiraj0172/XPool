import httpx
import time
from typing import List, Dict, Any
from src.common.types import JulesPath
from src.common.errors import BackendQuotaError, GatewayError
import os

class RcloneRCAdapter:
    """
    Adapter bridging the Gateway to an isolated rclone RC daemon.
    Does not assume direct production config access. Uses dependency-injected parameters.
    """

    def __init__(self, rc_url: str = "http://localhost:5572", remote_name: str = "local_mock:", jules_zone_root: str = "/"):
        self.rc_url = rc_url
        self.remote_name = remote_name
        # Keep internal paths relative to the jules zone root
        import pathlib
        self.jules_zone_root = pathlib.Path(jules_zone_root).resolve()

    def _execute_rc(self, command: str, payload: Dict[str, Any] = None, files: Dict[str, Any] = None, retries: int = 0) -> Dict[str, Any]:
        """Base wrapper executing POST against the Rclone RC daemon, with exponential backoff."""
        if payload is None:
            payload = {}

        attempt = 0
        while attempt <= retries:
            try:
                with httpx.Client(timeout=25.0) as client:
                    if files:
                        response = client.post(f"{self.rc_url}/{command}", data=payload, files=files)
                    else:
                        response = client.post(f"{self.rc_url}/{command}", json=payload)

                response.raise_for_status()

                content_type = response.headers.get("content-type", "")
                if "application/json" in content_type:
                    return response.json()
                return {"_raw": response.content}

            except httpx.HTTPStatusError as exc:
                error_msg = "Unknown rclone backend failure"
                content_type = exc.response.headers.get("content-type", "")
                if "application/json" in content_type:
                    error_msg = exc.response.json().get("error", error_msg)
                elif exc.response.text:
                    error_msg = exc.response.text.strip()

                # Quota limits and not-found should not be retried as transient
                if "not found" in error_msg.lower() or exc.response.status_code == 404:
                    raise FileNotFoundError(f"File not found: {error_msg}")

                if "quota" in error_msg.lower() or exc.response.status_code == 429:
                    raise BackendQuotaError(f"Backend Quota Exceeded: {error_msg}")

                if attempt == retries:
                    raise GatewayError(f"RC command {command} failed: {error_msg}", code=exc.response.status_code)

            except httpx.RequestError:
                if attempt == retries:
                    raise GatewayError(f"Connection to backend RC failed", code=502)

            attempt += 1
            time.sleep(2 ** attempt)

    def _get_remote_path(self, path: JulesPath) -> str:
        """Converts the resolved canonical path back to a safe relative string for the backend"""
        try:
            import pathlib
            # We strictly enforce that the path is within the Jules Zone Root
            rel_path = path.canonical_path.relative_to(self.jules_zone_root)
            if rel_path == pathlib.Path("."):
                raise GatewayError("Cannot target JULES_ZONE_ROOT itself", code=403)
        except ValueError:
            raise GatewayError("Path traversal prevented at storage layer", code=403)

        # Ensure forward slashes for rclone, regardless of host OS
        return rel_path.as_posix()

    def read(self, path: JulesPath) -> bytes:
        raise NotImplementedError("Direct memory read via RC is insecure and memory-bound. Use backend copy/hash operations.")

    def hash(self, path: JulesPath, hash_type: str = "sha256") -> str:
        remote_path = self._get_remote_path(path)
        payload = {
            "fs": self.remote_name,
            "remote": remote_path,
            "hashType": hash_type
        }
        try:
            result = self._execute_rc("operations/hashsumfile", payload=payload, retries=3)
            return result.get("hash", "")
        except FileNotFoundError:
            raise
        except Exception as e:
            if "not found" in str(e).lower():
                raise FileNotFoundError(f"File not found: {e}")
            raise

    def write(self, path: JulesPath, data: bytes) -> bool:
        remote_path = self._get_remote_path(path)
        payload = {
            "fs": self.remote_name,
            "remote": remote_path
        }
        files = {"file": ("upload", data)}
        self._execute_rc("operations/uploadfile", payload=payload, files=files, retries=3)
        return True

    def delete(self, path: JulesPath) -> bool:
        remote_path = self._get_remote_path(path)
        payload = {
            "fs": self.remote_name,
            "remote": remote_path
        }
        try:
            self._execute_rc("operations/deletefile", payload=payload, retries=3)
            return True
        except FileNotFoundError:
            return True # Delete is idempotent

    def copy(self, src: JulesPath, dst: JulesPath) -> bool:
        payload = {
            "srcFs": self.remote_name,
            "srcRemote": self._get_remote_path(src),
            "dstFs": self.remote_name,
            "dstRemote": self._get_remote_path(dst)
        }
        self._execute_rc("operations/copyfile", payload=payload, retries=3)
        return True

    def move(self, src: JulesPath, dst: JulesPath) -> bool:
        payload = {
            "srcFs": self.remote_name,
            "srcRemote": self._get_remote_path(src),
            "dstFs": self.remote_name,
            "dstRemote": self._get_remote_path(dst)
        }
        # Move is NOT idempotent. We must not blindly retry it.
        self._execute_rc("operations/movefile", payload=payload, retries=0)
        return True

    def list(self, path: JulesPath) -> List[str]:
        remote_path = self._get_remote_path(path)
        payload = {
            "fs": self.remote_name,
            "remote": remote_path,
            "opt": {"recurse": False}
        }
        result = self._execute_rc("operations/list", payload=payload, retries=3)
        return [item.get("Path", "") for item in result.get("list", [])]

    def stats(self, remote: str) -> Dict[str, Any]:
        """Provides provider-reported quota and stats per the contract."""
        payload = {"fs": remote}
        try:
            return self._execute_rc("operations/about", payload=payload, retries=3)
        except GatewayError:
            # Fallback to core/stats if operations/about is not supported by the remote
            return self._execute_rc("core/stats", retries=3)
