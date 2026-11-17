# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Agent execution facts for the shared monitoring writer."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from ops.monitoring.contracts import Fact, MonitoringKind, Outcome


RunId = Annotated[str, Field(min_length=1, max_length=128)]


class AgentFact(Fact):
    fact_kind: Literal["agent"] = "agent"
    root_run_id: RunId
    agent_run_id: RunId
    agent_id: int = Field(gt=0, le=2**31 - 1)
    is_root: bool
    parent_run_id: RunId | None = None
    agent_version_no: int | None = Field(default=None, ge=0, le=2**31 - 1)
    outcome: Outcome | Literal["timed_out"]

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


AGENT_MONITORING = MonitoringKind(
    fact_model=AgentFact,
    fact_fields={"is_root": "boolean", "parent_run_id": "keyword", "agent_version_no": "integer"},
)
