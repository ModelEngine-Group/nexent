# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Development-only evidence and local edits for a published business prompt."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DevelopmentFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    example_id: str = Field(min_length=1, max_length=128)
    expected: str = Field(min_length=1, max_length=3000)
    observed: str = Field(min_length=1, max_length=3000)


class LocalEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    model_id: int = Field(gt=0)
    source_passage: str = Field(min_length=1, max_length=2000)
    goal: str = Field(min_length=1, max_length=1500)
    failure: DevelopmentFeedback
    protection: DevelopmentFeedback

    @model_validator(mode="after")
    def distinct_development_examples(self):
        if self.failure.example_id == self.protection.example_id:
            raise ValueError("The target and protection examples must be distinct")
        return self


class PromptCandidateRequest(LocalEditRequest):
    agent_id: int = Field(gt=0)
    version_no: int = Field(gt=0)
    method: Literal["P1", "P3", "T1", "T2"]


class SkillStepCandidateRequest(LocalEditRequest):
    skill_id: int = Field(gt=0)


class ReplayAttachmentSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1, max_length=240)
    object_name: str = Field(min_length=1, max_length=1024)

    @field_validator("name")
    @classmethod
    def portable_filename(cls, value):
        from pathlib import PureWindowsPath
        if (value in {".", ".."} or value[-1] in " ." or PureWindowsPath(value).is_reserved()
                or any(ord(ch) < 32 or ch in '/\\:*?"<>|' for ch in value)):
            raise ValueError("Invalid attachment filename")
        return value


class ReplayCaseRequest(BaseModel):
    """A business-approved development task. Only the query and files reach the Agent."""

    model_config = ConfigDict(extra="forbid", strict=True)
    agent_id: int = Field(gt=0)
    version_no: int = Field(gt=0)
    family: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=16000)
    expected: str = Field(min_length=1, max_length=16000)
    attachments: list[ReplayAttachmentSource] = Field(default_factory=list, max_length=32)
    source_group: str | None = Field(default=None, min_length=1, max_length=128)
    expected_skill_names: list[str] | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def check_inputs(self):
        if self.expected_skill_names is not None and (
                len(set(self.expected_skill_names)) != len(self.expected_skill_names)
                or any(not name.strip() or len(name) > 100 for name in self.expected_skill_names)):
            raise ValueError("Expected Skill names must be distinct catalog names")
        names = [file.name.casefold() for file in self.attachments]
        if len(set(names)) != len(names):
            raise ValueError("Each attachment must have a distinct filename")
        if not all(value.strip() for value in (self.family, self.query, self.expected)):
            raise ValueError("A family, query and expected outcome are required")
        return self


class PromptExampleSelection(BaseModel):
    """The editor approves only these excerpts for reuse in future prompts."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    case_id: int = Field(gt=0)
    variant: Literal["base", "result"]
    behavior: str = Field(min_length=1, max_length=128)
    input_excerpt: str = Field(min_length=1, max_length=1200)
    attachment_name: str | None = Field(default=None, min_length=1, max_length=240)
    output_excerpt: str = Field(min_length=1, max_length=1200)


class ExampleCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    target_case_id: int = Field(gt=0)
    target_behavior: str = Field(min_length=1, max_length=128)
    examples: list[PromptExampleSelection] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def distinct_cases(self):
        if len({example.case_id for example in self.examples}) != len(self.examples):
            raise ValueError("Approve one demonstration per case")
        return self


class PromptEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    old: str = Field(min_length=1, max_length=2000)
    new: str = Field(max_length=3000)
    reason: str = Field(min_length=1, max_length=1000)
    evidence_ids: list[str] = Field(min_length=2, max_length=2)


class DevelopmentExperimentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    suggestion_id: int | None = Field(default=None, gt=0, exclude_if=lambda value: value is None)
    suggestion_target_case_id: int | None = Field(default=None, gt=0, exclude_if=lambda value: value is None)
    request_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9._-]+$")
    agent_id: int = Field(gt=0)
    version_no: int = Field(gt=0)
    candidate_type: Literal["prompt", "skill_step", "skill_discovery", "baseline"]
    candidate_id: int | None = Field(default=None, gt=0, exclude_if=lambda v: v is None)
    case_ids: list[int] = Field(min_length=1, max_length=100)
    evaluator_id: int = Field(gt=0)
    judge_model_id: int | None = Field(default=None, gt=0)
    language: Literal["en", "zh"] = "zh"
    timeout_seconds: int = Field(default=300, ge=1, le=3600)

    @field_validator("case_ids")
    @classmethod
    def unique_cases(cls, values):
        if min(values) < 1 or len(values) != len(set(values)):
            raise ValueError("Select distinct, confirmed development tasks")
        return values

    @model_validator(mode="after")
    def check_suggestion_cases(self):
        if (self.candidate_type == "baseline") != (self.candidate_id is None):
            raise ValueError("Select a candidate only when comparing a change")
        if self.candidate_type == "baseline" and self.suggestion_id is not None:
            raise ValueError("A suggestion trial requires a candidate")
        if self.suggestion_id is not None and len(self.case_ids) < 2:
            raise ValueError("Include the target and a protection task for a Skill suggestion")
        if self.suggestion_target_case_id is not None and (
                self.suggestion_id is None or self.suggestion_target_case_id not in self.case_ids):
            raise ValueError("The suggestion target must be one of the selected tasks")
        return self


class FeedbackExcerpt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    case_id: int = Field(gt=0)
    expected: str = Field(min_length=1, max_length=3000)
    observed: str = Field(max_length=3000)


class FeedbackHandoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    method: Literal["P1", "P3", "T1", "T2", "S2"]
    skill_id: int | None = Field(default=None, gt=0)
    goal: str = Field(min_length=1, max_length=1500)
    source_passage: str = Field(min_length=1, max_length=2000)
    failure: FeedbackExcerpt
    protection: FeedbackExcerpt

    @model_validator(mode="after")
    def valid_resource(self):
        if (self.method == "S2") != (self.skill_id is not None):
            raise ValueError("Select a bound Skill only for an S2 handoff")
        if self.failure.case_id == self.protection.case_id:
            raise ValueError("Failure and protection tasks must be distinct")
        return self


class GenerateFromFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model_id: int = Field(gt=0)


class DiscoveryExample(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    case_id: int = Field(gt=0)
    query_excerpt: str = Field(min_length=1, max_length=1500)


class DiscoveryHandoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    method: Literal["S1"]
    skill_id: int = Field(gt=0)
    goal: str = Field(min_length=1, max_length=1500)
    missed: DiscoveryExample
    overused: DiscoveryExample
    correct: DiscoveryExample

    @model_validator(mode="after")
    def distinct_cases(self):
        if len({self.missed.case_id, self.overused.case_id, self.correct.case_id}) != 3:
            raise ValueError("Select three distinct development tasks")
        return self
