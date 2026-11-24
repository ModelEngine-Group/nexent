# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Inputs accepted by the versioned NL2Agent resource workflow."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints, model_validator

MAX_REQUIREMENTS = 8
MAX_CANDIDATES_PER_RECALL_ROUTE = 3
MAX_CANDIDATES_PER_SOURCE = 3
MAX_REQUIREMENTS_PER_VERIFICATION_BATCH = 4
MAX_REFS_PER_REQUIREMENT_BATCH = 2 * MAX_CANDIDATES_PER_SOURCE
RESOURCE_PREPARATION_TIMEOUT = 120.0
RESOURCE_SEARCH_TIMEOUT = 10.0
# Leave room for catalog authorization and result handling around both phases.
RESOURCE_MCP_TOOL_TIMEOUT = RESOURCE_PREPARATION_TIMEOUT + RESOURCE_SEARCH_TIMEOUT + 20.0

RequirementQuery = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
SearchQuery = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
ResourcePurpose = Literal["recommend", "bind", "generate"]
ResourceCardType = Literal["requirement_resources", "requirement_clarification",
                           "installed_resource_binding"]


class RequirementInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: RequirementQuery
    # Retained for older callers. Every requirement in the submitted list needs coverage.
    required: StrictBool = True


class BilingualSearchQueries(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zh: SearchQuery
    en: SearchQuery


class RequirementDiscoveryInput(RequirementInput):
    search_query: SearchQuery | None = None
    search_queries: BilingualSearchQueries | None = None


class RequirementEdit(RequirementInput):
    requirement_id: Identifier | None = None
    client_key: Identifier | None = None

    @model_validator(mode="after")
    def require_one_identifier(self):
        if (self.requirement_id is None) == (self.client_key is None):
            raise ValueError("Exactly one requirement_id or client_key is required")
        return self


class CandidateAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_ref: Identifier
    satisfies: StrictBool
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class VerificationCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: Identifier
    checked: list[Identifier] | None = Field(default=None, max_length=MAX_REFS_PER_REQUIREMENT_BATCH)
    accepted: list[Identifier] = Field(max_length=MAX_REFS_PER_REQUIREMENT_BATCH)
    # Optional only for requirements already in flight before independent assessment.
    assessments: list[CandidateAssessment] | None = Field(default=None, max_length=MAX_REFS_PER_REQUIREMENT_BATCH)


class ResourceCardAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    card_id: Identifier
    state_version: int = Field(strict=True, ge=1)
    requirements: list[RequirementEdit] | None = Field(default=None, max_length=MAX_REQUIREMENTS)
    selected_resource_refs: list[Identifier] | None = None

    @model_validator(mode="after")
    def reject_duplicates(self):
        ids = [row.requirement_id or row.client_key for row in self.requirements or []]
        refs = self.selected_resource_refs or []
        if len(ids) != len(set(ids)) or len(refs) != len(set(refs)):
            raise ValueError("Duplicate requirement or resource reference")
        return self


class ResourceInstallationRequest(ResourceCardAction):
    agent_id: int = Field(strict=True, gt=0)
    conversation_id: int = Field(strict=True, gt=0)
    requirement_id: Identifier
    candidate_ref: Identifier


class KnowledgeRecommendationsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: int = Field(strict=True, gt=0)
    conversation_id: int = Field(strict=True, gt=0)
    card_id: Identifier
    state_version: int = Field(strict=True, ge=1)


class ResourceInstallationAttemptRequest(ResourceInstallationRequest):
    operation: Literal["claim", "check", "release"]
    target_name: Identifier | None = None
    attempt_id: Identifier | None = None


class ResourceLinkRequest(ResourceCardAction):
    agent_id: int = Field(strict=True, gt=0)
    conversation_id: int = Field(strict=True, gt=0)
    requirement_id: Identifier | None = None
    client_key: Identifier | None = None
    candidate_ref: Identifier | None = None
    resource_type: Literal["skill", "mcp_server", "tool"]
    resource_id: int = Field(strict=True, gt=0)

    @model_validator(mode="after")
    def validate_link_target(self):
        if (self.requirement_id is None) == (self.client_key is None):
            raise ValueError("Exactly one requirement_id or client_key is required")
        if self.candidate_ref is not None and self.requirement_id is None:
            raise ValueError("A recommendation requires a confirmed requirement")
        return self
