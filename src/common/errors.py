class GatewayError(Exception):
    """Base exception for all internal gateway errors."""
    def __init__(self, message: str, code: int = 500):
        super().__init__(message)
        self.code = code
        self.safe_message = "Internal Server Error"

class AuthorizationError(GatewayError):
    """Raised when JULES_ZONE bounds or identity checks fail."""
    def __init__(self, message: str = "Permission Denied"):
        super().__init__(message, code=403)
        self.safe_message = "Forbidden"

class BackupVerificationError(GatewayError):
    """Raised when a pre-mutation backup fails integrity checks."""
    def __init__(self, message: str = "Backup integrity verification failed"):
        super().__init__(message, code=500)
        self.safe_message = "Internal Storage Guard Triggered"

class BackendQuotaError(GatewayError):
    """Raised when the underlying storage returns quota exhaustion."""
    def __init__(self, message: str = "Storage quota exceeded"):
        super().__init__(message, code=429)
        self.safe_message = "Quota Exceeded"
