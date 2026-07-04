from datetime import datetime
import uuid
from typing import TYPE_CHECKING, List

from sqlalchemy import DateTime, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base

if TYPE_CHECKING:
    from src.db.models.employee import Employee


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    )

    # Relationships
    employees: Mapped[List["Employee"]] = relationship(
        "Employee",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
