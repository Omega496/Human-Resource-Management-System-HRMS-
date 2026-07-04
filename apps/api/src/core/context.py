from dataclasses import dataclass
from uuid import UUID


@dataclass
class TenantContext:
    organization_id: UUID
    user_id: UUID
    role: str
