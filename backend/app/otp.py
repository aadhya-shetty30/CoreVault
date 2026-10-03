"""TOTP-based 2FA helpers (pyotp) and the short-lived "pending" JWT issued
between password verification and OTP verification during login."""
from datetime import datetime, timedelta, timezone

import jwt
import pyotp

from app.config import settings

PENDING_TOKEN_PURPOSE = "2fa_pending"


def generate_otp_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, account_email: str) -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(name=account_email, issuer_name=settings.OTP_ISSUER_NAME)


def verify_otp_code(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def create_pending_token(user_id: str) -> str:
    """Issued by POST /auth/login when the account has 2FA enabled, in place
    of a real access token. It proves "password already checked out for this
    user" but grants no API access itself -- only POST /auth/2fa/verify
    accepts it, and only to exchange it for a real access token."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "purpose": PENDING_TOKEN_PURPOSE,
        "iat": now,
        "exp": now + timedelta(minutes=settings.OTP_PENDING_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_pending_token(token: str) -> str:
    """Returns the user id encoded in a pending token. Raises jwt.PyJWTError
    on any problem, and ValueError if the token is valid but isn't actually
    a pending-2FA token (e.g. someone passed a normal access token here)."""
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    if payload.get("purpose") != PENDING_TOKEN_PURPOSE:
        raise ValueError("Not a pending 2FA token")
    return payload["sub"]
