"""Password hashing, verification, and re-hash checking.

All operations are offloaded to a dedicated asynchronous thread worker pool
to prevent blocking Uvicorn's event loop and control CPU saturation during
CPU-heavy Argon2 operations.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_ph = PasswordHasher(time_cost=1, memory_cost=19456, parallelism=1)

hash_pool = ThreadPoolExecutor(max_workers=2)


async def hash_password(password: str) -> str:
    """Hash a plain-text password using Argon2id asynchronously."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(hash_pool, _ph.hash, password)


async def verify_password(password: str, hashed_password: str) -> bool:
    """Verify a plain-text password against an Argon2 hash asynchronously."""
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(hash_pool, _ph.verify, hashed_password, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


async def needs_rehash(hashed_password: str) -> bool:
    """Check if an Argon2 hash needs to be re-hashed due to outdated parameters."""
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(hash_pool, _ph.check_needs_rehash, hashed_password)
    except InvalidHashError:
        return False
