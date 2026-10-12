import logging

from sqlalchemy import select

from shopcommon.app import create_app
from shopcommon.config import env
from shopcommon.db import session_scope
from shopcommon.security import hash_password

from .api import router
from .models import User

log = logging.getLogger(__name__)


def seed_admin() -> None:
    """Create the admin user from ADMIN_EMAIL / ADMIN_PASSWORD if it doesn't exist."""
    email, password = env("ADMIN_EMAIL"), env("ADMIN_PASSWORD")
    if not email or not password:
        return
    with session_scope() as db:
        if db.scalar(select(User).where(User.email == email.lower())):
            return
        db.add(User(email=email.lower(), password_hash=hash_password(password), role="admin"))
        db.commit()
        log.info("seeded admin user %s", email)


app = create_app("auth", [router], on_startup=seed_admin)
