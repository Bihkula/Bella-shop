import time

import pytest

from shopcommon.security import (
    Principal,
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

KW = {"secret": "s3cret-at-least-32-bytes-long-abcdefgh", "issuer": "shop-auth", "audience": "shop"}


def test_hash_roundtrip():
    h = hash_password("correct horse", iterations=1000)
    assert h.startswith("pbkdf2_sha256$1000$")
    assert verify_password("correct horse", h)
    assert not verify_password("wrong", h)


def test_hash_is_salted():
    assert hash_password("x", iterations=1000) != hash_password("x", iterations=1000)


def test_verify_rejects_garbage():
    assert not verify_password("x", "not-a-hash")
    assert not verify_password("x", "md5$1$a$b")


def test_empty_password_rejected():
    with pytest.raises(ValueError):
        hash_password("")


def test_token_roundtrip():
    p = Principal(user_id=7, email="a@b.c", role="admin")
    tok = create_access_token(p, ttl_seconds=60, **KW)
    assert decode_access_token(tok, **KW) == p


def test_token_expired():
    p = Principal(user_id=1, email="a@b.c", role="customer")
    tok = create_access_token(p, ttl_seconds=10, now=int(time.time()) - 100, **KW)
    with pytest.raises(TokenError):
        decode_access_token(tok, **KW)


def test_token_wrong_secret_or_audience():
    p = Principal(user_id=1, email="a@b.c", role="customer")
    tok = create_access_token(p, ttl_seconds=60, **KW)
    with pytest.raises(TokenError):
        decode_access_token(tok, secret="other-at-least-32-bytes-long-abcdefghij", issuer="shop-auth", audience="shop")
    with pytest.raises(TokenError):
        decode_access_token(tok, secret="s3cret-at-least-32-bytes-long-abcdefgh", issuer="shop-auth", audience="other")
