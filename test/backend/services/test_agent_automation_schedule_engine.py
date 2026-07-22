import os
import sys
from datetime import datetime, timezone


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

from services.agent_automation.models import ScheduleMode, ScheduleRuleType, ScheduleTrigger
from services.agent_automation.schedule_engine import compute_next_fire_at
from services.agent_automation.schedule_engine import is_valid_cron_expression
from nexent.scheduler import triggers as trigger_engine


def test_once_at_returns_start_then_none():
    trigger = ScheduleTrigger(
        mode=ScheduleMode.ONCE,
        rule_type=ScheduleRuleType.AT,
        timezone="Asia/Shanghai",
        start_at=datetime(2026, 7, 9, 9, 0, tzinfo=timezone.utc),
    )

    next_fire = compute_next_fire_at(trigger, datetime(2026, 7, 8, 9, 0, tzinfo=timezone.utc), 0)
    assert next_fire == datetime(2026, 7, 9, 9, 0, tzinfo=timezone.utc)
    assert compute_next_fire_at(trigger, next_fire, 1) is None


def test_recurring_interval_computes_next_slot():
    trigger = ScheduleTrigger(
        mode=ScheduleMode.RECURRING,
        rule_type=ScheduleRuleType.INTERVAL,
        timezone="UTC",
        start_at=datetime(2026, 7, 8, 9, 0, tzinfo=timezone.utc),
        interval_seconds=3600,
    )

    next_fire = compute_next_fire_at(trigger, datetime(2026, 7, 8, 10, 30, tzinfo=timezone.utc), 0)
    assert next_fire == datetime(2026, 7, 8, 11, 0, tzinfo=timezone.utc)


def test_recurring_cron_computes_daily_time():
    trigger = ScheduleTrigger(
        mode=ScheduleMode.RECURRING,
        rule_type=ScheduleRuleType.CRON,
        timezone="UTC",
        start_at=datetime(2026, 7, 8, 0, 0, tzinfo=timezone.utc),
        cron_expr="0 9 * * *",
    )

    next_fire = compute_next_fire_at(trigger, datetime(2026, 7, 8, 9, 1, tzinfo=timezone.utc), 0)
    assert next_fire == datetime(2026, 7, 9, 9, 0, tzinfo=timezone.utc)


def test_recurring_cron_returns_matching_start_at_first():
    trigger = ScheduleTrigger(
        mode=ScheduleMode.RECURRING,
        rule_type=ScheduleRuleType.CRON,
        timezone="UTC",
        start_at=datetime(2026, 7, 9, 9, 0, tzinfo=timezone.utc),
        cron_expr="0 9 * * *",
    )

    next_fire = compute_next_fire_at(trigger, datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc), 0)
    assert next_fire == datetime(2026, 7, 9, 9, 0, tzinfo=timezone.utc)


def test_monthly_cron_fallback_respects_day_of_month(monkeypatch):
    monkeypatch.setattr(trigger_engine, "croniter", None)
    trigger = ScheduleTrigger(
        mode=ScheduleMode.RECURRING,
        rule_type=ScheduleRuleType.CRON,
        timezone="UTC",
        start_at=datetime(2026, 7, 8, 0, 0, tzinfo=timezone.utc),
        cron_expr="0 10 15 * *",
    )

    next_fire = compute_next_fire_at(trigger, datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc), 0)

    assert next_fire == datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc)


def test_end_at_caps_recurring_schedule():
    trigger = ScheduleTrigger(
        mode=ScheduleMode.RECURRING,
        rule_type=ScheduleRuleType.INTERVAL,
        timezone="UTC",
        start_at=datetime(2026, 7, 8, 9, 0, tzinfo=timezone.utc),
        end_at=datetime(2026, 7, 8, 9, 30, tzinfo=timezone.utc),
        interval_seconds=3600,
    )

    assert compute_next_fire_at(trigger, datetime(2026, 7, 8, 9, 1, tzinfo=timezone.utc), 0) is None


def test_cron_validation_accepts_generated_rules_and_rejects_invalid_input():
    assert is_valid_cron_expression("0 9 * * 1-5") is True
    assert is_valid_cron_expression("0 18 * * 1,3,5") is True
    assert is_valid_cron_expression("0 9 L * *") is True
    assert is_valid_cron_expression("0 9 1 1,4,7,10 *") is True
    assert is_valid_cron_expression("61 9 * * *") is False
    assert is_valid_cron_expression("0 25 * * *") is False
    assert is_valid_cron_expression("not a cron") is False


def test_cron_fallback_supports_multiple_times_and_last_day(monkeypatch):
    monkeypatch.setattr(trigger_engine, "croniter", None)
    multiple_times = ScheduleTrigger(
        mode=ScheduleMode.RECURRING,
        rule_type=ScheduleRuleType.CRON,
        timezone="Asia/Shanghai",
        start_at="2026-07-13T10:01:00+08:00",
        cron_expr="0 9,15 * * *",
    )
    month_end = ScheduleTrigger(
        mode=ScheduleMode.RECURRING,
        rule_type=ScheduleRuleType.CRON,
        timezone="Asia/Shanghai",
        start_at="2026-07-13T10:01:00+08:00",
        cron_expr="0 9 L * *",
    )
    after = datetime(2026, 7, 13, 2, 1, tzinfo=timezone.utc)

    assert compute_next_fire_at(multiple_times, after, 0) == datetime(
        2026, 7, 13, 7, 0, tzinfo=timezone.utc
    )
    assert compute_next_fire_at(month_end, after, 0) == datetime(
        2026, 7, 31, 1, 0, tzinfo=timezone.utc
    )
