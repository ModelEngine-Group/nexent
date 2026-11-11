# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Validation contracts for administrator trajectory queries."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)


class RecordsQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    view: Literal["execution", "conversation"] = "execution"
    tenant_id: str | None = Field(None, min_length=1, max_length=128)
    target_user_id: str | None = Field(None, min_length=1, max_length=128)
    agent_id: str | None = None
    conversation_id: str | None = None
    model: str | None = Field(None, max_length=200)
    status: Literal["success", "error", "not_captured", "expired"] | None = None
    started_from: str | None = None
    started_to: str | None = None
    id_query: str = Field("", max_length=200)
    sort_by: Literal["started_at", "duration_ms", "total_tokens"] = "started_at"
    sort_order: Literal["asc", "desc"] = "desc"
    page: int = Field(1, ge=1, le=1_000_000)
    page_size: int = Field(10, ge=1, le=100)
    query_id: str | None = Field(None, max_length=8192)
    facet: Literal["tenants", "users", "agents", "conversations", "models"] | None = None
    search: str = Field("", max_length=200)
    cursor: str | None = Field(None, max_length=8192)
    limit: int = Field(20, ge=1, le=100)

    @field_validator("agent_id", "conversation_id")
    @classmethod
    def validate_id(cls, value):
        if value is not None:
            from infrastructure.observability.trajectory_store import business_id

            business_id(value)
        return value

    @field_validator("started_from", "started_to")
    @classmethod
    def validate_time(cls, value):
        if value is None:
            return value
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError("Time must include a timezone")
        return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")

    @field_validator("id_query")
    @classmethod
    def normalize_search(cls, value):
        return value.strip().casefold()

    @model_validator(mode="after")
    def validate_range(self):
        if self.view != "conversation" and self.status in {"not_captured", "expired"}:
            raise ValueError("Availability filters require the conversation view")
        if (
            self.started_from
            and self.started_to
            and datetime.fromisoformat(self.started_from) > datetime.fromisoformat(self.started_to)
        ):
            raise ValueError("Start must not exceed end")
        return self

    @property
    def filters(self):
        return self.model_dump(
            include={
                "tenant_id",
                "target_user_id",
                "agent_id",
                "conversation_id",
                "model",
                "status",
                "started_from",
                "started_to",
                "id_query",
            },
            exclude_none=True,
        )


class CleanupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    before_days: StrictInt = Field(ge=1, le=3650)
    cursor: str | None = Field(None, max_length=8192)
