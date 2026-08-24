"""Unit tests for JWT authentication."""

from __future__ import annotations

import uuid

import jwt
import pytest

from app.auth.jwt import (
    create_access_token,
    create_refresh_token,
    create_token_pair,
    decode_token,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    """Tests for bcrypt password operations."""

    def test_hash_and_verify(self):
        """Password hash should verify correctly."""
        password = "MySecurePassword123!"  # noqa: S105
        hashed = hash_password(password)

        assert verify_password(password, hashed)
        assert not verify_password("WrongPassword", hashed)

    def test_different_hashes(self):
        """Same password should produce different hashes (salt)."""
        password = "TestPassword"  # noqa: S105
        hash1 = hash_password(password)
        hash2 = hash_password(password)

        assert hash1 != hash2  # Different salts
        assert verify_password(password, hash1)
        assert verify_password(password, hash2)


class TestTokenCreation:
    """Tests for JWT token creation."""

    def test_access_token_creation(self):
        """Should create a valid access token."""
        user_id = uuid.uuid4()
        token = create_access_token(user_id, "user")

        assert isinstance(token, str)
        payload = decode_token(token)
        assert payload.sub == str(user_id)
        assert payload.role == "user"
        assert payload.type == "access"

    def test_refresh_token_creation(self):
        """Should create a valid refresh token."""
        user_id = uuid.uuid4()
        token = create_refresh_token(user_id, "admin")

        payload = decode_token(token)
        assert payload.type == "refresh"
        assert payload.role == "admin"

    def test_token_pair_creation(self):
        """Should create both access and refresh tokens."""
        user_id = uuid.uuid4()
        pair = create_token_pair(user_id, "user")

        assert pair.access_token != pair.refresh_token
        assert pair.token_type == "bearer"  # noqa: S105
        assert pair.expires_in > 0

    def test_expired_token_rejected(self):
        """Expired tokens should be rejected."""
        import datetime

        user_id = uuid.uuid4()
        payload = {
            "sub": str(user_id),
            "role": "user",
            "type": "access",
            "exp": datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1),
            "iat": datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=2),
            "jti": str(uuid.uuid4()),
        }
        from app.config import get_settings

        settings = get_settings()
        token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

        with pytest.raises(jwt.ExpiredSignatureError):
            decode_token(token)

    def test_invalid_token_rejected(self):
        """Malformed tokens should be rejected."""
        with pytest.raises(jwt.InvalidTokenError):
            decode_token("not-a-valid-token")

    def test_wrong_secret_rejected(self):
        """Tokens signed with wrong key should be rejected."""
        user_id = uuid.uuid4()
        payload = {
            "sub": str(user_id),
            "role": "user",
            "type": "access",
        }
        token = jwt.encode(payload, "wrong-secret", algorithm="HS256")

        with pytest.raises(jwt.InvalidTokenError):
            decode_token(token)
