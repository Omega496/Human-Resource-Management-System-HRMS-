from datetime import datetime
import uuid
from typing import TYPE_CHECKING

import zoneinfo
from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from src.db.base import Base

if TYPE_CHECKING:
    from src.db.models.organization import Organization


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str] = mapped_column(
        Text,
        server_default=text("'UTC'"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        Text,
        server_default=text("'active'"),
        nullable=False,
    )
    password_hash: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="employees",
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "email", name="uq_organization_id_email"),
    )

    @validates("timezone")
    def validate_timezone(self, key, value):
        try:
            zoneinfo.ZoneInfo(value)
        except Exception:
            raise ValueError(f"Invalid timezone: {value}")
        return value
