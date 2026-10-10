from typing import Any, Dict, Optional, Literal
from pydantic import BaseModel, Field

class BaseResponse(BaseModel):
    """Standard success response schema."""
    status: Literal["ok"] = "ok"
    data: Optional[Any] = None

class ErrorResponse(BaseModel):
    """Standard error response schema."""
    status: Literal["error"] = "error"
    code: int
    message: str

    # Error responses must not leak sensitive paths or credentials
    class Config:
        extra = "forbid"

class OperationRequest(BaseModel):
    """Base schema for standard storage operations."""
    target_path: str = Field(..., description="Target logical path for the operation")

class WriteRequest(OperationRequest):
    data: str = Field(..., description="Base64 encoded payload data")

class QuotaState(BaseModel):
    """Represents the safety state of backend capacity."""
    status: Literal["UNKNOWN", "VERIFIED", "EXHAUSTED"] = "UNKNOWN"
    total_bytes: Optional[int] = None
    free_bytes: Optional[int] = None

class GatewayConfig(BaseModel):
    """Validated configuration structure for the gateway."""
    bind_host: str = "127.0.0.1"
    bind_port: int = 8080
    jules_zone_root: str
    # Fail closed on missing/invalid security settings
    require_auth: bool = True
