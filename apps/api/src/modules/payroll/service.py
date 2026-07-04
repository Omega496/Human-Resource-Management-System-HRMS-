import uuid
from datetime import date, datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.models.payroll_rule import PayrollRule
from src.db.models.payroll_ledger_line import PayrollLedgerLine

class PayrollRuleResolver:
    @staticmethod
    async def resolve(
        db: AsyncSession,
        organization_id: uuid.UUID,
        rule_type: str,
        rule_key: str,
        as_of: datetime,
    ) -> PayrollRule | None:
        """
        Resolves a single payroll rule valid as of the given timestamp.
        Matches: valid_from <= as_of AND (valid_to IS NULL OR valid_to > as_of)
        
        Overlapping prevention:
        Overlapping rule validities are prevented at the database level using an EXCLUDE constraint:
        ADD CONSTRAINT no_overlapping_payroll_rules EXCLUDE USING gist (
            organization_id WITH =,
            rule_type WITH =,
            rule_key WITH =,
            (tstzrange(valid_from, valid_to, '[)')) WITH &&
        )
        Because ranges are half-open '[)' (inclusive start, exclusive end), any given as_of timestamp
        resolves to exactly zero or one rule.
        """
        stmt = (
            select(PayrollRule)
            .where(
                PayrollRule.organization_id == organization_id,
                PayrollRule.rule_type == rule_type,
                PayrollRule.rule_key == rule_key,
                PayrollRule.valid_from <= as_of,
                (PayrollRule.valid_to == None) | (PayrollRule.valid_to > as_of),
            )
        )
        res = await db.execute(stmt)
        return res.scalar_one_or_none()
