import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .models import ScheduleMode, ScheduleRuleType, ScheduleTrigger


RECURRING_TOKENS = ("每天", "每日", "每周", "每星期", "每礼拜", "每月", "周期")
EXPLICIT_AUTOMATION_TOKENS = ("定时", "提醒")
RELATIVE_DATE_TOKENS = ("明天", "今天")
ACTION_TOKENS = (
    "帮我",
    "请",
    "提醒",
    "发送",
    "发一个",
    "发一份",
    "生成",
    "汇总",
    "总结",
    "执行",
    "运行",
    "通知",
)


def _has_explicit_time(message: str) -> bool:
    return bool(
        re.search(r"\d{1,2}(?::|：|点|时)\d{0,2}", message)
        or any(period in message for period in ("上午", "中午", "下午", "晚上", "凌晨", "早上"))
    )


def _is_automation_intent(message: str) -> bool:
    if any(token in message for token in RECURRING_TOKENS + EXPLICIT_AUTOMATION_TOKENS):
        return True
    return (
        any(token in message for token in RELATIVE_DATE_TOKENS)
        and _has_explicit_time(message)
        and any(token in message for token in ACTION_TOKENS)
    )


def _parse_hour_minute(message: str, default_hour: int = 9) -> tuple[int, int]:
    match = re.search(r"(\d{1,2})[:：点时](\d{1,2})?", message)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        if any(period in message for period in ("下午", "晚上")) and hour < 12:
            hour += 12
        elif "中午" in message and hour < 11:
            hour += 12
        elif "凌晨" in message and hour == 12:
            hour = 0
        if hour > 23 or minute > 59:
            raise ValueError("Invalid hour or minute in automation schedule.")
        return hour, minute
    if "上午" in message or "早上" in message:
        return default_hour, 0
    if "下午" in message or "晚上" in message:
        return 18, 0
    return default_hour, 0


def _clean_instruction(message: str) -> str:
    cleaned = re.sub(r"(?:每)?(?:周|星期|礼拜)[一二三四五六日天]", "", message)
    cleaned = re.sub(r"每月\s*\d{1,2}(?:号|日)?", "", cleaned)
    cleaned = re.sub(
        r"(请|帮我|定时|提醒我|每天|每日|每周|每星期|每礼拜|每月|"
        r"明天|今天|上午|中午|下午|晚上|凌晨)",
        "",
        cleaned,
    )
    cleaned = re.sub(r"\d{1,2}[:：点时]\d{0,2}", "", cleaned)
    cleaned = cleaned.strip(" ，,。")
    return cleaned or message


def _parse_weekday(message: str, default: int = 1) -> int:
    weekday_map = {
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "日": 0,
        "天": 0,
    }
    match = re.search(r"(?:周|星期|礼拜)([一二三四五六日天])", message)
    return weekday_map.get(match.group(1), default) if match else default


def _parse_month_day(message: str, default: int = 1) -> int:
    match = re.search(r"每月\s*(\d{1,2})(?:号|日)?", message)
    day = int(match.group(1)) if match else default
    if day < 1 or day > 31:
        raise ValueError("Invalid day of month in automation schedule.")
    return day


def parse_automation_intent(
    message: str,
    timezone_name: str = "Asia/Shanghai",
    tenant_id: str | None = None,
) -> dict:
    """Parse a natural-language automation request into a conservative proposal."""
    zone = ZoneInfo(timezone_name)
    now = datetime.now(zone)

    if not _is_automation_intent(message):
        return {"is_automation_intent": False, "confidence": 0.0}

    hour, minute = _parse_hour_minute(message)
    instruction = _clean_instruction(message)
    title = instruction[:30] if instruction else "自动任务"

    if "每天" in message or "每日" in message:
        start_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if start_at <= now:
            start_at += timedelta(days=1)
        trigger = ScheduleTrigger(
            mode=ScheduleMode.RECURRING,
            rule_type=ScheduleRuleType.CRON,
            timezone=timezone_name,
            start_at=start_at,
            cron_expr=f"{minute} {hour} * * *",
        )
    elif any(token in message for token in ("每周", "每星期", "每礼拜")):
        weekday = _parse_weekday(message)
        cron_weekday = weekday
        start_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        trigger = ScheduleTrigger(
            mode=ScheduleMode.RECURRING,
            rule_type=ScheduleRuleType.CRON,
            timezone=timezone_name,
            start_at=start_at,
            cron_expr=f"{minute} {hour} * * {cron_weekday}",
        )
    elif "每月" in message:
        month_day = _parse_month_day(message)
        start_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        trigger = ScheduleTrigger(
            mode=ScheduleMode.RECURRING,
            rule_type=ScheduleRuleType.CRON,
            timezone=timezone_name,
            start_at=start_at,
            cron_expr=f"{minute} {hour} {month_day} * *",
        )
    else:
        days = 1 if "明天" in message else 0
        start_at = (now + timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        if start_at <= now:
            start_at += timedelta(days=1)
        trigger = ScheduleTrigger(
            mode=ScheduleMode.ONCE,
            rule_type=ScheduleRuleType.AT,
            timezone=timezone_name,
            start_at=start_at,
            max_fire_count=1,
        )

    base_result = {
        "is_automation_intent": True,
        "confidence": 0.86,
        "title": title,
        "instruction": instruction,
        "schedule_trigger": trigger,
        "capability_intents": [],
        "output_requirements": {"language": "zh"},
    }
    return base_result
