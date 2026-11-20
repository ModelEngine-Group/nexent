# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Contracts for the unified repository review API, independent of legacy APIs."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
)

ResourceType = Literal["agent", "skill", "mcp"]
ReviewStatus = Literal["pending_review", "approved", "rejected"]
RepositoryId = Annotated[str, Field(pattern=r"^[1-9][0-9]{0,18}$")]


class ReviewListQuery(BaseModel):
    """Use one page across all authorized resource branches."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    resource_type: Literal["all", "agent", "skill", "mcp"] = Field("all", alias="type")
    status: Literal["all", "pending_review", "approved", "rejected"] = "all"
    search: str = ""
    page: int = Field(1, ge=1)
    page_size: int = Field(10, ge=1, le=100)

    @field_validator("search")
    @classmethod
    def trim_search(cls, value: str) -> str:
        return value.strip()


class ReviewDecisionRequest(BaseModel):
    """Never accept a client-selected user, tenant, role or query scope."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    decision: Literal["approve", "reject"]
    reason: str | None = None

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if len(value) > 1000:
            raise ValueError(
                "Review reason must contain at most 1000 Unicode code points"
            )
        return value or None


class ReviewSubmitter(BaseModel):
    """Display identity must not be substituted with the resource author."""

    user_id: str | None = None
    display_name: str | None = None
    cas_username: str | None = None


class ReviewListItem(BaseModel):
    """Public projection without archives, credentials or mutable source config."""

    resource_type: ResourceType
    review_id: RepositoryId
    source_resource_id: RepositoryId
    version_no: int | None = None
    repository_id: RepositoryId | None = None
    tenant_id: str
    tenant_name: str | None = None
    name: str
    description: str | None = None
    version_label: str | None = None
    status: ReviewStatus
    submitter: ReviewSubmitter
    submitted_user_id: str | None = None
    submitted_at: datetime | None = None
    published_at: datetime | None = None
    submit_description: str | None = None
    review_comment: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    current_repository_status: str | None = None
    allowed_actions: list[Literal["approve", "reject"]] = Field(default_factory=list)

    @field_validator("review_id", "source_resource_id", "repository_id")
    @classmethod
    def check_repository_id(cls, value: str) -> str:
        if value is not None and int(value) > 9223372036854775807:
            raise ValueError("Repository ID exceeds the signed BIGINT range")
        return value


class ReviewPagination(BaseModel):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)

    @computed_field
    @property
    def total_pages(self) -> int:
        return (self.total + self.page_size - 1) // self.page_size


class ReviewListResponse(BaseModel):
    items: list[ReviewListItem]
    pagination: ReviewPagination


class ReviewSubmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_type: ResourceType
    source_resource_id: RepositoryId
    version_no: int | None = Field(None, ge=0)
    submit_description: str | None = None
    listing_fields: dict = Field(default_factory=dict)

    @field_validator("source_resource_id")
    @classmethod
    def validate_source_id(cls, value):
        if int(value) > 2147483647:
            raise ValueError("Source ID exceeds supported local identifier range")
        return value
