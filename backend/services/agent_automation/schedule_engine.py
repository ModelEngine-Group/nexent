"""Compatibility adapter from API models to the SDK schedule engine."""

from datetime import datetime

from nexent.scheduler import (
    ScheduleSpec,
    compute_next_fire_at as compute_sdk_next_fire_at,
    is_valid_cron_expression as validate_sdk_cron_expression,
)

from .models import ScheduleTrigger


def is_valid_cron_expression(expression: str) -> bool:
    return validate_sdk_cron_expression(expression)


def compute_next_fire_at(
    trigger: ScheduleTrigger,
    after: datetime,
    fire_count: int,
) -> datetime | None:
    spec = ScheduleSpec(
        mode=trigger.mode,
        rule_type=trigger.rule_type,
        timezone=trigger.timezone,
        start_at=trigger.start_at,
        end_at=trigger.end_at,
        cron_expr=trigger.cron_expr,
        interval_seconds=trigger.interval_seconds,
        max_fire_count=trigger.max_fire_count,
    )
    return compute_sdk_next_fire_at(spec, after, fire_count)
