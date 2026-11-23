# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Validated monitoring events shared by producers and Ops consumers."""

from datetime import timezone
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from infrastructure.monitoring.contracts import MAX_LONG, Fact, Outcome


RunId = Annotated[str, Field(min_length=1, max_length=128)]


class ModelFact(Fact):
    fact_kind: Literal["model"] = "model"
    model_id: int | None = Field(default=None, gt=0, le=2147483647)
    model_type: str = Field(min_length=1, max_length=30)
    error_category: str | None = Field(default=None, pattern=r"^[A-Z0-9_]{1,50}$")
    ttft_ms: int | None = Field(default=None, ge=0, le=MAX_LONG)
    input_tokens: int | None = Field(default=None, ge=0, le=MAX_LONG)
    output_tokens: int | None = Field(default=None, ge=0, le=MAX_LONG)
    total_tokens: int | None = Field(default=None, ge=0, le=MAX_LONG)
    generation_rate: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    trace_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    span_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{16}$")


class AgentFact(Fact):
    fact_kind: Literal["agent"] = "agent"
    root_run_id: RunId
    agent_run_id: RunId
    agent_id: int = Field(gt=0, le=2**31 - 1)
    is_root: bool
    parent_run_id: RunId | None = None
    agent_version_no: int | None = Field(default=None, ge=0, le=2**31 - 1)
    outcome: Outcome | Literal["timed_out"]
    ttft_ms: int | None = Field(default=None, ge=0, le=MAX_LONG)
    execution_started_at: AwareDatetime | None = None

    def partition_anchor(self):
        """Preserve the actual execution's original partition despite earlier preparation."""
        return (self.execution_started_at or self.started_at).astimezone(timezone.utc)

    def statistic_day(self, zone):
        return self.partition_anchor().astimezone(zone).date()

    @model_validator(mode="after")
    def check_run_identity(self):
        if self.fact_id != self.agent_run_id:
            raise ValueError("Agent fact ID must match its run ID")
        if self.is_root:
            if self.root_run_id != self.agent_run_id or self.parent_run_id is not None:
                raise ValueError("Invalid root Agent identity")
        elif self.parent_run_id in {None, self.agent_run_id} or self.root_run_id == self.agent_run_id:
            raise ValueError("Invalid child Agent identity")
        return self


class McpToolFact(Fact):
    fact_kind: Literal["mcp_tool"] = "mcp_tool"
    tool_name: str = Field(min_length=1, max_length=200)
    mcp_server_id: int | None = Field(default=None, gt=0, le=2147483647)
    mcp_server_name: str | None = Field(default=None, max_length=200)
    mcp_server_type: Literal["container", "remote", "api_convert", "builtin", "unknown"]
    error_category: str | None = Field(default=None, pattern=r"^[A-Z0-9_]{1,50}$")
    trace_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    span_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{16}$")


FACT_MODELS = {"model": ModelFact, "mcp_tool": McpToolFact, "agent": AgentFact}
