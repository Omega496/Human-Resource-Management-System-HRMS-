import logging
from datetime import datetime, timezone, timedelta
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.base import superuser_sessionmaker
from src.db.models.employee import Employee
from src.db.models.refresh_token import RefreshToken
from src.modules.auth.helpers import (
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from src.core.revocation import revocation_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, response: Response) -> LoginResponse:
    """
    Log in an employee using email and password.
    
    Validates credentials, creates a short-lived JWT access token, and sets a secure, 
    HttpOnly refresh token cookie.
    """
    async with superuser_sessionmaker() as session:
        # 1. Lookup employee by email (using superuser to bypass RLS since context isn't set yet)
        stmt = select(Employee).where(
            Employee.email == payload.email,
            Employee.deleted_at.is_(None)
        )
        res = await session.execute(stmt)
        employee = res.scalars().first()

        if not employee or not employee.password_hash:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )

        # 2. Verify password
        if not verify_password(payload.password, employee.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )

        # 3. Generate tokens
        access_token, jti, exp = create_access_token(
            employee_id=employee.id,
            organization_id=employee.organization_id,
            role=employee.role,
        )
        refresh_token = generate_refresh_token()
        token_hash = hash_token(refresh_token)

        # 4. Save refresh token in DB
        db_refresh = RefreshToken(
            employee_id=employee.id,
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        session.add(db_refresh)
        await session.commit()

        # 5. Set HTTP-Only Cookie
        response.set_cookie(
            key="refresh_token",
            value=refresh_token,
            httponly=True,
            secure=True,
            samesite="strict",
            max_age=7 * 24 * 3600,  # 7 days
        )

        return LoginResponse(access_token=access_token)


@router.post("/refresh", response_model=LoginResponse)
async def refresh(request: Request, response: Response) -> LoginResponse:
    """
    Rotate and refresh the access token using the HttpOnly refresh token cookie.
    
    Verifies that the provided refresh token is valid and unexpired, rotates it 
    race-safely, and issues a new access token and a new refresh token cookie.
    """
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh token",
        )

    token_hash = hash_token(refresh_token)

    async with superuser_sessionmaker() as session:
        # 1. Look up refresh token
        stmt = select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > datetime.now(timezone.utc),
        )
        res = await session.execute(stmt)
        db_token = res.scalar_one_or_none()

        if not db_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token",
            )

        # 2. Rotate token race-safely
        update_stmt = (
            update(RefreshToken)
            .where(RefreshToken.id == db_token.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc))
            .returning(RefreshToken.id, RefreshToken.employee_id)
        )
        update_res = await session.execute(update_stmt)
        updated_row = update_res.fetchone()

        if not updated_row:
            # Race condition / duplicate reuse detected
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token already used",
            )

        # 3. Lookup employee
        emp_stmt = select(Employee).where(
            Employee.id == db_token.employee_id,
            Employee.deleted_at.is_(None)
        )
        emp_res = await session.execute(emp_stmt)
        employee = emp_res.scalar_one_or_none()

        if not employee:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Employee not found or deleted",
            )

        # 4. Generate new tokens
        access_token, jti, exp = create_access_token(
            employee_id=employee.id,
            organization_id=employee.organization_id,
            role=employee.role,
        )
        new_refresh_token = generate_refresh_token()
        new_token_hash = hash_token(new_refresh_token)

        # Save new refresh token
        new_db_refresh = RefreshToken(
            employee_id=employee.id,
            token_hash=new_token_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        session.add(new_db_refresh)
        await session.commit()

        # Set new cookie
        response.set_cookie(
            key="refresh_token",
            value=new_refresh_token,
            httponly=True,
            secure=True,
            samesite="strict",
            max_age=7 * 24 * 3600,
        )

        return LoginResponse(access_token=access_token)


class LogoutResponse(BaseModel):
    message: str


@router.post("/logout", response_model=LogoutResponse)
async def logout(request: Request, response: Response) -> LogoutResponse:
    """
    Log out the current employee.
    
    Revokes the active refresh token and access token (blacklists it in Redis), 
    and deletes the refresh token cookie.
    """
    # 1. Revoke refresh token
    refresh_token = request.cookies.get("refresh_token")
    if refresh_token:
        token_hash = hash_token(refresh_token)
        async with superuser_sessionmaker() as session:
            stmt = (
                update(RefreshToken)
                .where(RefreshToken.token_hash == token_hash)
                .values(revoked_at=datetime.now(timezone.utc))
            )
            await session.execute(stmt)
            await session.commit()

    # 2. Revoke active access token (using token claims if present)
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1]
        try:
            claims = decode_access_token(token)
            jti = claims.get("jti")
            exp = claims.get("exp")
            if jti and exp:
                # Add to local cache and publish revocation
                await revocation_cache.revoke(jti, float(exp))
        except Exception:
            # Ignore token decode errors during logout
            pass

    # 3. Clear cookie
    response.delete_cookie(
        key="refresh_token",
        httponly=True,
        secure=True,
        samesite="strict",
    )

    return LogoutResponse(message="Logged out successfully")
