import pytest
import respx
import httpx
from src.storage.rclone_adapter import RcloneRCAdapter
from src.common.types import JulesPath
from src.common.errors import GatewayError, BackendQuotaError

import sys

@pytest.fixture
def adapter():
    # Use a dummy root path appropriate for the OS running the test
    if sys.platform == "win32":
        root = "C:/JulesWorkspace"
    else:
        root = "/JulesWorkspace"
    return RcloneRCAdapter(rc_url="http://localhost:5572", remote_name="local_mock:", jules_zone_root=root)

@respx.mock
def test_execute_rc_success(adapter):
    """Verify base HTTP wrapper handles success schemas correctly."""
    request = respx.post("http://localhost:5572/core/version").respond(
        status_code=200, json={"version": "v1.64.0"}
    )
    result = adapter._execute_rc("core/version")
    assert result["version"] == "v1.64.0"
    assert request.called

@respx.mock
def test_execute_rc_quota_failure(adapter):
    """Verify backend quota exhaustion translates safely without leaking auth."""
    # Rclone returns 403 or specific string in body for quotas on drive
    respx.post("http://localhost:5572/operations/uploadfile").respond(
        status_code=403, json={"error": "quota exceeded"}
    )
    with pytest.raises(BackendQuotaError) as exc:
        adapter._execute_rc("operations/uploadfile", {"fs": "test"})
    assert "Backend Quota Exceeded" in str(exc.value)
    assert exc.value.code == 429
    assert exc.value.safe_message == "Quota Exceeded"

@respx.mock
def test_execute_rc_network_failure(adapter):
    """Verify connection timeouts result in secure 502 representations."""
    respx.post("http://localhost:5572/core/stats").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )
    with pytest.raises(GatewayError) as exc:
        adapter._execute_rc("core/stats")
    assert exc.value.code == 502
    assert exc.value.safe_message == "Internal Server Error"

def test_remote_path_mapping(adapter):
    """Ensure adapter safely relativizes absolute paths and prevents escapes."""
    import sys
    if sys.platform == "win32":
        path = JulesPath("C:\\JulesWorkspace\\folder\\test.txt")
    else:
        path = JulesPath("/JulesWorkspace/folder/test.txt")

    rel = adapter._get_remote_path(path)
    assert rel == "folder/test.txt"

    # Assert traversal escape is strictly blocked
    if sys.platform == "win32":
        bad_path = JulesPath("C:\\JulesWorkspace\\..\\Windows\\System32")
        root_path = JulesPath("C:\\JulesWorkspace")
    else:
        bad_path = JulesPath("/JulesWorkspace/../etc/passwd")
        root_path = JulesPath("/JulesWorkspace")

    with pytest.raises(GatewayError) as exc:
        adapter._get_remote_path(bad_path)
    assert exc.value.code == 403

    # Assert root zone protection is strictly blocked
    with pytest.raises(GatewayError) as exc:
        adapter._get_remote_path(root_path)
    assert exc.value.code == 403

@respx.mock
def test_hash_success(adapter):
    import sys
    base = "C:/JulesWorkspace" if sys.platform == "win32" else "/JulesWorkspace"
    path = JulesPath(f"{base}/valid/path.txt")
    request1 = respx.post("http://localhost:5572/operations/hashsumfile").respond(
        status_code=200, json={"hash": "abcdef123"}
    )
    result = adapter.hash(path)
    assert result == "abcdef123"
    assert request1.called

@respx.mock
def test_hash_not_found(adapter):
    import sys
    base = "C:/JulesWorkspace" if sys.platform == "win32" else "/JulesWorkspace"
    path = JulesPath(f"{base}/missing/path.txt")
    request1 = respx.post("http://localhost:5572/operations/hashsumfile").respond(
        status_code=404, json={"error": "file not found"}
    )
    import pytest
    with pytest.raises(FileNotFoundError):
        adapter.hash(path)
    assert request1.called

@respx.mock
def test_stats_fallback(adapter):
    # Test fallback from about to stats
    respx.post("http://localhost:5572/operations/about").respond(
        status_code=500, json={"error": "not supported"}
    )
    respx.post("http://localhost:5572/core/stats").respond(
        status_code=200, json={"bytes": 1024}
    )
    res = adapter.stats("local_mock:")
    assert res["bytes"] == 1024

@respx.mock
def test_copy_move(adapter):
    import sys
    base = "C:/JulesWorkspace" if sys.platform == "win32" else "/JulesWorkspace"
    src = JulesPath(f"{base}/src.txt")
    dst = JulesPath(f"{base}/dst.txt")

    req_copy = respx.post("http://localhost:5572/operations/copyfile").respond(status_code=200, json={})
    req_move = respx.post("http://localhost:5572/operations/movefile").respond(status_code=200, json={})

    assert adapter.copy(src, dst)
    assert adapter.move(src, dst)
    assert req_copy.called
    assert req_move.called

    # Verify move does NOT have retries enabled due to idempotency issues
    req_move.mock(side_effect=httpx.RequestError("Network glitch"))
    with pytest.raises(GatewayError):
        adapter.move(src, dst)
    # the route was called once initially successfully, and once failing just now. So call_count is 2 total.
    assert req_move.call_count == 2

@respx.mock
def test_retry_logic(adapter):
    """Test that transient network errors trigger retries."""
    import sys
    base = "C:/JulesWorkspace" if sys.platform == "win32" else "/JulesWorkspace"
    path = JulesPath(f"{base}/file.txt")

    # Fail 2 times, succeed on the 3rd
    route = respx.post("http://localhost:5572/operations/deletefile")
    route.side_effect = [
        httpx.RequestError("Network glitch"),
        httpx.RequestError("Network glitch"),
        httpx.Response(200, json={})
    ]

    assert adapter.delete(path) is True
    assert route.call_count == 3

@respx.mock
def test_write_quota_exhausted(adapter):
    import sys
    base = "C:/JulesWorkspace" if sys.platform == "win32" else "/JulesWorkspace"
    path = JulesPath(f"{base}/exhausted/path.txt")
    request = respx.post("http://localhost:5572/operations/uploadfile").respond(
        status_code=403, json={"error": "quota exceeded"}
    )
    with pytest.raises(BackendQuotaError):
        adapter.write(path, b"data")
    assert request.called

@respx.mock
def test_delete_idempotent(adapter):
    import sys
    base = "C:/JulesWorkspace" if sys.platform == "win32" else "/JulesWorkspace"
    path = JulesPath(f"{base}/missing/path.txt")
    # Simulate rclone returning not found on a delete request
    request = respx.post("http://localhost:5572/operations/deletefile").respond(
        status_code=500, json={"error": "object not found"}
    )
    # The adapter should swallow the 404/not found as success for idempotency
    assert adapter.delete(path) is True
    assert request.called
