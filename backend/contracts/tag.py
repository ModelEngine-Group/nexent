# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""OpenAPI response contracts for controlled tag conflicts."""

from __future__ import annotations

from collections.abc import Awaitable, Collection
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, List, Literal, Optional, Protocol

from contracts.constants.constants import DEFAULT_RESOURCE_LIBRARY_CODE
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TagDefinitionCreateRequest(BaseModel):
    definition_key: str | None = Field(None, min_length=1, max_length=100)
    definition_name: str = Field(..., min_length=1, max_length=255)
    selection_mode: Literal["single_select", "multi_select", "no_value"]
    initial_values: list[str] = Field(default_factory=list, max_length=1000)
    sort_order: int | None = None

    @field_validator("definition_key", "definition_name")
    @classmethod
    def strip_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value must not be empty")
        return normalized

    @field_validator("initial_values")
    @classmethod
    def validate_initial_values(cls, values: list[str]) -> list[str]:
        normalized_values = []
        seen = set()
        for value in values:
            normalized = value.strip()
            if not normalized:
                raise ValueError("Tag values must not be empty")
            normalized_key = normalized.lower()
            if normalized_key in seen:
                raise ValueError("Tag values must be unique after normalization")
            seen.add(normalized_key)
            normalized_values.append(normalized)
        return normalized_values

    @model_validator(mode="after")
    def validate_selection_mode_values(self):
        if self.selection_mode == "no_value" and self.initial_values:
            raise ValueError("A no-value tag definition cannot contain tag values")
        if self.selection_mode != "no_value" and not self.initial_values:
            raise ValueError("At least one tag value is required")
        return self


class TagDefinitionUpdateRequest(BaseModel):
    definition_name: str | None = Field(None, min_length=1, max_length=255)
    selection_mode: Literal["single_select", "multi_select", "no_value"] | None = None

    @field_validator("definition_name")
    @classmethod
    def strip_definition_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Definition name must not be empty")
        return normalized


