# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.evolution import ToolUseRule


class ToolRepairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    tool_name: str = Field(min_length=1, max_length=180)
    failure_case_id: int = Field(gt=0)
    protection_case_id: int = Field(gt=0)
    repeat_experiment_id: int = Field(gt=0)
    goal: str = Field(min_length=1, max_length=1500)
    share_tool_examples: Literal[True]

    @model_validator(mode="after")
    def separate_cases(self):
        if self.failure_case_id == self.protection_case_id:
            raise ValueError("Choose separate failure and protection tasks")
        return self


class ToolReproductionSuite(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    format: Literal["nexent-mcp-repair-v1"]
    failure: ToolUseRule
    protection: ToolUseRule

    @model_validator(mode="after")
    def paired_contract(self):
        if self.failure.name != self.protection.name:
            raise ValueError("Both tasks must exercise the same remote tool")
        for rule in (self.failure, self.protection):
            if (
                not rule.expected_mcp_reply
                or not rule.expected_mcp_reply.fixture
                or (rule.min_calls, rule.max_calls) != (1, 1)
            ):
                raise ValueError("Each task must declare one remote call and independent initial/final state")
        return self
