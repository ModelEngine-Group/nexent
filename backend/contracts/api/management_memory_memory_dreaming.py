# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from datetime import datetime
from typing import Literal, Optional
from zoneinfo import ZoneInfo
from pydantic import BaseModel, Field
from pydantic import model_validator
from nexent.scheduler import is_valid_cron_expression

USER_DREAMING_SCOPE = "__user__"


class DreamingRunRequest(BaseModel):
    target_user_id: Optional[str] = None


class DreamingScheduleRequest(BaseModel):
    enabled: bool
    rule_type: Literal["CRON", "INTERVAL"] = "CRON"
    timezone: str = "Asia/Shanghai"
    start_at: Optional[datetime] = None
    cron_expr: Optional[str] = None
    interval_seconds: Optional[int] = Field(default=None, ge=3600)
    min_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    min_recall_count: Optional[int] = Field(default=None, ge=0)
    min_unique_queries: Optional[int] = Field(default=None, ge=0)
    source_limit: Optional[int] = Field(default=None, ge=1, le=100)
    long_term_max_chars: Optional[int] = Field(default=None, ge=100, le=1000000)
    summarization_max_attempts: Optional[int] = Field(default=None, ge=0, le=10)
    target_user_id: Optional[str] = None

    @model_validator(mode="after")
    def validate_schedule(self):
        try:
            ZoneInfo(self.timezone)
        except Exception as exc:
            raise ValueError(f"Invalid timezone: {self.timezone}") from exc
        if self.rule_type == "CRON":
            if not is_valid_cron_expression(self.cron_expr or ""):
                raise ValueError("A valid five-field cron_expr is required")
            if self.interval_seconds is not None:
                raise ValueError("CRON schedule cannot include interval_seconds")
        else:
            if self.interval_seconds is None:
                raise ValueError("interval_seconds is required")
            if self.cron_expr is not None:
                raise ValueError("INTERVAL schedule cannot include cron_expr")
        return self
