# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


from __future__ import annotations

from collections.abc import Awaitable, Collection
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

DEFAULT_RESOURCE_LIBRARY_CODE = "default_resource"


class ResourceType(str, Enum):
    """Resource types bound to the tenant's default resource library."""

    AGENT = "agent"
    SKILL = "skill"
    TOOL = "tool"
    MCP_SERVICE = "mcp_service"
    KNOWLEDGE_BASE = "knowledge_base"
    KNOWLEDGE_DOCUMENT = "knowledge_document"


class ResourceOrigin(str, Enum):
    """The record which supplied a resource reference, not its tag identity."""

    CANONICAL = "canonical"
    MARKETPLACE = "marketplace"
    COMMUNITY = "community"


@dataclass(frozen=True, slots=True)
class AuthenticatedCaller:
    """Server-derived caller facts; none of these values may come from a request body."""

    user_id: str
    authenticated_tenant_id: str
    role: str = ""
    group_ids: Collection[str | int] = field(default_factory=tuple)
    can_edit_all: bool = False

    def normalized_group_ids(self) -> frozenset[str]:
        return frozenset(str(group_id) for group_id in self.group_ids)


@dataclass(frozen=True, slots=True)
class ResourceReference:
    """Untrusted resource identifier; tenant scope is intentionally absent."""

    resource_type: ResourceType | str
    resource_id: int | str
    origin: ResourceOrigin | str = ResourceOrigin.CANONICAL
    provider: str | None = None
    knowledge_base_id: str | None = None

    def normalized_type(self) -> ResourceType | None:
        try:
            return ResourceType(self.resource_type)
        except (TypeError, ValueError):
            return None

    def normalized_origin(self) -> ResourceOrigin | None:
        try:
            return ResourceOrigin(self.origin)
        except (TypeError, ValueError):
            return None


@dataclass(frozen=True, slots=True)
class ResourceCapabilities:
    can_read: bool = False
    can_edit: bool = False


@dataclass(frozen=True, slots=True)
class ResourceDisplayMetadata:
    name: str
    description: str | None = None
    source: str | None = None


@dataclass(frozen=True, slots=True)
class CanonicalResourceIdentity:
    """Stable source identity used for tag assignments and cleanup."""

    resource_type: ResourceType
    resource_id: str
    publisher_tenant_id: str
    library_code: str = DEFAULT_RESOURCE_LIBRARY_CODE
    provider: str | None = None
    knowledge_base_id: str | None = None
    provider_document_id: str | None = None

    @property
    def tenant_id(self) -> str:
        """Return the tenant which owns this canonical resource."""

        return self.publisher_tenant_id

    @property
    def key(self) -> str:
        return f"{self.resource_type.value}:{self.resource_id}"


@dataclass(frozen=True, slots=True)
class TagAssignmentCleanupDescriptor:
    """Input for a later tag-assignment deletion implementation."""

    identity: CanonicalResourceIdentity


class TagAssignmentCleanupCallback(Protocol):
    """Contract the future tag-assignment service must implement."""

    def __call__(
        self,
        descriptor: TagAssignmentCleanupDescriptor,
    ) -> Awaitable[None] | None: ...


@dataclass(frozen=True, slots=True)
class ResolvedTagResource:
    """The only successful output accepted by a future tag-assignment service."""

    found: bool
    identity: CanonicalResourceIdentity | None = None
    display: ResourceDisplayMetadata | None = None
    capabilities: ResourceCapabilities = ResourceCapabilities()
    cleanup: TagAssignmentCleanupDescriptor | None = None

    @classmethod
    def not_found(cls) -> ResolvedTagResource:
        """Return one indistinguishable result for unknown and cross-tenant resources."""

        return cls(found=False)
