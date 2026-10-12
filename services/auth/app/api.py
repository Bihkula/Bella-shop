import logging

from fastapi import APIRouter, Depends, HTTPException, status
from prometheus_client import Counter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shopcommon.auth import get_current_user
from shopcommon.config import get_settings
from shopcommon.db import get_db
from shopcommon.security import Principal, create_access_token, hash_password, verify_password

from .models import User
from .ratelimit import LoginThrottle
from .schemas import Credentials, LoginRequest, TokenResponse, UserOut

log = logging.getLogger(__name__)
router = APIRouter()
throttle = LoginThrottle()

LOGINS = Counter("shop_auth_logins_total", "Login attempts", ["result"])
REGISTRATIONS = Counter("shop_auth_registrations_total", "New user registrations")

# Used to make timing equal whether or not the email exists.
_DUMMY_HASH = hash_password("timing-equaliser-not-a-real-password")


def _issue(user: User) -> TokenResponse:
    s = get_settings()
    token = create_access_token(
        Principal(user.id, user.email, user.role),
        secret=s.jwt_secret,
        issuer=s.jwt_issuer,
        audience=s.jwt_audience,
        ttl_seconds=s.jwt_ttl_seconds,
    )
    return TokenResponse(access_token=token, expires_in=s.jwt_ttl_seconds)


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(body: Credentials, db: Session = Depends(get_db)) -> UserOut:
    user = User(
        email=body.email.lower(), password_hash=hash_password(body.password), role="customer"
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered") from None
    REGISTRATIONS.inc()
    return UserOut(id=user.id, email=user.email, role=user.role)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    email = body.email.lower()
    if throttle.is_blocked(email):
        LOGINS.labels("throttled").inc()
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed attempts")

    user = db.scalar(select(User).where(User.email == email))
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok:
        throttle.record_failure(email)
        LOGINS.labels("failure").inc()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    throttle.reset(email)
    LOGINS.labels("success").inc()
    return _issue(user)


@router.get("/me", response_model=UserOut)
def me(principal: Principal = Depends(get_current_user)) -> UserOut:
    return UserOut(id=principal.user_id, email=principal.email, role=principal.role)
