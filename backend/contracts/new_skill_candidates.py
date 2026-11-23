# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Editor-approved development evidence for a new business Skill."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

Label = Annotated[str, Field(min_length=1, max_length=120)]
Excerpt = Annotated[str, Field(min_length=1, max_length=350)]


class SkillOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    step: Label
    excerpt: Excerpt


class SkillSuccess(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    case_id: int = Field(gt=0)
    outcomes: list[SkillOutcome] = Field(default_factory=list, max_length=16)
    private_values: list[Annotated[str, Field(min_length=2, max_length=160)]] = Field(
        default_factory=list, max_length=20
    )


class CoveredSkillStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    step: Label
    skill: Label
    passage: Excerpt


class NewSkillBriefRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    name: str = Field(pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$", max_length=80)
    creator_id: Label
    purpose: Excerpt
    skip_when: Excerpt
    parameters: list[Label] = Field(max_length=16)
    successes: list[SkillSuccess] = Field(min_length=2, max_length=10)
    counterexample_id: int = Field(gt=0)
    covered: list[CoveredSkillStep] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def distinct_examples(self):
        ids = [s.case_id for s in self.successes] + [self.counterexample_id]
        if len(ids) != len(set(ids)):
            raise ValueError("Select independent successes and a separate counterexample")
        return self
