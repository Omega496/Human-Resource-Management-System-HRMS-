from datetime import datetime
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base

if TYPE_CHECKING:
    from src.db.models.organization import Organization
    from src.db.models.employee import Employee


class PseudonymizationMap(Base):
    __tablename__ = "pseudonymization_map"

    original_employee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"),
        primary_key=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    pseudonym_hash: Mapped[str] = mapped_column(
        String,
        unique=True,
        nullable=False,
    )
    structural_cohort: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )
    pseudonymized_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    )
    requested_by: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    # Relationships
    organization: Mapped["Organization"] = relationship("Organization")
    employee: Mapped["Employee"] = relationship("Employee")
