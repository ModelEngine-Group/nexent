"""Shared permission data models."""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class CurrentUser:
    """Authenticated user context used by permission checks."""

    user_id: str
    tenant_id: str
    role: str
    groups: List[int] = field(default_factory=list)

    @property
    def normalized_role(self) -> str:
        return (self.role or "").upper()


@dataclass(frozen=True)
class Resource:
    """Resource descriptor consumed by the DAC."""

    resource_type: str
    resource_id: str
    tenant_id: Optional[str] = None
    created_by: Optional[str] = None
    ingroup_permission: Optional[str] = None
    group_ids: Optional[List[object]] = None
    knowledge_sources: Optional[str] = None


@dataclass(frozen=True)
class ResourceAccess:
    """Result of a DAC access decision."""

    can_read: bool = False
    can_edit: bool = False
    is_creator: bool = False
    matched_groups: List[object] = field(default_factory=list)
    permission_label: Optional[str] = None

    @classmethod
    def deny(cls) -> "ResourceAccess":
        return cls()

    @classmethod
    def read_only(cls) -> "ResourceAccess":
        return cls(can_read=True, permission_label="READ_ONLY")

    @classmethod
    def edit(cls) -> "ResourceAccess":
        return cls(can_read=True, can_edit=True, permission_label="EDIT")

    @classmethod
    def creator(cls, matched_groups: Optional[List[object]] = None) -> "ResourceAccess":
        return cls(
            can_read=True,
            can_edit=True,
            is_creator=True,
            matched_groups=list(matched_groups or []),
            permission_label="CREATOR",
        )
