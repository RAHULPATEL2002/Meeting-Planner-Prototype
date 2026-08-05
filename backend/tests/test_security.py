"""Unit tests for password hashing and JWT handling (no HTTP involved)."""

from __future__ import annotations

from datetime import timedelta

import jwt
import pytest

from app.config import settings
from app.security import (
    BCRYPT_MAX_PASSWORD_BYTES,
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_hash_is_not_the_plaintext_and_verifies():
    hashed = hash_password("correct horse battery")
    assert hashed != "correct horse battery"
    assert verify_password("correct horse battery", hashed)


def test_wrong_password_is_rejected():
    assert not verify_password("nope", hash_password("correct horse battery"))


def test_same_password_hashes_differently_each_time():
    """A per-password salt means identical passwords must not collide."""
    assert hash_password("same-input") != hash_password("same-input")


def test_password_over_bcrypt_limit_is_refused():
    """bcrypt silently ignores bytes past 72; refusing is safer than truncating."""
    with pytest.raises(ValueError):
        hash_password("x" * (BCRYPT_MAX_PASSWORD_BYTES + 1))


def test_verify_against_a_corrupt_hash_returns_false():
    assert not verify_password("anything", "not-a-bcrypt-hash")


def test_token_round_trip():
    token, expires_in = create_access_token(42)
    assert decode_access_token(token) == 42
    assert expires_in == settings.access_token_expire_minutes * 60


def test_expired_token_is_rejected():
    token, _ = create_access_token(1, expires_delta=timedelta(seconds=-1))
    with pytest.raises(TokenError):
        decode_access_token(token)


def test_token_signed_with_another_key_is_rejected():
    forged = jwt.encode({"sub": "1"}, "some-other-key", algorithm="HS256")
    with pytest.raises(TokenError):
        decode_access_token(forged)


def test_token_without_subject_is_rejected():
    token = jwt.encode({"foo": "bar"}, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    with pytest.raises(TokenError):
        decode_access_token(token)


def test_garbage_token_is_rejected():
    with pytest.raises(TokenError):
        decode_access_token("clearly.not.a.jwt")
