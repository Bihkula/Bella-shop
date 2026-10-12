"""Password hashing and JWT helpers (no web-framework imports)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass

import jwt

PBKDF2_ITERATIONS = 600_000  # OWASP 2023+ guidance for PBKDF2-HMAC-SHA256
_ALGO = "pbkdf2_sha256"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str, *, iterations: int | None = None) -> str:
    if not password:
        raise ValueError("password must not be empty")
    if iterations is None:
        # Tests lower this via env; never lower it in production.
        iterations = int(os.getenv("PASSWORD_HASH_ITERATIONS", PBKDF2_ITERATIONS))
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"{_ALGO}${iterations}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, iterations, salt, digest = encoded.split("$")
        if algo != _ALGO:
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), _unb64(salt), int(iterations)
        )
        return hmac.compare_digest(candidate, _unb64(digest))
    except (ValueError, TypeError):
        return False


@dataclass(frozen=True)
class Principal:
    user_id: int
    email: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class TokenError(Exception):
    pass


def create_access_token(
    principal: Principal,
    *,
    secret: str,
    issuer: str,
    audience: str,
    ttl_seconds: int,
    now: int | None = None,
) -> str:
    issued = int(now if now is not None else time.time())
    claims = {
        "sub": str(principal.user_id),
        "email": principal.email,
        "role": principal.role,
        "iss": issuer,
        "aud": audience,
        "iat": issued,
        "exp": issued + ttl_seconds,
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(claims, secret, algorithm="HS256")


def decode_access_token(token: str, *, secret: str, issuer: str, audience: str) -> Principal:
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            issuer=issuer,
            audience=audience,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    return Principal(
        user_id=int(claims["sub"]),
        email=claims.get("email", ""),
        role=claims.get("role", "customer"),
    )
