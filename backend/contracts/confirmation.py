# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Public fingerprints of private confirmation material, plus its offline input format."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.evolution import ReplayCaseRequest


class PrivateTask(ReplayCaseRequest):
    source_group: str = Field(min_length=1, max_length=128)
    conversation_digest: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def independent_source(self):
        if not self.source_group.strip() or self.trace is not None:
            raise ValueError("Provide an independent source group and only approved offline inputs")
        return self


class ConfirmationCaseFingerprint(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    digest: str = Field(pattern="^[0-9a-f]{64}$")
    sources: list[Annotated[str, Field(pattern=r"^(group|conversation|file|file-state|query):[0-9a-f]{64}$")]] = Field(
        min_length=1, max_length=40)

    @model_validator(mode="after")
    def grouped_sources(self):
        if (len(set(self.sources)) != len(self.sources) or not any(k.startswith("group:") for k in self.sources)
                or not any(k.startswith(("query:", "file:")) for k in self.sources)):
            raise ValueError("Supply distinct fingerprints for the source group and original input")
        return self


class ConfirmationManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    format: Literal["nexent-confirmation-v1"]
    agent_id: int = Field(gt=0)
    version_no: int = Field(gt=0)
    cases: list[ConfirmationCaseFingerprint] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique_tasks(self):
        if len({case.digest for case in self.cases}) != len(self.cases):
            raise ValueError("Duplicate confirmation task")
        return self

    def canonical(self):
        return {**self.model_dump(exclude={"cases"}), "cases":[{"digest":case.digest, "sources":sorted(case.sources)}
                for case in sorted(self.cases, key=lambda c: c.digest)]}


class CuratorGrant(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    user_id: str = Field(min_length=1, max_length=100)
    enabled: bool


class ConfirmationPolicy(BaseModel):
    """Business thresholds agreed before executing the private suite."""

    model_config = ConfigDict(extra="forbid", strict=True)
    minimum_valid_pairs: int = Field(ge=1, le=500)
    minimum_valid_percent: int = Field(ge=1, le=100)
    family_minimums: dict[Annotated[str, Field(min_length=1, max_length=128)], Annotated[int, Field(ge=1, le=500)]] = Field(
        min_length=1, max_length=100)
    minimum_quality_gain_pp: int = Field(ge=-100, le=100)
    minimum_input_saving_percent: int | None = Field(default=None, ge=1, le=100)
    max_regressed_tasks: int = Field(default=0, ge=0, le=500)
    max_candidate_p95_ms: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def check_goal(self):
        if self.minimum_quality_gain_pp <= 0 and self.minimum_input_saving_percent is None:
            raise ValueError("Require a quality gain or an input token saving")
        if any(not family.strip() or family.strip() != family for family in self.family_minimums):
            raise ValueError("Use nonempty business task families without surrounding whitespace")
        return self


class ConfirmationLockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    experiment_id: int = Field(gt=0)
    candidate_digest: str = Field(pattern="^[0-9a-f]{64}$")
    suite_digest: str = Field(pattern="^[0-9a-f]{64}$")
    policy: ConfirmationPolicy
