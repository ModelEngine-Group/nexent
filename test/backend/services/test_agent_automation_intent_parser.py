import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

from services.agent_automation.intent_parser import parse_automation_intent


def test_parse_once_intent():
    result = parse_automation_intent("明天上午9点帮我总结项目进展", "Asia/Shanghai")

    assert result["is_automation_intent"] is True
    assert result["schedule_trigger"].mode == "ONCE"
    assert result["schedule_trigger"].rule_type == "AT"
    assert "总结项目进展" in result["instruction"]


def test_parse_recurring_daily_intent():
    result = parse_automation_intent("每天9点总结销售线索", "Asia/Shanghai")

    assert result["is_automation_intent"] is True
    assert result["schedule_trigger"].mode == "RECURRING"
    assert result["schedule_trigger"].rule_type == "CRON"
    assert result["schedule_trigger"].cron_expr == "0 9 * * *"


def test_parse_weekly_intent_uses_requested_weekday_and_afternoon_time():
    result = parse_automation_intent("每周五下午3点发一个周报", "Asia/Shanghai")

    assert result["is_automation_intent"] is True
    assert result["schedule_trigger"].cron_expr == "0 15 * * 5"
    assert result["instruction"] == "发一个周报"


def test_parse_monthly_intent_uses_requested_day():
    result = parse_automation_intent("每月15日上午10点汇总销售数据", "Asia/Shanghai")

    assert result["is_automation_intent"] is True
    assert result["schedule_trigger"].cron_expr == "0 10 15 * *"
    assert result["instruction"] == "汇总销售数据"


def test_parse_non_automation_message():
    result = parse_automation_intent("帮我总结一下项目进展", "Asia/Shanghai")

    assert result["is_automation_intent"] is False


def test_relative_date_question_does_not_create_automation():
    assert parse_automation_intent("今天项目进展如何", "Asia/Shanghai")["is_automation_intent"] is False
    assert parse_automation_intent("明天上午的天气怎么样", "Asia/Shanghai")["is_automation_intent"] is False


def test_relative_date_with_time_and_action_creates_automation():
    result = parse_automation_intent("今天下午3点帮我总结项目进展", "Asia/Shanghai")

    assert result["is_automation_intent"] is True
    assert result["instruction"] == "总结项目进展"


def test_parse_intent_keeps_prompt_optimization_out_of_schedule_parser():
    result = parse_automation_intent("每天9点总结销售线索", "Asia/Shanghai", tenant_id="tenant")

    assert result["instruction"] == "总结销售线索"
    assert result["capability_intents"] == []
