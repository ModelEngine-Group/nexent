from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from nexent.scheduler import ScheduleMode, ScheduleRuleType
from pydantic import BaseModel, Field, field_validator, model_validator


class StrEnum(str, Enum):
    pass


class AutomationTaskStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    PAUSED_BY_SYSTEM = "PAUSED_BY_SYSTEM"
    COMPLETED = "COMPLETED"
    DELETED = "DELETED"


class AutomationRunStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELED = "CANCELED"
    TIMEOUT = "TIMEOUT"


class AutomationProposalStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class AutomationSource(StrEnum):
    CHAT_INTENT = "CHAT_INTENT"


class CapabilityType(StrEnum):
    TOOL = "TOOL"
    SKILL = "SKILL"
    KNOWLEDGE_BASE = "KNOWLEDGE_BASE"
    MANAGED_AGENT = "MANAGED_AGENT"
    EXTERNAL_A2A_AGENT = "EXTERNAL_A2A_AGENT"
    MEMORY = "MEMORY"


class ScheduleTrigger(BaseModel):
    mode: ScheduleMode
    rule_type: ScheduleRuleType
    timezone: str = "Asia/Shanghai"
    start_at: datetime
    end_at: Optional[datetime] = None
    cron_expr: Optional[str] = None
    interval_seconds: Optional[int] = Field(default=None, gt=0)
    max_fire_count: Optional[int] = Field(default=None, gt=0)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except Exception as exc:
            raise ValueError(f"Invalid timezone: {value}") from exc
        return value

    @model_validator(mode="after")
    def validate_combination(self):
        if self.end_at is not None and self.end_at <= self.start_at:
            raise ValueError("end_at must be later than start_at")
        if self.mode == ScheduleMode.ONCE:
            if self.rule_type != ScheduleRuleType.AT:
                raise ValueError("ONCE schedule only supports AT rule_type")
            if self.cron_expr is not None or self.interval_seconds is not None:
                raise ValueError("ONCE schedule cannot include cron_expr or interval_seconds")
            self.max_fire_count = 1
        elif self.mode == ScheduleMode.RECURRING:
            if self.rule_type == ScheduleRuleType.AT:
                raise ValueError("RECURRING schedule does not support AT rule_type")
            if self.rule_type == ScheduleRuleType.CRON and not self.cron_expr:
                raise ValueError("cron_expr is required for CRON schedules")
            if self.rule_type == ScheduleRuleType.CRON and self.interval_seconds is not None:
                raise ValueError("CRON schedule cannot include interval_seconds")
            if self.rule_type == ScheduleRuleType.INTERVAL and not self.interval_seconds:
                raise ValueError("interval_seconds is required for INTERVAL schedules")
            if self.rule_type == ScheduleRuleType.INTERVAL and self.cron_expr is not None:
                raise ValueError("INTERVAL schedule cannot include cron_expr")
        return self


class CapabilityBinding(BaseModel):
    type: CapabilityType
    name: str
    display_name: Optional[str] = None
    binding_ref: str
    reason: Optional[str] = None
    required: bool = True


class CapabilityResolution(BaseModel):
    matched_capabilities: List[CapabilityBinding] = Field(default_factory=list)
    missing_capabilities: List[Dict[str, Any]] = Field(default_factory=list)
    optional_capabilities: List[CapabilityBinding] = Field(default_factory=list)
    agent_snapshot: Dict[str, Any] = Field(default_factory=dict)
    executable: bool = True


class AutomationTaskCreateRequest(BaseModel):
    title: str = Field(min_length=1)
    agent_id: int = Field(gt=0)
    instruction: str = Field(min_length=1)
    schedule_trigger: ScheduleTrigger
    conversation_id: int = Field(gt=0)
    original_instruction: Optional[str] = None
    agent_version_no: Optional[int] = None
    model_id: Optional[int] = None
    tool_params: Optional[Dict[str, Any]] = None
    capability_bindings: List[CapabilityBinding] = Field(default_factory=list)
    timeout_seconds: Optional[int] = Field(default=None, gt=0)


class AutomationTaskPatchRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1)
    instruction: Optional[str] = Field(default=None, min_length=1)
    schedule_trigger: Optional[ScheduleTrigger] = None
    capability_bindings: Optional[List[CapabilityBinding]] = None
    model_id: Optional[int] = None
    tool_params: Optional[Dict[str, Any]] = None
    timeout_seconds: Optional[int] = Field(default=None, gt=0)


class AutomationProposalCreateRequest(BaseModel):
    conversation_id: Optional[int] = Field(default=None, gt=0)
    agent_id: int = Field(gt=0)
    message: str = Field(min_length=1)
    timezone: str = "Asia/Shanghai"
    agent_version_no: Optional[int] = None
    model_id: Optional[int] = None
    tool_params: Optional[Dict[str, Any]] = None


class AutomationProposalConfirmRequest(BaseModel):
    instruction: Optional[str] = None


class AutomationResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: Any = None
