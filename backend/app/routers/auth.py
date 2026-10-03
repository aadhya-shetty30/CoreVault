"""
Registration and login.

Login enforces the account-lockout rule from the spec: MAX_FAILED_LOGIN_ATTEMPTS
consecutive failed attempts locks the account for LOCKOUT_MINUTES
(app/config.py). failed_login_attempts only resets to 0 on a *successful*
login, so "consecutive" holds even if the caller waits out an expired lock
and then fails again.
"""
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.otp import (
    create_pending_token,
    decode_pending_token,
    generate_otp_secret,
    provisioning_uri,
    verify_otp_code,
)
from app.schemas import (
    LoginRequest,
    LoginResponse,
    TokenResponse,
    TwoFactorSetupOut,
    TwoFactorVerifyRequest,
    TwoFactorVerifySetupRequest,
    UserCreate,
    UserOut,
)
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(
        select(User).where((User.email == payload.email) | (User.username == payload.username))
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email or username already registered")

    user = User(
        email=payload.email,
        username=payload.username,
        password_hash=hash_password(payload.password),
        storage_quota_bytes=settings.DEFAULT_STORAGE_QUOTA_BYTES,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    # Same error for "no such user" and "wrong password" so the response
    # can't be used to enumerate registered emails.
    invalid_credentials = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if user is None:
        raise invalid_credentials

    now = datetime.now(timezone.utc)
    if user.locked_until is not None and user.locked_until > now:
        raise HTTPException(
            status.HTTP_423_LOCKED,
            f"Account locked until {user.locked_until.isoformat()} due to too many failed logins",
        )

    if not verify_password(payload.password, user.password_hash):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= settings.MAX_FAILED_LOGIN_ATTEMPTS:
            user.locked_until = now + timedelta(minutes=settings.LOCKOUT_MINUTES)
        await db.commit()
        raise invalid_credentials

    user.failed_login_attempts = 0
    user.locked_until = None
    await db.commit()

    # Phase 2: password alone isn't enough once 2FA is enabled -- hand back
    # a short-lived pending token instead of a real one; only
    # POST /auth/2fa/verify (with the right OTP code) can exchange it.
    if user.otp_enabled:
        return LoginResponse(requires_2fa=True, pending_token=create_pending_token(str(user.id)))

    token = create_access_token(str(user.id))
    return LoginResponse(requires_2fa=False, access_token=token)


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return current_user


# --- Phase 2: OTP-based 2FA ---------------------------------------------------


@router.post("/2fa/setup", response_model=TwoFactorSetupOut)
async def setup_2fa(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Generates a new TOTP secret and stores it (otp_enabled stays False
    until verify-setup confirms the user actually has it loaded). Calling
    this again before verifying replaces the pending secret -- harmless,
    since it isn't active yet either way."""
    secret = generate_otp_secret()
    current_user.otp_secret = secret
    await db.commit()
    return TwoFactorSetupOut(secret=secret, otpauth_uri=provisioning_uri(secret, current_user.email))


@router.post("/2fa/verify-setup", response_model=UserOut)
async def verify_2fa_setup(
    payload: TwoFactorVerifySetupRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.otp_secret:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Call /auth/2fa/setup first")
    if not verify_otp_code(current_user.otp_secret, payload.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid code")
    current_user.otp_enabled = True
    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.post("/2fa/verify", response_model=TokenResponse)
async def verify_2fa(payload: TwoFactorVerifyRequest, db: AsyncSession = Depends(get_db)):
    try:
        user_id = uuid.UUID(decode_pending_token(payload.pending_token))
    except (jwt.PyJWTError, ValueError, KeyError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired pending token")

    user = await db.get(User, user_id)
    if user is None or not user.otp_enabled or not user.otp_secret:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired pending token")

    if not verify_otp_code(user.otp_secret, payload.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid code")

    return TokenResponse(access_token=create_access_token(str(user.id)))
