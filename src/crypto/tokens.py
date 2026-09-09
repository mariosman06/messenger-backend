"""Opaque token generation and hashing."""

import hashlib
import secrets


def generate_raw_token(nbytes: int = 32) -> str:
    """Generate a cryptographically secure random token string."""
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """Hash a raw token string using SHA-256 for secure database storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
