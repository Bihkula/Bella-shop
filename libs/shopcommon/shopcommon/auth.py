"""FastAPI dependencies for authenticating users and internal callers."""

from __future__ import annotations

import hmac

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import get_settings
from .security import Principal, TokenError, decode_access_token

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Principal:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    s = get_settings()
    try:
        return decode_access_token(
            creds.credentials, secret=s.jwt_secret, issuer=s.jwt_issuer, audience=s.jwt_audience
        )
    except TokenError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def require_admin(user: Principal = Depends(get_current_user)) -> Principal:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")
    return user


def require_internal(x_internal_token: str | None = Header(default=None)) -> None:
    """Service-to-service calls carry a shared token. Endpoints guarded by this
    are also blocked at the edge (nginx/Ingress) and by NetworkPolicy."""
    expected = get_settings().internal_token
    if not x_internal_token or not hmac.compare_digest(x_internal_token, expected):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Internal endpoint")
