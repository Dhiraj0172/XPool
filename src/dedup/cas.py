import hashlib

def calculate_sha256(content: bytes) -> str:
    """Calculates the SHA-256 hash of the given byte content."""
    sha256_hash = hashlib.sha256()
    sha256_hash.update(content)
    return sha256_hash.hexdigest()
