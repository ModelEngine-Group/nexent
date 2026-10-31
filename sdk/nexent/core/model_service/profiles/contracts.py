# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Strict profile primitives, independent of provider clients and persistence."""

import json
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


SupportStatus = Literal["supported", "unsupported", "unknown"]
NonBlankString = Annotated[str, StringConstraints(pattern=r"\S")]
PositiveTokens = Annotated[int, Field(gt=0)]


class ProfileContract(BaseModel):
    """Reject undeclared fields and coercion at the profile boundary."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class ContextCapabilities(ProfileContract):
    """Effective service limits; missing limits remain unknown."""

    combined_window: PositiveTokens | None = None
    input_limit: PositiveTokens | None = None
    output_limit: PositiveTokens | None = None

    @model_validator(mode="after")
    def validate_limits(self) -> Self:
        if self.combined_window is not None:
            for limit in (self.input_limit, self.output_limit):
                if limit is not None and limit > self.combined_window:
                    raise ValueError("Service limits cannot exceed the combined context window")
        return self


class ToggleControl(ProfileContract):
    """Explicitly supported thinking switch values, not the current setting."""

    mode: Literal["toggle"] = "toggle"
    parameter_key: Literal["enable_thinking"] = "enable_thinking"
    values: list[bool] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_values(self) -> Self:
        if len(set(self.values)) != len(self.values):
            raise ValueError("Toggle values must be unique")
        return self


class EffortControl(ProfileContract):
    """Provider-declared effort values; no universal effort enum is inferred."""

    mode: Literal["effort"] = "effort"
    parameter_key: Literal["reasoning_effort"] = "reasoning_effort"
    values: list[NonBlankString | None] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_values(self) -> Self:
        if len(set(self.values)) != len(self.values):
            raise ValueError("Effort values must be unique")
        return self


class BudgetTokensControl(ProfileContract):
    """Known or unknown token bounds and explicitly declared sentinel values."""

    mode: Literal["budget_tokens"] = "budget_tokens"
    parameter_key: Literal["reasoning_budget_tokens"] = "reasoning_budget_tokens"
    min: Annotated[int, Field(ge=0)] | None = None
    max: Annotated[int, Field(ge=0)] | None = None
    special_values: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("Budget minimum cannot exceed maximum")
        if len(set(self.special_values)) != len(self.special_values):
            raise ValueError("Special budget values must be unique")
        return self


ReasoningControl = Annotated[ToggleControl | EffortControl | BudgetTokensControl, Field(discriminator="mode")]


class ReasoningCapabilities(ProfileContract):
    """Capability declarations with unknown distinct from unsupported."""

    status: SupportStatus = "unknown"
    controls: list[ReasoningControl] | None = None
    response_paths: list[NonBlankString] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_controls(self) -> Self:
        if self.status == "unsupported" and (self.controls or self.response_paths):
            raise ValueError("Unsupported reasoning cannot declare controls or response paths")
        if len(set(self.response_paths)) != len(self.response_paths):
            raise ValueError("Reasoning response paths must be unique")
        if self.controls is not None:
            modes = [control.mode for control in self.controls]
            keys = [control.parameter_key for control in self.controls]
            if len(set(modes)) != len(modes) or len(set(keys)) != len(keys):
                raise ValueError("Reasoning control modes and parameter keys must be unique")
            encoded = json.dumps(
                [control.model_dump(mode="json") for control in self.controls],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            if len(encoded) > 64 * 1024:
                raise ValueError("Reasoning controls exceed the 64 KiB UTF-8 limit")
        return self


class AtomicProfileReference(ProfileContract):
    """Provenance only; runtime loading never recomposes from this reference."""

    key: NonBlankString
    catalog_revision: NonBlankString
    file_path: NonBlankString
    content_sha256: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]

    @model_validator(mode="after")
    def validate_source_path(self) -> Self:
        parts = self.file_path.split("/")
        if (
            "\\" in self.file_path
            or ":" in self.file_path
            or any(ord(character) < 32 for character in self.file_path)
            or any(part in ("", ".", "..") for part in parts)
        ):
            raise ValueError("Source paths must be canonical relative POSIX paths")
        return self


class VersionedReference(ProfileContract):
    """An explicit registry identity; never a dynamic import path."""

    ref: NonBlankString
    version: Annotated[int, Field(gt=0)]


class InstructionRoleMappings(ProfileContract):
    """All Nexent semantic instruction/resource categories need explicit targets."""

    platform_instruction: NonBlankString
    application_instruction: NonBlankString
    user_input: NonBlankString
    assistant_history: NonBlankString
    tool_result: NonBlankString
    reference_data: NonBlankString


class InstructionMappingDefinition(ProfileContract):
    """Extensible declaration; execution requires a matching registered strategy."""

    strategy_id: NonBlankString
    strategy_version: Annotated[int, Field(gt=0)]
    instruction_hierarchy: list[NonBlankString]
    supported_roles: list[NonBlankString]
    mappings: InstructionRoleMappings
    ordering: list[NonBlankString]
    reference_placement: NonBlankString

    @model_validator(mode="after")
    def validate_declared_roles(self) -> Self:
        for values in (self.instruction_hierarchy, self.supported_roles, self.ordering):
            if not values or len(set(values)) != len(values):
                raise ValueError("Instruction lists must be nonempty and unique")
        if not set(self.instruction_hierarchy) <= set(self.supported_roles):
            raise ValueError("Instruction hierarchy must use supported roles")
        if not set(self.mappings.model_dump().values()) <= set(self.supported_roles):
            raise ValueError("All semantic roles require supported targets")
        return self


class CapabilityFlag(ProfileContract):
    """Missing capability evidence stays unknown."""

    status: SupportStatus = "unknown"


class ToolCapabilities(ProfileContract):
    """Native tool support and explicit registered format/constraint contracts."""

    status: SupportStatus = "unknown"
    schema_constraints: VersionedReference | None = None
    result_format: NonBlankString | None = None


class SamplingCapabilities(ProfileContract):
    """Sampling support is independent of configured numeric parameter values."""

    temperature: CapabilityFlag = Field(default_factory=CapabilityFlag)
    top_p: CapabilityFlag = Field(default_factory=CapabilityFlag)


class ModalityCapabilities(ProfileContract):
    input: list[NonBlankString] | None = None
    output: list[NonBlankString] | None = None

    @model_validator(mode="after")
    def validate_unique_modalities(self) -> Self:
        for values in (self.input, self.output):
            if values is not None and len(set(values)) != len(values):
                raise ValueError("Modalities must be unique")
        return self


class ResponseCapabilities(ProfileContract):
    supported_finish_reasons: list[NonBlankString] | None = None
    stream_format: NonBlankString | None = None

    @model_validator(mode="after")
    def validate_finish_reasons(self) -> Self:
        if self.supported_finish_reasons is not None:
            if len(set(self.supported_finish_reasons)) != len(self.supported_finish_reasons):
                raise ValueError("Finish reasons must be unique")
        return self


class UsageCapabilities(ProfileContract):
    semantics_id: NonBlankString | None = None
    input_includes_cached: SupportStatus = "unknown"
    output_includes_reasoning: SupportStatus = "unknown"


class ProfileCapabilities(ProfileContract):
    """Strict complete groups; unknown controls never become invented defaults."""

    context: ContextCapabilities = Field(default_factory=ContextCapabilities)
    reasoning: ReasoningCapabilities = Field(default_factory=ReasoningCapabilities)
    tools: ToolCapabilities = Field(default_factory=ToolCapabilities)
    sampling: SamplingCapabilities = Field(default_factory=SamplingCapabilities)
    structured_output: CapabilityFlag = Field(default_factory=CapabilityFlag)
    modalities: ModalityCapabilities = Field(default_factory=ModalityCapabilities)
    response: ResponseCapabilities = Field(default_factory=ResponseCapabilities)
    usage: UsageCapabilities = Field(default_factory=UsageCapabilities)
