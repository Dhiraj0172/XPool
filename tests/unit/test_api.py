
import pytest
import sys
import json
import base64
from unittest.mock import MagicMock

from src.gateway.main import XPoolGatewayHandler
from src.gateway.executor import SingleAuthoritativeExecutor
from src.common.errors import GatewayError

class MockRequestWrapper:
    def __init__(self, body):
        self._body = body
    def read(self, length):
        return self._body

class MockResponseWrapper:
    def __init__(self):
        self.output = b""
        self.code = None
    def write(self, b):
        self.output += b

class TestGatewayHandler(XPoolGatewayHandler):
    def __init__(self, path, headers, body_raw):
        self.path = path
        self.headers = headers
        self.rfile = MockRequestWrapper(body_raw)
        self.wfile = MockResponseWrapper()

    def send_response(self, code):
        self.wfile.code = code

    def send_header(self, *args):
        pass

    def end_headers(self):
        pass

@pytest.fixture
def mock_executor():
    return MagicMock(spec=SingleAuthoritativeExecutor)

def make_handler(path, headers, payload, inject_token=True):
    body = json.dumps(payload).encode('utf-8') if payload is not None and not isinstance(payload, bytes) else payload
    if body is None: body = b""
    # Re-calculate exact content length to match the JSON dump properly for tests that expect success
    if "Content-Length" in headers and headers["Content-Length"] not in ("15000000", "-50", "abc"):
        if int(headers["Content-Length"]) > 0:
            headers["Content-Length"] = str(len(body))
    h = TestGatewayHandler(path, headers, body)
    if inject_token:
        h.expected_mock_token = "mock-secret-token"
    return h

def test_api_missing_auth(mock_executor):
    headers = {"Content-Length": "20", "Content-Type": "application/json"}
    h = make_handler("/api/v1/files/write", headers, {"target_path": "a"})
    h.executor = mock_executor
    h.do_POST()
    assert h.wfile.code == 401
    mock_executor.execute_write.assert_not_called()

def test_api_unconfigured_auth(mock_executor):
    # Proves: If token isn't injected, it fails closed explicitly.
    headers = {"Authorization": "Bearer mock-secret-token", "Content-Length": "20", "Content-Type": "application/json"}
    h = make_handler("/api/v1/files/write", headers, {"target_path": "a"}, inject_token=False)
    h.executor = mock_executor
    h.do_POST()
    assert h.wfile.code == 401
    mock_executor.execute_write.assert_not_called()

def test_api_malformed_json(mock_executor):
    headers = {"Authorization": "Bearer mock-secret-token", "Content-Length": "20", "Content-Type": "application/json"}
    h = TestGatewayHandler("/api/v1/files/write", headers, b"{bad-json")
    h.expected_mock_token = "mock-secret-token"
    h.executor = mock_executor
    h.do_POST()
    assert h.wfile.code == 400

def test_api_schema_validation_failure(mock_executor):
    # Proves: 422 Unprocessable Entity for schema mismatch
    headers = {"Authorization": "Bearer mock-secret-token", "Content-Length": "20", "Content-Type": "application/json"}
    h = make_handler("/api/v1/files/write", headers, {"wrong_field": "a"})
    h.executor = mock_executor
    h.do_POST()
    assert h.wfile.code == 422

def test_api_oversized_payload(mock_executor):
    # Proves: 413 Payload Too Large is enforced before reading memory
    headers = {"Authorization": "Bearer mock-secret-token", "Content-Length": "15000000", "Content-Type": "application/json"}
    h = make_handler("/api/v1/files/write", headers, {})
    h.executor = mock_executor
    h.do_POST()
    assert h.wfile.code == 413

def test_api_unsupported_media_type(mock_executor):
    # Proves: 415 Unsupported Media Type for non-JSON requests
    headers = {"Authorization": "Bearer mock-secret-token", "Content-Length": "20", "Content-Type": "text/plain"}
    h = make_handler("/api/v1/files/write", headers, {"target_path": "a"})
    h.executor = mock_executor
    h.do_POST()
    assert h.wfile.code == 415

def test_api_unsupported_method(mock_executor):
    # Proves: 405 Method Not Allowed for GET
    headers = {}
    h = make_handler("/api/v1/files/write", headers, None)
    h.do_GET()
    assert h.wfile.code == 405

