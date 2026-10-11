import json
import logging
import uuid
import base64
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

from src.common.types import JulesPath, Principal
from src.common.schemas import WriteRequest, OperationRequest, CopyRequest, MoveRequest, BaseResponse, ErrorResponse
from src.common.errors import GatewayError, AuthorizationError, BackupVerificationError, BackendQuotaError
from src.gateway.executor import SingleAuthoritativeExecutor
from src.gateway.state import OpState

logger = logging.getLogger(__name__)

class XPoolGatewayHandler(BaseHTTPRequestHandler):
    """
    Minimal, offline-testable HTTP Gateway Router.
    Dependency injected via class attributes before server start.
    """
    executor: SingleAuthoritativeExecutor = None
    expected_mock_token: str = None

    def _send_json_response(self, code: int, payload: dict):
        self.send_response(code)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode('utf-8'))

    def _send_error(self, code: int, safe_message: str):
        err = ErrorResponse(code=code, message=safe_message)
        self._send_json_response(code, err.model_dump())

    def _authenticate(self) -> Principal:
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise AuthorizationError("Missing or invalid authorization header")

        token = auth_header.split(" ")[1]

        # In a real environment, this must call a trusted identity provider.
        # Since production integration is UNAUTHORIZED_PENDING_APPROVAL, we strictly fail closed
        # unless a specific mock token was injected during isolated offline testing.
        if self.expected_mock_token is None:
            # Trusted Authentication is NOT_IMPLEMENTED for production. Fail closed natively.
            raise AuthorizationError("Trusted Identity Provider not configured")

        if token != self.expected_mock_token:
            raise AuthorizationError("Invalid token")

        return Principal(token_id="user-principal-1")

    def _handle_api_request(self):
        # Prevent Slowloris/slow-body thread exhaustion DoS
        if hasattr(self, 'connection'):
            self.connection.settimeout(30.0)
        try:
            # 1. Trusted Authentication Boundary
            principal = self._authenticate()

            # 2. Strict Request Parsing & Schema Validation
            cl_header = self.headers.get('Content-Length')
            if not cl_header:
                self._send_error(411, "Length Required")
                return
            try:
                content_length = int(cl_header)
            except ValueError:
                self._send_error(400, "Invalid Content-Length")
                return
            if content_length < 0:
                self._send_error(400, "Negative Content-Length")
                return
            content_type = self.headers.get('Content-Type', '')
            if 'application/json' not in content_type:
                self._send_error(415, "Unsupported Media Type")
                return

            if content_length > 10 * 1024 * 1024:  # Bounded Request Size (10MB arbitrary for mock API)
                self._send_error(413, "Payload Too Large")
                return

            body = self.rfile.read(content_length)
            if len(body) != content_length:
                self._send_error(400, "Incomplete request body")
                return
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                self._send_error(400, "Malformed JSON")
                return

            parsed_url = urlparse(self.path)
            idempotency_key = self.headers.get("X-Idempotency-Key", str(uuid.uuid4()))

            # 3. Route Dispatch
            if parsed_url.path == "/api/v1/files/write":
                from pydantic import ValidationError
                try:
                    req = WriteRequest(**payload)
                except ValidationError:
                    self._send_error(422, "Unprocessable Entity (Schema Validation Failed)")
                    return
                target = JulesPath(req.target_path)
                data = base64.b64decode(req.data) # Simple bounded mock payload

                success = self.executor.execute_write(idempotency_key, target, data, principal.token_id)
                self._send_json_response(200, BaseResponse(data={"success": success}).model_dump())

            elif parsed_url.path == "/api/v1/files/delete":
                from pydantic import ValidationError
                try:
                    req = OperationRequest(**payload)
                except ValidationError:
                    self._send_error(422, "Unprocessable Entity (Schema Validation Failed)")
                    return
                # Canonicalization enforces protection before NotImplemented
                target = JulesPath(req.target_path)
                self._send_error(501, "Not Implemented")

            elif parsed_url.path in ("/api/v1/files/copy", "/api/v1/files/move"):
                from pydantic import ValidationError
                try:
                    if parsed_url.path == "/api/v1/files/copy":
                        req = CopyRequest(**payload)
                    else:
                        req = MoveRequest(**payload)
                except ValidationError:
                    self._send_error(422, "Unprocessable Entity (Schema Validation Failed)")
                    return
                # Enforce protection on BOTH source and destination paths before failing 501
                src = JulesPath(req.target_path)
                dst = JulesPath(req.dst_path)

                # Check for protected namespace explicitly if it somehow bypassed canonicalization block
                # (though _get_remote_path inside executor handles it, doing it early here is defense in depth)
                if ".xpool_recovery" in src.canonical_path.parts or ".xpool_recovery" in dst.canonical_path.parts:
                    self._send_error(403, "Cannot target protected recovery namespace")
                    return

                self._send_error(501, "Not Implemented")

            else:
                self._send_error(404, "Unknown operation")

        except AuthorizationError:
            self._send_error(401, "Unauthorized")
        except GatewayError as e:
            code = e.code if hasattr(e, 'code') else 500
            # If the operation state is uncertain, map to 500/504
            if "uncertain" in str(e).lower():
                self._send_error(500, "Backend operation outcome uncertain")
            else:
                self._send_error(code, e.safe_message if hasattr(e, 'safe_message') else "Gateway Error")
        except Exception as e:
            # Prevent data leakage by ensuring raw exception strings containing backend paths or
            # tokens are not blindly serialized to logs if they originated from untrusted components.
            # (Though in our case, GatewayError is explicitly designed with `safe_message`).
            logger.error("Unhandled server error processing request.")
            self._send_error(500, "Internal Server Error")

    def do_POST(self):
        self._handle_api_request()

    def do_PUT(self):
        self._handle_api_request()


    def do_GET(self):
        self._send_error(405, "Method Not Allowed")
    def do_DELETE(self):
        self._send_error(405, "Method Not Allowed")
    def do_PATCH(self):
        self._send_error(405, "Method Not Allowed")
    def do_HEAD(self):
        self._send_error(405, "Method Not Allowed")
    def do_OPTIONS(self):
        self._send_error(405, "Method Not Allowed")