class TagValueCreateRequest(BaseModel):
    display_value: str = Field(..., min_length=1)
    sort_order: int = 0

    @field_validator("display_value")
    @classmethod
    def strip_display_value(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Tag value must not be empty")
        return normalized


class TagValueUpdateRequest(BaseModel):
    display_value: str = Field(..., min_length=1)

    @field_validator("display_value")
    @classmethod
    def strip_updated_display_value(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Tag value must not be empty")
        return normalized


class TagStatusUpdateRequest(BaseModel):
    status: Literal["active", "disabled"]


class TagOrderUpdateRequest(BaseModel):
    sort_order: int


class TagAuditResponse(BaseModel):
    created_by: str | None = None
    updated_by: str | None = None
    create_time: datetime | None = None
    update_time: datetime | None = None


class TagValueResponse(TagAuditResponse):
    value_id: int
    display_value: str
    normalized_value: str
    sort_order: int
    status: Literal["active", "disabled"]


class TagDefinitionResponse(TagAuditResponse):
    definition_id: int
    bucket_id: int
    definition_key: str
    definition_name: str
    selection_mode: Literal["single_select", "multi_select", "no_value"]
    sort_order: int
    status: Literal["active", "disabled"]
    active_value_count: int = Field(..., ge=0, le=1000)
    value_capacity: int = Field(..., ge=1, le=1000)
    values: list[TagValueResponse] | None = Field(default=None, max_length=1000)


class TagLibraryResponse(TagAuditResponse):
    bucket_id: int
    bucket_key: Literal["default_resource", "knowledge_content"]
    bucket_name: str
    status: Literal["active", "disabled"]
    resource_types: List[
        Literal[
            "agent",
            "skill",
            "tool",
            "mcp_service",
            "knowledge_base",
            "knowledge_document",
        ]
    ] = Field(default_factory=list, max_length=6)
    definition_count: int = Field(..., ge=0, le=100)
    definition_capacity: int = Field(..., ge=1, le=100)


class TagDefinitionUsageResponse(BaseModel):
    definition_id: int
    active_value_count: int = Field(..., ge=0, le=1000)
    active_usage_count: int = Field(..., ge=0)
    value_capacity: int = Field(..., ge=1, le=1000)


class TagValueUsageResponse(BaseModel):
    value_id: int
    active_usage_count: int = Field(..., ge=0)


class TagDeleteResponse(BaseModel):
    success: bool


class TagConflictDetailsResponse(BaseModel):
    definition_id: Optional[int] = None
    value_id: Optional[int] = None
    active_value_count: int | None = Field(None, ge=0, le=1000)
    active_usage_count: int | None = Field(None, ge=0)
    resources_with_multiple_values: int | None = Field(None, ge=0)
    limit: int | None = Field(None, ge=1)
    current_count: int | None = Field(None, ge=0)
    scope: Literal["definition", "value", "assignment"] | None = None


class TagConflictResponse(BaseModel):
    message: str
    details: TagConflictDetailsResponse


class TagHTTPConflictResponse(BaseModel):
    detail: TagConflictResponse


_LEGACY_FLAT_TAG_FIELDS = ("tags", "labels", "label", "tag")


def _reject_legacy_flat_tag_fields(data: Any) -> None:
    """Reject deprecated flat tag fields on canonical structured writes."""

    if not isinstance(data, dict):
        return
    supplied = [field for field in _LEGACY_FLAT_TAG_FIELDS if field in data]
    if supplied:
        raise ValueError(
            "Legacy flat tag fields are rejected by the canonical assignment API "
            f"({', '.join(supplied)}); submit structured controlled value_ids only. "
            "Use the migration backfill or the structured assignment endpoints."
        )


def _validate_tag_batch_ids(resource_ids: list[int]) -> list[int]:
    if any(
        resource_id <= 0 or resource_id > 9223372036854775807
        for resource_id in resource_ids
    ):
        raise ValueError("resource IDs must contain positive bigint identifiers")
    return list(dict.fromkeys(resource_ids))


class SkillTagAssignmentBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill_ids: list[int] = Field(..., min_length=1, max_length=500)

    @field_validator("skill_ids")
    @classmethod
    def validate_skill_ids(cls, skill_ids: list[int]) -> list[int]:
        return _validate_tag_batch_ids(skill_ids)


class KnowledgeTagAssignmentBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index_names: list[str] = Field(..., min_length=1, max_length=500)

    @field_validator("index_names")
    @classmethod
    def validate_index_names(cls, index_names: list[str]) -> list[str]:
        if any(not name.strip() or len(name) > 1024 for name in index_names):
            raise ValueError(
                "index_names must contain nonempty bounded resource identifiers"
            )
        return list(dict.fromkeys(index_names))


class AgentTagAssignmentBatchRequest(BaseModel):
    """Read at most one page of canonical agent assignments."""

    model_config = ConfigDict(extra="forbid")
    agent_ids: list[int] = Field(..., min_length=1, max_length=500)

    @field_validator("agent_ids")
    @classmethod
    def validate_agent_ids(cls, agent_ids: list[int]) -> list[int]:
        return _validate_tag_batch_ids(agent_ids)


class ToolTagAssignmentBatchRequest(BaseModel):
    """Read at most one page of tool assignments in authenticated tenant scope."""

    model_config = ConfigDict(extra="forbid")
    tool_ids: list[int] = Field(..., min_length=1, max_length=500)

    @field_validator("tool_ids")
    @classmethod
    def validate_tool_ids(cls, tool_ids: list[int]) -> list[int]:
        return _validate_tag_batch_ids(tool_ids)


class TagAssignmentReplaceRequest(BaseModel):
    """Controlled value identifiers replacing one resource's assignments."""

    model_config = ConfigDict(extra="forbid")

    value_ids: list[int] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def reject_legacy_flat_writes(cls, data):
        _reject_legacy_flat_tag_fields(data)
        return data

    @field_validator("value_ids")
    @classmethod
    def validate_value_ids(cls, value_ids: list[int]) -> list[int]:
        if any(value_id <= 0 for value_id in value_ids):
            raise ValueError("Tag value IDs must be positive")
        return list(dict.fromkeys(value_ids))


class TagAssignmentValueResponse(BaseModel):
    definition_id: int
    definition_key: str
    definition_name: str
    selection_mode: Literal["single_select", "multi_select", "no_value"]
    value_id: int
    display_value: str
    value_status: Literal["active", "disabled"]


class TagAssignmentResponse(BaseModel):
    resource_type: Literal[
        "agent",
        "skill",
        "tool",
        "mcp_service",
        "knowledge_base",
        "knowledge_document",
    ]
    resource_id: str
    assignment_count: int = Field(..., ge=0, le=100)
    assignment_capacity: int = Field(..., ge=1, le=100)
    assignments: list[TagAssignmentValueResponse] = Field(default_factory=list)


class TagDocumentProjectionStatusResponse(BaseModel):
    """Synchronization status of one provider-backed document tag projection."""

    status: Literal["pending", "synced", "failed", "unsupported", "not_projected"]
    version: int
    tag_count: int
    last_error: str | None = None
    retry_count: int = 0
    last_attempt_at: datetime | None = None
    next_attempt_at: datetime | None = None
    update_time: datetime | None = None


class TagLegacyFlatTagsProjectionResponse(BaseModel):
    """Bounded deprecated flat-array projection derived from structured assignments."""

    resource_type: str
    resource_id: str
    tags: list[str] = Field(default_factory=list)
    count: int = 0
    limit: int = 100
    deprecated: Literal[True] = True


class TagAssignmentBulkTarget(BaseModel):
    """One explicit resource target for a bulk replacement request."""

    model_config = ConfigDict(extra="forbid")

    resource_id: str = Field(..., min_length=1)
    provider: str | None = Field(None, min_length=1)
    knowledge_base_id: str | None = Field(None, min_length=1)
    value_ids: list[int] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def reject_legacy_flat_writes(cls, data):
        _reject_legacy_flat_tag_fields(data)
        return data

    @field_validator("value_ids")
    @classmethod
    def validate_target_value_ids(cls, value_ids: list[int]) -> list[int]:
        return TagAssignmentReplaceRequest.validate_value_ids(value_ids)


class TagAssignmentBulkReplaceRequest(BaseModel):
    """Explicit resource targets for one resource-type bulk replacement."""

    targets: list[TagAssignmentBulkTarget] = Field(..., min_length=1)


class TagAssignmentBulkOutcome(BaseModel):
    resource_id: str
    outcome: Literal["updated", "not_found_or_forbidden", "validation"]
    assignment: TagAssignmentResponse | None = None
    message: str | None = None
    details: dict[str, Any] | None = None


class TagAssignmentFilter(BaseModel):
    """One definition predicate; callers combine predicates with AND."""

    definition_id: int = Field(..., gt=0)
    value_ids: list[int] = Field(..., min_length=1)

    @field_validator("value_ids")
    @classmethod
    def validate_filter_value_ids(cls, value_ids: list[int]) -> list[int]:
        return TagAssignmentReplaceRequest.validate_value_ids(value_ids)


class TagResourceFilterRequest(BaseModel):
    """Filter already-authorized non-document resource ids by tag predicates.

    Callers supply the resource ids their own list flow has already authorized;
    the tag service narrows that set to resources matching every predicate
    (OR within a definition, AND across definitions). It never widens scope or
    returns resources the caller could not already see.
    """

    model_config = ConfigDict(extra="forbid")

    resource_ids: list[str] = Field(..., min_length=1, max_length=500)
    predicates: list[TagAssignmentFilter] = Field(default_factory=list)

    @field_validator("resource_ids")
    @classmethod
    def validate_filter_resource_ids(cls, resource_ids: list[str]) -> list[str]:
        normalized = []
        for resource_id in resource_ids:
            value = str(resource_id).strip()
            if not value:
                raise ValueError("resource_ids must not contain empty values")
            normalized.append(value)
        return list(dict.fromkeys(normalized))


class TagResourceFilterResponse(BaseModel):
    """Resource ids from the caller's authorized set that match the predicates."""

    resource_type: str
    matched_resource_ids: list[str] = Field(default_factory=list)


class TagDocumentBatchStatusRequest(BaseModel):
    """Batch document tag status for one provider knowledge base."""

    model_config = ConfigDict(extra="forbid")

    document_ids: list[str] = Field(..., min_length=1, max_length=200)
    predicates: list[TagAssignmentFilter] = Field(default_factory=list)

    @field_validator("document_ids")
    @classmethod
    def validate_document_ids(cls, document_ids: list[str]) -> list[str]:
        normalized = []
        for document_id in document_ids:
            value = str(document_id).strip()
            if not value:
                raise ValueError("document_ids must not contain empty values")
            normalized.append(value)
        return list(dict.fromkeys(normalized))


class TagDocumentBatchStatusResponse(BaseModel):
    """One document's tag assignment and provider projection summary."""

    document_id: str
    assignment_count: int = 0
    projection_status: TagDocumentProjectionStatusResponse | None = None


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


TAG_CONFLICT_RESPONSES = {409: {"model": TagHTTPConflictResponse}}
