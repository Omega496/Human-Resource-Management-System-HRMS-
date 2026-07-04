import hashlib
import secrets
from datetime import datetime, timezone, timedelta
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.base import superuser_sessionmaker
from src.db.session import get_db
from src.db.models.invitation import Invitation
from src.db.models.employee import Employee
from src.modules.auth.helpers import hash_password

logger = logging.getLogger(__name__)

router = APIRouter(tags=["invitations"])


class InvitationCreate(BaseModel):
    email: EmailStr
    role: str


class InvitationAccept(BaseModel):
    email: EmailStr
    raw_token: str
    full_name: str
    password: str


class InvitationRecordResponse(BaseModel):
    id: str
    email: str
    role: str
    expires_at: str
    used_at: str | None = None
    created_at: str


class InvitationCreateResponse(BaseModel):
    invitation_link: str
    raw_token: str
    email: str
    role: str


class InvitationAcceptResponse(BaseModel):
    detail: str


@router.get("/invitations", response_model=list[InvitationRecordResponse])
async def get_invitations(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> list[InvitationRecordResponse]:
    """
    Retrieve all pending, expired, and used signup invitations for the organization.
    
    Accessible only by admins.
    """
    ctx = request.state.tenant_context
    if not ctx:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    if ctx.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can view invitations",
        )
    stmt = select(Invitation).order_by(Invitation.created_at.desc())
    res = await db.execute(stmt)
    records = res.scalars().all()
    return [
        InvitationRecordResponse(
            id=str(r.id),
            email=r.email,
            role=r.role,
            expires_at=r.expires_at.isoformat(),
            used_at=r.used_at.isoformat() if r.used_at else None,
            created_at=r.created_at.isoformat(),
        )
        for r in records
    ]


@router.post("/invitations", response_model=InvitationCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_invitation(
    payload: InvitationCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> InvitationCreateResponse:
    """
    Issue a new single-use signup invitation for the organization.
    
    Generates a cryptographically secure token, hashes it in the database, 
    and returns the raw token to be shared with the invitee. Expires in 24 hours.
    Accessible only by admins.
    """
    # 1. Admin-only role check
    ctx = request.state.tenant_context
    if not ctx:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    if ctx.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can issue invitations",
        )

    # 2. Generate raw token and hash
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

    # 3. Create invitation record
    invitation = Invitation(
        organization_id=ctx.organization_id,
        email=payload.email.strip().lower(),
        token_hash=token_hash,
        role=payload.role,
        invited_by=ctx.user_id,
        expires_at=expires_at,
    )
    db.add(invitation)
    # The transaction will be committed automatically by get_db's context manager

    # 4. Return registration link with RAW token
    invitation_link = f"https://example.com/accept-invitation?token={raw_token}"
    return InvitationCreateResponse(
        invitation_link=invitation_link,
        raw_token=raw_token,
        email=payload.email,
        role=payload.role,
    )


@router.post("/invitations/accept", response_model=InvitationAcceptResponse, status_code=status.HTTP_200_OK)
async def accept_invitation(payload: InvitationAccept) -> InvitationAcceptResponse:
    """
    Accept an invitation to register a new employee account.
    
    Validates token and email, marks the invitation as used in a transaction, 
    and creates the corresponding employee record. Safe against token reuse.
    """
    token_hash = hashlib.sha256(payload.raw_token.encode()).hexdigest()

    # Use superuser_sessionmaker to bypass RLS since the client does not have tenant context yet
    async with superuser_sessionmaker() as session:
        async with session.begin():
            # 1. Look up invitation by token_hash
            stmt = select(Invitation).where(Invitation.token_hash == token_hash)
            res = await session.execute(stmt)
            invitation = res.scalar_one_or_none()

            # 2. Verify existence and case-insensitive email match
            if not invitation or invitation.email.strip().lower() != payload.email.strip().lower():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="This invitation link is invalid or has expired.",
                )

            # 3. Perform single-use claim via conditional update
            update_stmt = (
                update(Invitation)
                .where(
                    Invitation.id == invitation.id,
                    Invitation.used_at.is_(None),
                    Invitation.expires_at > datetime.now(timezone.utc),
                )
                .values(used_at=datetime.now(timezone.utc))
                .returning(Invitation.id)
            )
            update_res = await session.execute(update_stmt)
            updated_id = update_res.scalar_one_or_none()

            if not updated_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="This invitation link is invalid or has expired.",
                )

            # 4. Create new employee in the same transaction
            pwd_hash = hash_password(payload.password)
            new_employee = Employee(
                organization_id=invitation.organization_id,
                email=invitation.email,  # Use verified email from invitation
                full_name=payload.full_name,
                role=invitation.role,    # Use role from invitation
                status="active",
                password_hash=pwd_hash,
            )
            session.add(new_employee)

    return InvitationAcceptResponse(detail="Account registered successfully")
