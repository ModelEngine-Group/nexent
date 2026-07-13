import os
import sys
from datetime import datetime, timezone


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

from services.agent_automation import schedule_engine
from services.agent_automation.models import ScheduleMode, ScheduleRuleType, ScheduleTrigger
from services.agent_automation.schedule_engine import compute_next_fire_at


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
    monkeypatch.setattr(schedule_engine, "croniter", None)
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
