from datetime import date, datetime
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, String, BigInteger, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base

if TYPE_CHECKING:
    from src.db.models.organization import Organization
    from src.db.models.employee import Employee
    from src.db.models.payroll_rule import PayrollRule


class PayrollLedgerLine(Base):
    __tablename__ = "payroll_ledger_lines"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    ledger_month: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    line_type: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )
    amount_cents: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String,
        server_default=text("'open'"),
        nullable=False,
    )
    adjustment_of: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("payroll_ledger_lines.id", ondelete="SET NULL"),
        nullable=True,
    )
    computed_from_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("payroll_rules.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    organization: Mapped["Organization"] = relationship("Organization")
    employee: Mapped["Employee"] = relationship("Employee")
    adjustment_source: Mapped["PayrollLedgerLine | None"] = relationship(
        "PayrollLedgerLine",
        remote_side=[id],
    )
    computed_from_rule: Mapped["PayrollRule | None"] = relationship(
        "PayrollRule",
    )