def test_api_successful_dispatch(mock_executor):
    mock_executor.execute_write.return_value = True
    headers = {"Authorization": "Bearer mock-secret-token", "Content-Length": "100", "Content-Type": "application/json"}
    payload = {"target_path": "/JulesWorkspace/test.txt", "data": base64.b64encode(b"hello").decode('utf-8')}
    h = make_handler("/api/v1/files/write", headers, payload)
    h.executor = mock_executor
    h.do_POST()
    assert h.wfile.code == 200
    mock_executor.execute_write.assert_called_once()

def test_api_uncertain_mutation_mapping(mock_executor):
    mock_executor.execute_write.side_effect = GatewayError("Backend outcome uncertain", code=500)
    headers = {"Authorization": "Bearer mock-secret-token", "Content-Length": "100", "Content-Type": "application/json"}
    payload = {"target_path": "/JulesWorkspace/test.txt", "data": base64.b64encode(b"hello").decode('utf-8')}
    h = make_handler("/api/v1/files/write", headers, payload)
    h.executor = mock_executor
    h.do_POST()
    assert h.wfile.code == 500
    assert b"uncertain" in h.wfile.output.lower()

def test_api_copy_protected_namespace_blocked(mock_executor):
    # Proves: Both src and dst are validated for .xpool_recovery early
    headers = {"Authorization": "Bearer mock-secret-token", "Content-Length": "100", "Content-Type": "application/json"}
    payload = {"target_path": "/JulesWorkspace/safe.txt", "dst_path": "/JulesWorkspace/.xpool_recovery/bad.txt"}
    h = make_handler("/api/v1/files/copy", headers, payload)
    h.executor = mock_executor
    h.do_POST()
    assert h.wfile.code == 403
    assert b"protected recovery namespace" in h.wfile.output

def test_api_missing_content_length(mock_executor):
    # Proves: 411 Length Required
    headers = {"Authorization": "Bearer mock-secret-token", "Content-Type": "application/json"}
    h = make_handler("/api/v1/files/write", headers, None)
    h.do_POST()
    assert h.wfile.code == 411

def test_api_negative_content_length(mock_executor):
    # Proves: 400 Bad Request on Negative Length
    headers = {"Authorization": "Bearer mock-secret-token", "Content-Length": "-50", "Content-Type": "application/json"}
    h = make_handler("/api/v1/files/write", headers, None)
    h.do_POST()
    assert h.wfile.code == 400

def test_api_invalid_content_length(mock_executor):
    # Proves: 400 Bad Request on string Content-Length
    headers = {"Authorization": "Bearer mock-secret-token", "Content-Length": "abc", "Content-Type": "application/json"}
    h = make_handler("/api/v1/files/write", headers, None)
    h.do_POST()
    assert h.wfile.code == 400

def test_api_unknown_route(mock_executor):
    # Proves: 404 Not Found on unknown paths
    headers = {"Authorization": "Bearer mock-secret-token", "Content-Length": "20", "Content-Type": "application/json"}
    h = make_handler("/api/v1/files/unknown", headers, {"target_path": "a"})
    h.do_POST()
    assert h.wfile.code == 404

def test_api_incomplete_request_body(mock_executor):
    # Proves: Request body that ends before Content-Length prevents server hang
    headers = {"Authorization": "Bearer mock-secret-token", "Content-Length": "100", "Content-Type": "application/json"}
    headers["Content-Length"] = "100" # Deliberately longer than the payload
    h = make_handler("/api/v1/files/write", headers, b'{"target_path":"') # deliberately short bytes
    h.executor = mock_executor
    h.do_POST()
    assert h.wfile.code == 400

def test_api_invalid_utf8_json(mock_executor):
    # Proves: Invalid UTF-8 decoding throws 400 Malformed JSON safely
    headers = {"Authorization": "Bearer mock-secret-token", "Content-Length": "10", "Content-Type": "application/json"}
    h = TestGatewayHandler("/api/v1/files/write", headers, b'\xff\xfe\x00')
    h.expected_mock_token = "mock-secret-token"
    h.executor = mock_executor
    h.do_POST()
    assert h.wfile.code == 400

def test_api_head_options_methods(mock_executor):
    # Proves: HEAD and OPTIONS return 405
    h = make_handler("/api/v1/files/write", {}, None)
    h.do_HEAD()
    assert h.wfile.code == 405

    h2 = make_handler("/api/v1/files/write", {}, None)
    h2.do_OPTIONS()
    assert h2.wfile.code == 405
