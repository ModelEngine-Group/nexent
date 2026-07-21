import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

from services.agent_automation.intent_parser import parse_automation_intent


REFERENCE_TIME = datetime(2026, 7, 13, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


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


@pytest.mark.parametrize(
    ("message", "expected_instruction"),
    [
        ("每天早上八点算一下当天的黄历信息", "算一下当天的黄历信息"),
        ("每天早上8点获取当天的黄历信息", "获取当天的黄历信息"),
        ("每天早上8点检索当天的黄历信息", "检索当天的黄历信息"),
        ("every day at 8 am fetch today's almanac", "fetch today's almanac"),
    ],
)
def test_parse_daily_information_actions_as_automation(message, expected_instruction):
    result = parse_automation_intent(message, reference_time=REFERENCE_TIME)

    assert result["is_automation_intent"] is True
    assert result["schedule_trigger"].rule_type == "CRON"
    assert result["schedule_trigger"].cron_expr == "0 8 * * *"
    assert result["instruction"] == expected_instruction


def test_parse_minutely_interval_intent():
    result = parse_automation_intent("每分钟给我发一句你好", "Asia/Shanghai")

    assert result["is_automation_intent"] is True
    assert result["schedule_trigger"].mode == "RECURRING"
    assert result["schedule_trigger"].rule_type == "INTERVAL"
    assert result["schedule_trigger"].interval_seconds == 60
    assert result["instruction"] == "发一句你好"


def test_parse_five_second_interval_intent():
    result = parse_automation_intent("每5秒钟发送一次你好", "Asia/Shanghai")

    assert result["is_automation_intent"] is True
    assert result["schedule_trigger"].interval_seconds == 5
    assert result["instruction"] == "发送一次你好"


def test_parse_numbered_interval_intents():
    every_five_minutes = parse_automation_intent("每5分钟检查一次任务状态", "Asia/Shanghai")
    every_two_hours = parse_automation_intent("每隔2小时汇总销售数据", "Asia/Shanghai")

    assert every_five_minutes["schedule_trigger"].interval_seconds == 300
    assert every_five_minutes["instruction"] == "检查一次任务状态"
    assert every_two_hours["schedule_trigger"].interval_seconds == 7200
    assert every_two_hours["instruction"] == "汇总销售数据"


def test_parse_interval_aliases_and_hourly_offsets():
    every_half_hour = parse_automation_intent(
        "每半个小时检查服务状态",
        reference_time=REFERENCE_TIME,
    )
    every_two_hours = parse_automation_intent(
        "每两个小时检查服务状态",
        reference_time=REFERENCE_TIME,
    )
    hourly_on_the_hour = parse_automation_intent(
        "每小时整点检查服务状态",
        reference_time=REFERENCE_TIME,
    )
    hourly_at_quarter = parse_automation_intent(
        "每小时第十五分钟检查服务状态",
        reference_time=REFERENCE_TIME,
    )

    assert every_half_hour["schedule_trigger"].interval_seconds == 1800
    assert every_two_hours["schedule_trigger"].interval_seconds == 7200
    assert hourly_on_the_hour["schedule_trigger"].cron_expr == "0 * * * *"
    assert hourly_at_quarter["schedule_trigger"].cron_expr == "15 * * * *"
    assert hourly_on_the_hour["instruction"] == "检查服务状态"


def test_unsupported_multi_month_recurrence_is_not_silently_run_as_normal_chat():
    result = parse_automation_intent(
        "每两个月1号上午9点生成报告",
        reference_time=REFERENCE_TIME,
    )

    assert result["is_automation_intent"] is True
    assert result["schedule_trigger"] is None
    assert "暂不支持" in result["schedule_error"]


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


@pytest.mark.parametrize(
    "message",
    [
        "帮我获取今天的黄历信息",
        "帮我分析一下每天早上八点的销量",
        "查询每天早上八点的历史天气",
        "我每天早上八点都会查看黄历",
    ],
)
def test_ordinary_tasks_and_statements_are_not_intercepted_as_automation(message):
    result = parse_automation_intent(message, reference_time=REFERENCE_TIME)

    assert result["is_automation_intent"] is False


@pytest.mark.parametrize(
    ("message", "expected_instruction"),
    [
        ("帮我每天早上八点分析销量", "分析销量"),
        ("请你在明天上午九点提醒我开会", "提醒我开会"),
        ("创建一个每天早上八点获取黄历的定时任务", "获取黄历"),
    ],
)
def test_schedule_that_modifies_a_task_action_is_intercepted(message, expected_instruction):
    result = parse_automation_intent(message, reference_time=REFERENCE_TIME)

    assert result["is_automation_intent"] is True
    assert result["instruction"] == expected_instruction


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


def test_parse_workday_and_multiple_weekday_cron_expressions():
    workday = parse_automation_intent(
        "每个工作日早上8点汇总销售数据",
        reference_time=REFERENCE_TIME,
    )
    selected_weekdays = parse_automation_intent(
        "每周一、周三、周五下午6点检查服务状态",
        reference_time=REFERENCE_TIME,
    )

    assert workday["schedule_trigger"].cron_expr == "0 8 * * 1-5"
    assert workday["instruction"] == "汇总销售数据"
    assert selected_weekdays["schedule_trigger"].cron_expr == "0 18 * * 1,3,5"
    assert selected_weekdays["instruction"] == "检查服务状态"


def test_parse_multiple_month_days_and_yearly_cron_expressions():
    monthly = parse_automation_intent(
        "每月1号和15号上午10点生成销售报告",
        reference_time=REFERENCE_TIME,
    )
    yearly = parse_automation_intent(
        "每年7月1日上午9点发送纪念消息",
        reference_time=REFERENCE_TIME,
    )

    assert monthly["schedule_trigger"].cron_expr == "0 10 1,15 * *"
    assert monthly["instruction"] == "生成销售报告"
    assert yearly["schedule_trigger"].cron_expr == "0 9 1 7 *"
    assert yearly["instruction"] == "发送纪念消息"


def test_parse_relative_delay_explicit_date_and_next_weekday():
    delayed = parse_automation_intent("半小时后提醒我开会", reference_time=REFERENCE_TIME)
    explicit = parse_automation_intent(
        "2026年7月14日01:30执行备份",
        reference_time=REFERENCE_TIME,
    )
    next_monday = parse_automation_intent(
        "下周一上午9点提醒我提交周报",
        reference_time=REFERENCE_TIME,
    )

    assert delayed["schedule_trigger"].start_at == datetime(
        2026, 7, 13, 10, 30, tzinfo=ZoneInfo("Asia/Shanghai")
    )
    assert delayed["instruction"] == "提醒我开会"
    assert explicit["schedule_trigger"].start_at == datetime(
        2026, 7, 14, 1, 30, tzinfo=ZoneInfo("Asia/Shanghai")
    )
    assert next_monday["schedule_trigger"].start_at == datetime(
        2026, 7, 20, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")
    )
    assert next_monday["instruction"] == "提醒我提交周报"


def test_this_weekday_uses_current_calendar_week_instead_of_silently_rolling_forward():
    friday_morning = datetime(2026, 7, 17, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    future_today = parse_automation_intent(
        "本周五下午3点提醒我提交周报",
        reference_time=friday_morning,
    )
    past_today = parse_automation_intent(
        "本周五上午9点提醒我提交周报",
        reference_time=friday_morning,
    )

    assert future_today["schedule_trigger"].start_at == datetime(
        2026, 7, 17, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai")
    )
    assert past_today["schedule_trigger"] is None
    assert "已经过去" in past_today["schedule_error"]


def test_ambiguous_or_past_schedule_requires_clarification_instead_of_guessing():
    missing_time = parse_automation_intent("每天提醒我提交日报", reference_time=REFERENCE_TIME)
    past_time = parse_automation_intent("今天上午9点提醒我提交日报", reference_time=REFERENCE_TIME)

    assert missing_time["schedule_trigger"] is None
    assert "具体时间" in missing_time["schedule_error"]
    assert past_time["schedule_trigger"] is None
    assert "已经过去" in past_time["schedule_error"]


def test_parse_common_english_schedule_expressions():
    recurring = parse_automation_intent(
        "every Monday at 3 pm send a report",
        reference_time=REFERENCE_TIME,
    )
    once = parse_automation_intent(
        "tomorrow at 9 am send hello",
        reference_time=REFERENCE_TIME,
    )

    assert recurring["schedule_trigger"].cron_expr == "0 15 * * 1"
    assert recurring["instruction"] == "send a report"
    assert once["schedule_trigger"].start_at == datetime(
        2026, 7, 14, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")
    )
    assert once["instruction"] == "send hello"


def test_parse_explicit_timezone_and_english_workday():
    utc_task = parse_automation_intent(
        "每天 UTC时间 9点发送日报",
        reference_time=REFERENCE_TIME,
    )
    weekday = parse_automation_intent(
        "every weekday at 8 am send a status report",
        reference_time=REFERENCE_TIME,
    )

    assert utc_task["schedule_trigger"].timezone == "UTC"
    assert utc_task["schedule_trigger"].cron_expr == "0 9 * * *"
    assert utc_task["instruction"] == "发送日报"
    assert weekday["schedule_trigger"].cron_expr == "0 8 * * 1-5"


def test_parse_iana_timezone_from_natural_language():
    result = parse_automation_intent(
        "每天 Asia/Tokyo 9点发送日报",
        reference_time=REFERENCE_TIME,
    )

    assert result["schedule_trigger"].timezone == "Asia/Tokyo"
    assert result["schedule_trigger"].cron_expr == "0 9 * * *"
    assert result["instruction"] == "发送日报"


def test_nonexistent_dst_local_time_is_rejected():
    reference = datetime(2026, 1, 1, 10, 0, tzinfo=ZoneInfo("America/New_York"))

    with pytest.raises(ValueError, match="does not exist"):
        parse_automation_intent(
            "2026-03-08 02:30 America/New_York 发送提醒",
            reference_time=reference,
        )


@pytest.mark.parametrize(
    ("message", "expected_cron", "expected_instruction"),
    [
        ("每晚9点发送日报", "0 21 * * *", "发送日报"),
        ("每天晚上12点发送日报", "0 0 * * *", "发送日报"),
        ("每个星期一上午9点发送周报", "0 9 * * 1", "发送周报"),
        ("每周一至周五上午9点发送日报", "0 9 * * 1-5", "发送日报"),
        ("每天上午9点、下午3点检查状态", "0 9,15 * * *", "检查状态"),
        ("每月最后一天上午9点生成月报", "0 9 L * *", "生成月报"),
        ("每季度第一天上午9点生成季报", "0 9 1 1,4,7,10 *", "生成季报"),
    ],
)
def test_parse_common_calendar_aliases_and_multiple_times(message, expected_cron, expected_instruction):
    result = parse_automation_intent(message, reference_time=REFERENCE_TIME)

    assert result["schedule_trigger"].cron_expr == expected_cron
    assert result["instruction"] == expected_instruction


def test_multiple_times_that_cannot_be_one_cron_require_separate_tasks():
    result = parse_automation_intent(
        "每天9点和18点30分检查状态",
        reference_time=REFERENCE_TIME,
    )

    assert result["schedule_trigger"] is None
    assert "拆分为多个任务" in result["schedule_error"]


@pytest.mark.parametrize(
    ("message", "expected_start"),
    [
        ("明早9点提醒我开会", datetime(2026, 7, 14, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))),
        ("半个小时后提醒我休息", datetime(2026, 7, 13, 10, 30, tzinfo=ZoneInfo("Asia/Shanghai"))),
        ("一周后提醒我复盘", datetime(2026, 7, 20, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))),
        ("下个月1号上午9点生成月报", datetime(2026, 8, 1, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))),
        ("7/14 09:00提醒我开会", datetime(2026, 7, 14, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))),
        ("今晚12点提醒我睡觉", datetime(2026, 7, 14, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))),
        ("next Monday at 3 pm send a report", datetime(2026, 7, 20, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai"))),
    ],
)
def test_parse_relative_and_short_once_expressions(message, expected_start):
    result = parse_automation_intent(message, reference_time=REFERENCE_TIME)

    assert result["schedule_trigger"].start_at == expected_start


def test_recurring_language_without_an_action_is_not_an_automation_command():
    messages = (
        "每周的销量是多少",
        "每周发现多少个问题",
        "每天上午9点的销量是多少",
        "每5分钟有多少个请求",
    )

    for message in messages:
        result = parse_automation_intent(message, reference_time=REFERENCE_TIME)
        assert result["is_automation_intent"] is False


@pytest.mark.parametrize(
    "message",
    [
        "每天早上八点获取的信息是什么",
        "每天早上八点如何获取黄历信息",
        "每5分钟获取的数据有多少条",
    ],
)
def test_recurring_information_questions_are_not_automation_commands(message):
    result = parse_automation_intent(message, reference_time=REFERENCE_TIME)

    assert result["is_automation_intent"] is False
