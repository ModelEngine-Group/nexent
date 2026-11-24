# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Development-only evidence and local edits for a published business prompt."""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, JsonValue, field_validator, model_validator
from contracts.replay_files import FileStateCheck, TextFiles


class PublicBenchmarkRequest(BaseModel):
    """Aggregate results supplied by an external public-benchmark run."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)

    dataset: str = Field(min_length=1, max_length=128)
    revision: str = Field(min_length=1, max_length=128)
    subset: str = Field(min_length=1, max_length=128)
    scoring_protocol: str = Field(min_length=1, max_length=512)
    adaptation: str = Field(default="", max_length=512)
    run_reference: str = Field(default="", max_length=512)
    metric: str = Field(min_length=1, max_length=80)
    sample_count: int = Field(gt=0, le=2_147_483_647)
    baseline_score: FiniteFloat
    candidate_score: FiniteFloat


class DevelopmentFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    example_id: str = Field(min_length=1, max_length=128)
    expected: str = Field(min_length=1, max_length=3000)
    observed: str = Field(min_length=1, max_length=3000)
    tool_evidence: str | None = Field(default=None, max_length=5000, exclude_if=lambda v: v is None)
    input_excerpt: str | None = Field(default=None, max_length=1500, exclude_if=lambda v: v is None)


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
    related_passage: str | None = Field(default=None, min_length=1, max_length=2000, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def related_passage_is_for_conflict(self):
        if self.related_passage is not None and self.method != "P3":
            raise ValueError("Select a related clause only when resolving a prompt conflict")
        return self


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


class MCPFixtureState(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    initial: dict[str, JsonValue]
    final: dict[str, JsonValue]


class ExpectedMCPReply(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    kind: Literal["text", "structured"]
    value: str | dict[str, JsonValue]
    error: bool = Field(default=False, exclude_if=lambda v: not v)
    fixture: MCPFixtureState | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def matches_kind(self):
        if (self.kind == "text") != isinstance(self.value, str):
            raise ValueError("Provide one text response or a structured JSON object")
        if len(json.dumps(self.model_dump(), ensure_ascii=False, allow_nan=False).encode()) > 65536:
            raise ValueError("The expected tool response exceeds 64 KiB")
        return self


class ToolUseRule(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    name: str = Field(min_length=1, max_length=180, pattern=r"^\S+$")
    min_calls: int = Field(default=1, ge=0, le=512)
    max_calls: int | None = Field(default=None, ge=0, le=512)
    expected_mcp_reply: ExpectedMCPReply | None = Field(default=None, exclude_if=lambda v: v is None)
    expected_script_files: TextFiles | None = Field(default=None, exclude_if=lambda v: v is None)
    expected_script_stdout: str | None = Field(default=None, max_length=16384, exclude_if=lambda v: v is None)
    arguments: dict[str, JsonValue] = Field(default_factory=dict, max_length=32)

    @model_validator(mode="after")
    def valid_bounds(self):
        if self.expected_mcp_reply is not None:
            from nexent.core.agents.resources.tool_user_context import USER_CONTEXT_FIELDS
            if (self.min_calls < 1 or set(self.arguments).intersection(USER_CONTEXT_FIELDS)
                    or self.expected_script_files is not None or self.expected_script_stdout is not None):
                raise ValueError("An MCP reply check requires a remote tool call and business arguments")
        if self.expected_script_stdout is not None or self.expected_script_files is not None:
            import shlex
            if (self.name != "run_skill_script" or self.arguments.get("source", "skill") != "skill"
                    or not all(isinstance(self.arguments.get(k), str) and self.arguments[k].strip()
                               for k in ("skill_name", "script_path"))
                    or not isinstance(self.arguments.get("params", ""), str) or self.min_calls < 1):
                raise ValueError("A script check requires a bundled Skill, script path and at least one call")
            shlex.split(self.arguments.get("params", ""))
        if self.max_calls is not None and self.max_calls < self.min_calls:
            raise ValueError("Maximum call count must cover the minimum")
        if any(not key.strip() or len(key) > 128 for key in self.arguments):
            raise ValueError("Invalid tool argument name")
        return self


class ToolUseExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    rules: list[ToolUseRule] = Field(min_length=1, max_length=32)
    order: list[str] | None = Field(default=None, min_length=2, max_length=512)

    @model_validator(mode="after")
    def distinct_rules(self):
        names = {r.name for r in self.rules}
        if len(names) != len(self.rules) or self.order and not set(self.order).issubset(names):
            raise ValueError("Specify one rule per tool and order only named tools")
        if self.order:
            for rule in self.rules:
                if rule.name in self.order:
                    count = self.order.count(rule.name)
                    if count < rule.min_calls or rule.max_calls is not None and count > rule.max_calls:
                        raise ValueError("Tool order contradicts its call-count rule")
        return self


class TraceCaseApproval(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    turn_id: int = Field(gt=0)
    draft_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    purpose: Literal["reproduce", "protect"]
    inputs_reviewed: Literal[True]
    tools_require_no_reset: bool = False
    use_previous_task: bool = False
    preceding_turns: int = Field(default=0, ge=0, le=15)
    unused_attachment_slots: list[int] = Field(default_factory=list, max_length=32)

    @field_validator("unused_attachment_slots")
    @classmethod
    def distinct_source_slots(cls, values):
        if any(slot < 1 for slot in values) or len(values) != len(set(values)):
            raise ValueError("Choose distinct positive source attachment numbers")
        return values


class ReplayFollowup(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=16000)
    attachment_names: list[str] = Field(default_factory=list, max_length=32)


class ReplayCaseRequest(BaseModel):
    """A business-approved development task. Only the query and files reach the Agent."""

    model_config = ConfigDict(extra="forbid", strict=True)
    agent_id: int = Field(gt=0)
    version_no: int = Field(gt=0)
    family: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=16000)
    expected: str = Field(min_length=1, max_length=16000)
    attachments: list[ReplayAttachmentSource] = Field(default_factory=list, max_length=32)
    followups: list[ReplayFollowup] = Field(default_factory=list, max_length=15)
    source_group: str | None = Field(default=None, min_length=1, max_length=128)
    expected_skill_names: list[str] | None = Field(default=None, max_length=32)
    tool_use: ToolUseExpectation | None = None
    file_state: FileStateCheck | None = None
    trace: TraceCaseApproval | None = None

    @model_validator(mode="after")
    def check_inputs(self):
        if self.expected_skill_names is not None and (
                len(set(self.expected_skill_names)) != len(self.expected_skill_names)
                or any(not name.strip() or len(name) > 100 for name in self.expected_skill_names)):
            raise ValueError("Expected Skill names must be distinct catalog names")
        names = [file.name.casefold() for file in self.attachments]
        if len(set(names)) != len(names):
            raise ValueError("Each attachment must have a distinct filename")
        later = [name for turn in self.followups for name in turn.attachment_names]
        if len(set(later)) != len(later) or set(later).difference(file.name for file in self.attachments):
            raise ValueError("Assign each approved attachment to its first turn of use")
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


class RegressionMembershipRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool
    evaluator_id: int | None = Field(default=None, gt=0)
    judge_model_id: int | None = Field(default=None, gt=0)
    language: Literal["zh", "en"] = "zh"


class EvaluatedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    experiment_id: int = Field(gt=0)
    candidate_type: Literal["prompt", "tool_set", "skill_step", "skill_discovery"]
    candidate_id: int = Field(gt=0)


class DevelopmentScreening(BaseModel):
    """Criteria chosen before trying the candidate against the development and regression tasks."""

    model_config = ConfigDict(extra="forbid", strict=True)
    target_case_ids: list[int] = Field(min_length=1, max_length=100)
    metric: Literal["tasks_fixed", "skill_choices_fixed", "input_token_reduction_pct"] = "tasks_fixed"
    minimum: int = Field(ge=1, le=100)

    @model_validator(mode="after")
    def check_targets(self):
        if min(self.target_case_ids) <= 0 or len(set(self.target_case_ids)) != len(self.target_case_ids):
            raise ValueError("Choose distinct target tasks")
        if self.metric != "input_token_reduction_pct" and self.minimum > len(self.target_case_ids):
            raise ValueError("The minimum gain exceeds the number of target tasks")
        return self


class DevelopmentRunBudget(BaseModel):
    """Limits for one submitted development experiment, including fixed regression tasks."""

    model_config = ConfigDict(extra="forbid", strict=True)
    max_replay_turns: int = Field(default=1000, ge=1, le=10000)
    max_elapsed_seconds: int = Field(default=3600, ge=1, le=604800)
    max_model_tokens: int | None = Field(default=None, gt=0, le=10**12, exclude_if=lambda v: v is None)
    max_model_micros: int | None = Field(default=None, ge=0, le=10**15, exclude_if=lambda v: v is None)


class DevelopmentExperimentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    suggestion_id: int | None = Field(default=None, gt=0, exclude_if=lambda value: value is None)
    suggestion_target_case_id: int | None = Field(default=None, gt=0, exclude_if=lambda value: value is None)
    request_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9._-]+$")
    agent_id: int = Field(gt=0)
    version_no: int = Field(gt=0)
    candidate_type: Literal["prompt", "skill_step", "skill_discovery", "skill_new", "skill_script", "baseline", "tool_set", "tool_mapping", "tool_build", "combination"]
    candidate_id: int | None = Field(default=None, gt=0, exclude_if=lambda v: v is None)
    components: list[EvaluatedCandidate] | None = Field(default=None, min_length=2, max_length=2, exclude_if=lambda v: v is None)
    case_ids: list[int] = Field(min_length=1, max_length=100)
    evaluator_id: int = Field(gt=0)
    judge_model_id: int | None = Field(default=None, gt=0)
    language: Literal["en", "zh"] = "zh"
    timeout_seconds: int = Field(default=300, ge=1, le=3600)
    screening: DevelopmentScreening | None = Field(default=None, exclude_if=lambda value: value is None)

    budget: DevelopmentRunBudget | None = Field(default=None, exclude_if=lambda value: value is None)

    def evaluates_skill_choices(self):
        return self.candidate_type in {"skill_discovery", "skill_new"} or any(
            part.candidate_type == "skill_discovery" for part in self.components or ()
        )

    @field_validator("case_ids")
    @classmethod
    def unique_cases(cls, values):
        if min(values) < 1 or len(values) != len(set(values)):
            raise ValueError("Select distinct, confirmed development tasks")
        return values

    @model_validator(mode="after")
    def check_suggestion_cases(self):
        if self.screening and (self.candidate_type == "baseline" or
                               set(self.screening.target_case_ids).difference(self.case_ids)):
            raise ValueError("Screen a candidate against targets from the selected development tasks")
        if self.screening and self.screening.metric == "skill_choices_fixed" and self.candidate_type != "skill_discovery":
            raise ValueError("The Skill selection metric requires a discovery description candidate")
        combined = self.candidate_type == "combination"
        if combined != (self.components is not None):
            raise ValueError("Select exactly two evaluated revisions for a combination")
        if self.components:
            a, b = self.components
            if (a.experiment_id == b.experiment_id or a.candidate_type == b.candidate_type
                    and (a.candidate_type in {"prompt", "tool_set"} or a.candidate_id == b.candidate_id)):
                raise ValueError("Select two revisions of different resources")
        if (self.candidate_type in {"baseline", "combination"}) != (self.candidate_id is None):
            raise ValueError("Select a candidate only when comparing a change")
        if self.candidate_type in {"baseline", "combination"} and self.suggestion_id is not None:
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
    input_excerpt: str | None = Field(default=None, min_length=1, max_length=1500)


class FeedbackHandoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    method: Literal["P1", "P3", "T1", "T2", "S2"]
    skill_id: int | None = Field(default=None, gt=0)
    released_guide_candidate_id: int | None = Field(default=None, gt=0)
    goal: str = Field(min_length=1, max_length=1500)
    source_passage: str = Field(min_length=1, max_length=2000)
    related_passage: str | None = Field(default=None, min_length=1, max_length=2000)
    failure: FeedbackExcerpt
    protection: FeedbackExcerpt
    tool_name: str | None = Field(default=None, min_length=1, max_length=180)
    share_expected_arguments: list[str] = Field(default_factory=list, max_length=32)
    share_file_state: bool = False

    @model_validator(mode="after")
    def valid_resource(self):
        if self.related_passage is not None and self.method != "P3":
            raise ValueError("Select a related clause only when resolving a prompt conflict")
        if self.share_file_state and (self.method not in {"T1", "T2"} or not self.tool_name):
            raise ValueError("Choose a measured tool before sharing its file checks")
        if self.tool_name and self.method not in {"T1", "T2"}:
            raise ValueError("Select a tool only for a tool-call improvement")
        if self.share_expected_arguments and (self.method != "T2" or not self.tool_name):
            raise ValueError("Choose a tool parameter improvement to share expected argument values")
        skill_targets = sum(target is not None for target in (self.skill_id, self.released_guide_candidate_id))
        if skill_targets != int(self.method == "S2"):
            raise ValueError("Select exactly one bound Skill for an S2 handoff")
        if self.failure.case_id == self.protection.case_id:
            raise ValueError("Failure and protection tasks must be distinct")
        return self


class GenerateFromFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model_id: int = Field(gt=0)


class ToolMappingProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    failure_case_id: int = Field(gt=0)
    protection_case_id: int = Field(gt=0)
    tool_name: str = Field(min_length=1, max_length=180)
    field: str = Field(min_length=1, max_length=128)
    supplied_value: str = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def separate_examples(self):
        if self.failure_case_id == self.protection_case_id:
            raise ValueError("The protection case must differ from the failure")
        return self


class ToolSetProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    failure_case_ids: list[int] = Field(min_length=1, max_length=16)
    protection_case_ids: list[int] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def independent_examples(self):
        cases = self.failure_case_ids + self.protection_case_ids
        if min(cases) < 1 or len(set(cases)) != len(cases):
            raise ValueError("Select distinct failure and protection tasks")
        return self


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
