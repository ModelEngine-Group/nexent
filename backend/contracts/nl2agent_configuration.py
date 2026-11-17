# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Allowlisted inputs for ordinary NL2Agent configuration."""

import re
from typing import Annotated, Literal

from nexent.core.agents.agent_model import GuardrailRule
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

ConfigurationSection = Literal["model", "collaborators", "permissions", "tags", "guardrails", "advanced"]
Id = Annotated[int, Field(strict=True, gt=0)]


class ConfigPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def reject_empty_or_null(cls, value):
        if not isinstance(value, dict) or not value or any(item is None for item in value.values()):
            raise ValueError("Supply explicit non-null changes")
        return value


class ModelPatch(ConfigPatch):
    model_ids: list[Id] = Field(min_length=1, max_length=5)


class CollaborationTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: Id
    version_no: Annotated[int, Field(strict=True, ge=0)] | None = None


class CollaborationPatch(ConfigPatch):
    add: list[CollaborationTarget] = Field(default_factory=list, max_length=100)
    remove: list[Id] = Field(default_factory=list, max_length=100)


class PermissionPatch(ConfigPatch):
    group_ids: list[Id] | None = Field(default=None, max_length=100)
    ingroup_permission: Literal["PRIVATE", "READ_ONLY", "EDIT"] | None = None
    is_main_agent: StrictBool | None = None
    is_a2a: StrictBool | None = None


class TagPatch(ConfigPatch):
    add: list[Id] = Field(default_factory=list, max_length=100)
    remove: list[Id] = Field(default_factory=list, max_length=100)


class SafeGuardrailRule(GuardrailRule):
    model_config = ConfigDict(extra="forbid")

    @field_validator("name", "pattern")
    @classmethod
    def validate_rule_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A rule needs a name and pattern")
        return value

    @field_validator("pattern")
    @classmethod
    def validate_regex(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError("Invalid guardrail pattern") from exc
        return value


class GuardrailPatch(ConfigPatch):
    enabled: StrictBool | None = None
    upsert_rules: list[SafeGuardrailRule] = Field(default_factory=list, max_length=100)
    remove_rules: list[str] = Field(default_factory=list, max_length=100)


class AdvancedPatch(ConfigPatch):
    max_steps: Id | None = None
    provide_run_summary: StrictBool | None = None
    allow_chat_metadata: StrictBool | None = None
    enable_protocol_repair_retry: StrictBool | None = None
    self_verification_enabled: StrictBool | None = None


PATCH_MODELS = {
    "model": ModelPatch,
    "collaborators": CollaborationPatch,
    "permissions": PermissionPatch,
    "tags": TagPatch,
    "guardrails": GuardrailPatch,
    "advanced": AdvancedPatch,
}
