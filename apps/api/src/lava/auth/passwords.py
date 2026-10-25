"""Argon2id passwords with equal-cost verification for unknown identities."""

import secrets

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

PASSWORD_HASHER = PasswordHasher(
    time_cost=3, memory_cost=65536, parallelism=2, hash_len=32, salt_len=16, type=Type.ID
)
DUMMY_HASH = PASSWORD_HASHER.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    if not 12 <= len(password) <= 1024:
        raise ValueError("Password must contain between 12 and 1024 characters")
    return PASSWORD_HASHER.hash(password)


def verify_password(password: str, encoded: str | None) -> bool:
    try:
        valid = PASSWORD_HASHER.verify(encoded or DUMMY_HASH, password)
    except (InvalidHashError, VerificationError):
        return False
    return valid and encoded is not None
