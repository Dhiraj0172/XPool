"""XPool Storage Access Gateway Client SDK & CLI.
Provides authenticated access to the XPool Gateway across both local loopback
and secure outbound reverse tunnels (Cloudflare / Ngrok).
Supports all live v1 endpoints: health, list, read, write, delete, restore, and approve.
Includes automatic live tunnel URL discovery from CURRENT_TUNNEL_URL.json on NXDOMAIN.
"""

import os
import sys
import json
import base64
import re
import argparse
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple


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

    # 1. Search from repo root
    repo_root = find_repo_root()
    if repo_root:
        candidates.append(repo_root / "CURRENT_TUNNEL_URL.json")

    # 2. Check current working directory
    candidates.append(Path.cwd() / "CURRENT_TUNNEL_URL.json")

    # 3. Check staging / standard paths
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


class XPoolClient:
    """Official Python Client for XPool + Jules Storage Gateway."""
    def __init__(self, base_url: Optional[str] = None, token: Optional[str] = None):
        self.base_url = resolve_default_gateway_url(base_url)
        self.token = token or os.environ.get("XPOOL_GATEWAY_TOKEN", DEFAULT_TOKEN)

    def _request(
        self,
        method: str,
        endpoint: str,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
        retried_after_failover: bool = False
    ) -> Dict[str, Any]:
        """Executes an authenticated JSON HTTP request against the gateway with auto-failover on NXDOMAIN."""
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
            err_body = e.read().decode("utf-8", errors="replace")
            clean_err = sanitize_text(err_body)
            try:
                parsed = json.loads(err_body)
                msg = parsed.get("detail") or parsed.get("error") or clean_err
            except Exception:
                msg = clean_err
            raise RuntimeError(f"Gateway HTTP {e.code} Error on {endpoint}: {msg}")
        except urllib.error.URLError as e:
            reason_str = str(e.reason).lower()
            is_nxdomain = any(term in reason_str for term in [
                "getaddrinfo failed",
                "not known",
                "could not be resolved",
                "11001",
                "nodename nor servname provided"
            ])
            # Automatic NXDOMAIN fallback: reload live tunnel URL from repository CURRENT_TUNNEL_URL.json
            if is_nxdomain and not retried_after_failover:
                fresh_url = read_tunnel_url_file()
                if fresh_url and fresh_url != self.base_url:
                    print(
                        f"[XPoolClient] Notice: Gateway '{self.base_url}' returned NXDOMAIN. "
                        f"Auto-failing over to live URL from CURRENT_TUNNEL_URL.json: '{fresh_url}'",
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
            clean_reason = sanitize_text(str(e.reason))
            raise RuntimeError(f"Gateway Connection Error on {endpoint}: {clean_reason}")

    def health(self) -> Dict[str, Any]:
        """Queries /api/v1/health endpoint."""
        return self._request("GET", "/api/v1/health")

    def list(self, path: str = "/") -> Dict[str, Any]:
        """Lists directory contents via /api/v1/list."""
        return self._request("POST", "/api/v1/list", json_body={"path": path})

    def read(self, path: str) -> Dict[str, Any]:
        """Reads file contents via /api/v1/read."""
        return self._request("POST", "/api/v1/read", json_body={"path": path})

    def write(self, path: str, content: str, is_base64: bool = False) -> Dict[str, Any]:
        """Writes or overwrites a file via /api/v1/write under fail-closed protection."""
        return self._request("POST", "/api/v1/write", json_body={
            "path": path,
            "content": content,
            "is_base64": is_base64
        })

    def delete(self, path: str) -> Dict[str, Any]:
        """Deletes a file via /api/v1/delete with synchronous pre-delete backup."""
        return self._request("POST", "/api/v1/delete", json_body={"path": path})

    def restore(self, version_id: str, target_path: Optional[str] = None) -> Dict[str, Any]:
        """Restores a version from the protected CAS vault via /api/v1/restore."""
        payload: Dict[str, Any] = {"version_id": version_id}
        if target_path:
            payload["target_path"] = target_path
        return self._request("POST", "/api/v1/restore", json_body=payload)

    def approve(self, approval_id: str, decision: str = "APPROVED") -> Dict[str, Any]:
        """Resolves an owner approval request via /api/v1/approve."""
        return self._request("POST", "/api/v1/approve", json_body={
            "approval_id": approval_id,
            "decision": decision
        })


def main():
    parser = argparse.ArgumentParser(description="XPool Storage Access Gateway Client CLI")
    parser.add_argument("--url", default=None, help="Gateway base URL (default: $XPOOL_GATEWAY_URL or CURRENT_TUNNEL_URL.json)")
    parser.add_argument("--token", default=None, help="Bearer authorization token (default: $XPOOL_GATEWAY_TOKEN)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # health
    subparsers.add_parser("health", help="Check gateway service health")

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
    client = XPoolClient(base_url=args.url, token=args.token)

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
