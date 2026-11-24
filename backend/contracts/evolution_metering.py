# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Operator-supplied limits for models whose billable usage is bounded."""

import json
from functools import lru_cache
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from contracts.constants import environment
from contracts.evolution_sources import task_digest


PositiveCap = Annotated[int, Field(gt=0, le=1_000_000_000)]
Price = Annotated[int, Field(ge=0, le=1_000_000_000_000)]


class Tariff(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    max_input_tokens: PositiveCap
    max_output_tokens: PositiveCap
    input_micros_per_million: Price
    output_micros_per_million: Price


class TenantBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    daily_tokens: Annotated[int, Field(gt=0, le=10**12)]
    daily_micros: Annotated[int, Field(ge=0, le=10**15)]
    models: dict[Annotated[str, Field(pattern=r"^[1-9][0-9]*$")], Tariff] = Field(min_length=1)

    def revision(self):
        return task_digest(self.model_dump(mode="json"))


@lru_cache(maxsize=1)
def parse_metering(raw):
    return TypeAdapter(dict[str, TenantBudget]).validate_python(json.loads(raw))


def generation_budget(tenant):
    return parse_metering(environment.EVOLUTION_GENERATION_METERING).get(tenant)


def evaluation_budget(tenant):
    return parse_metering(environment.EVOLUTION_EVALUATION_METERING).get(tenant)


def confirmation_budget(tenant):
    return parse_metering(environment.EVOLUTION_CONFIRMATION_METERING).get(tenant)


def cost_in_micros(input_tokens, output_tokens, input_rate, output_rate):
    return (input_tokens * input_rate + output_tokens * output_rate + 999_999) // 1_000_000
