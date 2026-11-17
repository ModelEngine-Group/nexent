# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management-owned automatic summary issuer and one-attempt-per-data-version snapshot."""

from datetime import datetime
from typing import Literal

from contracts.agentos_knowledge import Contract
from pydantic import Field, field_validator, model_validator

SUMMARY_DATASET = 'management_knowledge_summary'
SUMMARY_MODEL_DATASET = 'management_summary_model'
SUMMARY_DISPATCH_DATASET = 'management_summary_dispatch'


class SummaryAttempt(Contract):
    attempt_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    user_id: str = Field(min_length=1, max_length=100)
    data_revision: str = Field(pattern=r'^[0-9a-f]{64}$')
    knowledge_revision: str = Field(pattern=r'^[0-9a-f]{64}$')
    model_id: int | None = Field(default=None, gt=0)
    status: Literal['admitted', 'completed', 'failed'] = 'admitted'
    started_at: str = Field(min_length=1, max_length=64)
    completed_at: str | None = Field(default=None, min_length=1, max_length=64)
    error_code: str | None = Field(default=None, pattern=r'^[A-Z][A-Z0-9_]{0,127}$')

    @field_validator('started_at', 'completed_at')
    @classmethod
    def aware_time(cls, value):
        if value is not None and datetime.fromisoformat(value).tzinfo is None:
            raise ValueError('Expected an explicit timestamp offset')
        return value

    @model_validator(mode='after')
    def terminal_state(self):
        if ((self.status == 'admitted') != (self.completed_at is None)
            or (self.status == 'failed') != (self.error_code is not None)):
            raise ValueError('Summary outcome must match its completion timestamp and error')
        return self


class SummarySchedule(Contract):
    schema_version: Literal[1] = 1
    user_id: str = Field(min_length=1, max_length=100)
    configuration_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    attempt: SummaryAttempt | None = None

    @model_validator(mode='after')
    def bounded_snapshot(self):
        if len(self.model_dump_json().encode()) > 16384:
            raise ValueError('Summary configuration exceeds 16 KiB')
        return self


class SummaryWork(SummarySchedule):
    knowledge_id: int = Field(gt=0)
    index_name: str = Field(min_length=1, max_length=100)
    attempt: SummaryAttempt
