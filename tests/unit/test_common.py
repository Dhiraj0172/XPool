import pytest
import pathlib
from src.common.types import JulesPath, Principal
from src.common.schemas import GatewayConfig, QuotaState, BaseResponse, ErrorResponse
from src.common.errors import AuthorizationError, BackendQuotaError
from pydantic import ValidationError

def test_jules_path_canonicalization():
    """Verify that JulesPath inherently resolves traversal attacks safely."""
    path = JulesPath(raw_path="/fake/root/../test.txt")
    # Resolution eliminates the ../ traversal
    assert str(path.canonical_path) == str(pathlib.Path("/fake/test.txt").resolve())

def test_principal_defaults():
    p = Principal(token_id="user123")
    assert p.is_admin is False

def test_config_validation_success():
    config = GatewayConfig(bind_host="0.0.0.0", bind_port=9000, jules_zone_root="/mnt/xpool")
    assert config.jules_zone_root == "/mnt/xpool"
    assert config.require_auth is True

def test_config_validation_failure():
    # Missing required field `jules_zone_root` should fail
    with pytest.raises(ValidationError):
        GatewayConfig(bind_port=8080)

def test_quota_state_unknown_by_default():
    """Ensure QuotaState fails closed to UNKNOWN, preventing false capacity reports."""
    state = QuotaState()
    assert state.status == "UNKNOWN"
    assert state.total_bytes is None

def test_error_schema_forbids_extra_fields():
    """Ensure ErrorResponse cannot accidentally serialize secret kwargs."""
    with pytest.raises(ValidationError):
        ErrorResponse(code=500, message="Fail", internal_secret_token="abc1234")

def test_error_safe_messages():
    """Verify exceptions expose safe messages instead of raw internal tracebacks."""
    err = AuthorizationError("Detailed path: /mnt/secret/x")
    assert err.code == 403
    assert err.safe_message == "Forbidden"

    quota_err = BackendQuotaError("Provider raw error: 403 quota exceeded")
    assert quota_err.code == 429
    assert quota_err.safe_message == "Quota Exceeded"
