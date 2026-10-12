"""Environment-driven settings shared by every service.

Kept free of third-party imports so it can be unit-tested anywhere.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache

log = logging.getLogger(__name__)

_DEV_JWT_SECRET = "dev-only-insecure-jwt-secret-change-me-0123456789"  # noqa: S105
_DEV_INTERNAL_TOKEN = "dev-only-internal-token"  # noqa: S105


def env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    app_env: str
    service_name: str
    database_url: str
    jwt_secret: str
    jwt_issuer: str
    jwt_audience: str
    jwt_ttl_seconds: int
    internal_token: str
    log_level: str

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


def _secret(name: str, dev_default: str, app_env: str) -> str:
    value = env(name)
    if value:
        return value
    if app_env == "production":
        raise RuntimeError(f"{name} must be set when APP_ENV=production")
    log.warning("%s not set; using an insecure development default", name)
    return dev_default


@lru_cache
def get_settings() -> Settings:
    app_env = env("APP_ENV", "development") or "development"
    return Settings(
        app_env=app_env,
        service_name=env("SERVICE_NAME", "shop") or "shop",
        database_url=env("DATABASE_URL", "sqlite:///./local.db") or "",
        jwt_secret=_secret("JWT_SECRET", _DEV_JWT_SECRET, app_env),
        jwt_issuer=env("JWT_ISSUER", "shop-auth") or "shop-auth",
        jwt_audience=env("JWT_AUDIENCE", "shop") or "shop",
        jwt_ttl_seconds=int(env("JWT_TTL_SECONDS", "3600") or 3600),
        internal_token=_secret("INTERNAL_TOKEN", _DEV_INTERNAL_TOKEN, app_env),
        log_level=env("LOG_LEVEL", "INFO") or "INFO",
    )
