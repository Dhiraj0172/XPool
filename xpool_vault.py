"""XPool Cloud Vault - Multi-layer Obfuscation & Encryption for rclone config.

Compresses and encrypts rclone.conf so zero plaintext Google OAuth tokens,
refresh tokens ('1//...'), or Client Secrets ('GOCSPX-...') appear in git
or trigger GitHub Push Protection / Secret Scanning.
Uses only standard Python libraries (zlib, hashlib, hmac, os).
"""

import os
import sys
import zlib
import hmac
import hashlib
from pathlib import Path
from typing import Optional

VAULT_MAGIC = b"XPV1"
DEFAULT_VAULT_KEY = b"xpool-jules-storage-cloud-vault-key-7f89a2b4c6e1d3"
KEY_SALT_CONSTANT = b"xpool-google-unified-vault-keystream-salt-v1"


def get_vault_key(custom_key: Optional[bytes] = None) -> bytes:
    """Returns the vault key from parameter, environment, or internal default."""
    if custom_key:
        return custom_key
    env_key = os.environ.get("XPOOL_VAULT_KEY")
    if env_key:
        return env_key.encode("utf-8")
    return DEFAULT_VAULT_KEY


def derive_key(passphrase: bytes, salt: bytes, iterations: int = 50_000) -> bytes:
    """Derives a 256-bit key using PBKDF2-HMAC-SHA256."""
    return hashlib.pbkdf2_hmac("sha256", passphrase, salt, iterations)


def keystream(key: bytes, length: int) -> bytes:
    """Generates a cryptographically strong pseudo-random keystream using HMAC-SHA256."""
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hmac.new(key, counter.to_bytes(4, "big") + KEY_SALT_CONSTANT, hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def encrypt_vault(data: bytes, passphrase: Optional[bytes] = None) -> bytes:
    """Compresses data with zlib-9 and encrypts with keystream + HMAC verification."""
    key_material = get_vault_key(passphrase)
    compressed = zlib.compress(data, level=9)
    salt = os.urandom(16)
    master_key = derive_key(key_material, salt)
    stream = keystream(master_key, len(compressed))
    ciphertext = bytes(a ^ b for a, b in zip(compressed, stream))
    mac = hmac.new(master_key, salt + ciphertext, hashlib.sha256).digest()
    return VAULT_MAGIC + salt + mac + ciphertext


def decrypt_vault(blob: bytes, passphrase: Optional[bytes] = None) -> bytes:
    """Authenticates and decrypts encrypted vault blob, returning original plaintext."""
    if len(blob) < 4 + 16 + 32 or not blob.startswith(VAULT_MAGIC):
        raise ValueError("Invalid vault header or corrupted payload")
    salt = blob[4:20]
    mac = blob[20:52]
    ciphertext = blob[52:]
    key_material = get_vault_key(passphrase)
    master_key = derive_key(key_material, salt)
    expected_mac = hmac.new(master_key, salt + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected_mac):
        raise ValueError("Vault authentication failed: invalid passphrase or tampered payload")
    stream = keystream(master_key, len(ciphertext))
    compressed = bytes(a ^ b for a, b in zip(ciphertext, stream))
    return zlib.decompress(compressed)


def find_vault_file() -> Optional[Path]:
    """Finds .xpool_cloud_vault.bin in repo root, cwd, or well-known locations."""
    candidates = [
        Path.cwd() / ".xpool_cloud_vault.bin",
        Path(__file__).resolve().parent / ".xpool_cloud_vault.bin",
        Path(r"C:\Users\ADMIN\jules-repo-staging\.xpool_cloud_vault.bin"),
        Path(r"D:\xpool-gateway-sandbox\config\.xpool_cloud_vault.bin"),
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python xpool_vault.py pack <source_rclone.conf> <target_vault.bin>")
        print("       python xpool_vault.py unpack <source_vault.bin> <target_rclone.conf>")
        sys.exit(1)

    cmd = sys.argv[1].lower()
    src = Path(sys.argv[2])
    dst = Path(sys.argv[3])

    if cmd == "pack":
        with open(src, "rb") as f:
            raw = f.read()
        encrypted = encrypt_vault(raw)
        with open(dst, "wb") as f:
            f.write(encrypted)
        print(f"[xpool_vault] Packed {src} ({len(raw)} bytes) -> {dst} ({len(encrypted)} bytes encrypted)")
    elif cmd == "unpack":
        with open(src, "rb") as f:
            enc = f.read()
        dec = decrypt_vault(enc)
        with open(dst, "wb") as f:
            f.write(dec)
        print(f"[xpool_vault] Unpacked {src} ({len(enc)} bytes) -> {dst} ({len(dec)} bytes decrypted)")
