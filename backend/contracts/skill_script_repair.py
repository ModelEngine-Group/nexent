# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Development evidence and the maintainer's choice of repair author."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScriptRepairFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    skill_id: int = Field(gt=0)
    failure_case_id: int = Field(gt=0)
    protection_case_id: int = Field(gt=0)
    repeat_experiment_id: int = Field(gt=0)
    function: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z_][A-Za-z_0-9]*$")
    goal: str = Field(min_length=1, max_length=1500)
    share_script_examples: Literal[True]

    @model_validator(mode="after")
    def distinct_examples(self):
        if self.failure_case_id == self.protection_case_id:
            raise ValueError("Choose separate failure and protection tasks")
        return self


class ScriptDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model_id: int | None = Field(default=None, gt=0)
    replacement: str | None = Field(default=None, min_length=1, max_length=32768)

    @model_validator(mode="after")
    def one_author(self):
        if (self.model_id is None) == (self.replacement is None):
            raise ValueError("Supply a maintainer edit or choose one drafting model")
        return self
