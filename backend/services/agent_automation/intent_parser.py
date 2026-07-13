import re
from datetime import date, datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from .models import ScheduleMode, ScheduleRuleType, ScheduleTrigger


_NUMBER_TOKEN = r"(?:\d+|[零一二两三四五六七八九十百]+|半)"
_CLOCK_NUMBER_TOKEN = r"(?:\d{1,2}|[零一二两三四五六七八九十]+)"
_INTERVAL_PATTERN = re.compile(
    rf"(?:每(?:隔\s*)?|隔\s*)(?P<count>{_NUMBER_TOKEN})?\s*(?:个)?"
    r"(?P<unit>秒钟?|分钟?|小时|钟头)"
)
_DAY_INTERVAL_PATTERN = re.compile(
    rf"每(?:隔\s*)?(?P<count>{_NUMBER_TOKEN})\s*(?:个)?(?P<unit>天|日|周|星期)"
)
_RELATIVE_DELAY_PATTERN = re.compile(
    rf"(?P<count>{_NUMBER_TOKEN})\s*(?:个)?(?P<unit>秒钟?|分钟?|小时|钟头|天|日|周|星期)"
    r"\s*(?:以后|之后|后)"
)
_HOURLY_OFFSET_PATTERN = re.compile(
    rf"每(?:个)?小时(?:的)?(?:(?:第)?(?P<minute>{_CLOCK_NUMBER_TOKEN})\s*分(?:钟)?|"
    r"(?P<marker>整点|半点))"
)
_EXPLICIT_DATE_PATTERN = re.compile(
    r"(?:(?P<year>\d{4})\s*年\s*)?(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*(?:日|号)?"
)
_ISO_DATE_PATTERN = re.compile(r"(?P<year>\d{4})[-/](?P<month>\d{1,2})[-/](?P<day>\d{1,2})")
_SHORT_DATE_PATTERN = re.compile(r"(?<!\d)(?P<month>\d{1,2})/(?P<day>\d{1,2})(?!\d)")
_RELATIVE_MONTH_DAY_PATTERN = re.compile(
    r"(?P<relative_month>下个?月|本月|这个月)\s*(?P<day>\d{1,2})\s*(?:日|号)?"
)
_DAY_OF_MONTH_ONCE_PATTERN = re.compile(r"(?<![月\d])(?P<day>\d{1,2})\s*(?:日|号)")
_WEEKDAY_PATTERN = re.compile(
    r"(?:(?P<prefix>下|本|这(?:个)?)(?:周|星期|礼拜)|(?:周|星期|礼拜))"
    r"(?P<day>[一二三四五六日天])"
)
_RECURRING_WEEKDAY_PATTERN = re.compile(
    r"(?:每(?:个)?|每逢|逢)(?:周|星期|礼拜)(?P<days>[一二三四五六日天]"
    r"(?:\s*[、,，/和及]\s*(?:(?:周|星期|礼拜))?[一二三四五六日天])*)"
)
_RECURRING_WEEKDAY_RANGE_PATTERN = re.compile(
    r"每(?:个)?(?:周|星期|礼拜)(?P<start>[一二三四五六日天])\s*(?:到|至|[-~～])\s*"
    r"(?:(?:周|星期|礼拜))?(?P<end>[一二三四五六日天])"
)
_MONTH_DAY_LIST_PATTERN = re.compile(
    r"每(?:个)?月\s*(?P<days>\d{1,2}(?:\s*(?:号|日))?"
    r"(?:\s*[、,，/和及]\s*\d{1,2}(?:\s*(?:号|日))?)*)"
)
_YEARLY_PATTERN = re.compile(r"每年(?:的)?\s*(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*(?:日|号)?")
_MONTH_END_PATTERN = re.compile(r"(?:每(?:个)?月(?:的)?最后一天|每(?:个)?月末|每(?:个)?月底)")
_QUARTERLY_PATTERN = re.compile(
    r"每(?:个)?季度(?:的)?(?:第)?(?P<day>\d{1,2}|一)\s*(?:天|日|号)?"
)
_RECURRENCE_MARKER_PATTERN = re.compile(
    r"(?:每(?:个)?(?:天|日|晚|周|星期|礼拜|月|年|季度)|每逢|逢(?:周|星期|礼拜))"
)
_UNSUPPORTED_RECURRENCE_PATTERN = re.compile(
    rf"每(?:隔\s*)?(?P<count>{_NUMBER_TOKEN})\s*(?:个)?(?P<unit>月|年)"
)
_EN_INTERVAL_PATTERN = re.compile(
    r"\bevery\s+(?:(?P<count>\d+)\s+)?(?P<unit>second|minute|hour)s?\b",
    flags=re.IGNORECASE,
)
_EN_RELATIVE_DELAY_PATTERN = re.compile(
    r"\bin\s+(?P<count>\d+)\s+(?P<unit>minute|hour|day)s?\b",
    flags=re.IGNORECASE,
)
_EN_RECURRING_WEEKDAY_PATTERN = re.compile(
    r"\bevery\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    flags=re.IGNORECASE,
)
_EN_NEXT_WEEKDAY_PATTERN = re.compile(
    r"\bnext\s+(?P<day>monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    flags=re.IGNORECASE,
)
_IANA_TIMEZONE_PATTERN = re.compile(
    r"\b(?:Africa|America|Antarctica|Asia|Atlantic|Australia|Europe|Indian|Pacific)"
    r"/[A-Za-z_+-]+(?:/[A-Za-z_+-]+)?\b"
)
_TIMEZONE_PATTERN = re.compile(
    r"(?:北京时间|上海时间|中国时间|上海时区|中国时区|东京时间|日本时间|纽约时间|"
    r"伦敦时间|洛杉矶时间|UTC\s*(?:时间|时区)|UTC\s*(?=\d{1,2}\s*(?:[:：点时])))",
    re.IGNORECASE,
)

_TIMEZONE_ALIASES = (
    (re.compile(r"(?:北京时间|上海时间|中国时间|上海时区|中国时区)"), "Asia/Shanghai"),
    (re.compile(r"(?:东京时间|日本时间)"), "Asia/Tokyo"),
    (re.compile(r"纽约时间"), "America/New_York"),
    (re.compile(r"伦敦时间"), "Europe/London"),
    (re.compile(r"洛杉矶时间"), "America/Los_Angeles"),
    (re.compile(r"UTC\s*(?:(?:时间|时区)|(?=\d{1,2}\s*(?:[:：点时])))", re.IGNORECASE), "UTC"),
)

_WEEKDAY_TO_CRON = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 0, "天": 0}
_EN_WEEKDAY_TO_CRON = {
    "sunday": 0,
    "monday": 1,
    "tuesday": 2,
    "wednesday": 3,
    "thursday": 4,
    "friday": 5,
    "saturday": 6,
}
_DURATION_SECONDS = {
    "秒": 1,
    "秒钟": 1,
    "分": 60,
    "分钟": 60,
    "小时": 3600,
    "钟头": 3600,
    "天": 86400,
    "日": 86400,
    "周": 604800,
    "星期": 604800,
    "second": 1,
    "minute": 60,
    "hour": 3600,
    "day": 86400,
}
_ACTION_TOKENS = (
    "提醒",
    "发送",
    "生成",
    "汇总",
    "总结",
    "执行",
    "运行",
    "通知",
    "检查",
    "查询",
    "整理",
    "备份",
    "同步",
    "推送",
    "发布",
    "抓取",
    "监控",
    "扫描",
    "清理",
    "更新",
    "导出",
    "调用",
    "统计",
    "记录",
    "计算",
    "算一下",
    "获取",
    "查找",
    "检索",
    "搜索",
    "读取",
    "收集",
    "采集",
    "分析",
    "处理",
    "转换",
    "翻译",
    "创建",
    "提交",
    "保存",
    "写入",
    "上传",
    "下载",
    "告诉",
    "说",
)
_AUTOMATION_TOKENS = (
    "定时",
    "提醒",
    "每天",
    "每日",
    "每晚",
    "每周",
    "每星期",
    "每礼拜",
    "每月",
    "每年",
    "工作日",
    "周末",
    "周期",
    "every ",
    "tomorrow",
    "next ",
    "明早",
    "明晚",
    "下个月",
    "本月",
    "每季度",
    "定期",
    "每当",
    "每次",
)
_QUESTION_PATTERN = re.compile(
    r"(?:多少|如何|怎么|怎么样|是什么|为何|为什么|是否|能否|可不可以|有没有|吗|呢|[？?])"
)
_EXPLICIT_AUTOMATION_PATTERN = re.compile(
    r"(?:定时任务|自动任务|周期任务|计划任务|"
    r"(?:创建|新建|添加|设置|设定|安排|建立|配置).{0,24}(?:任务|提醒|定时|自动|周期)|提醒我)"
)
_LEADING_REQUEST_PATTERN = re.compile(
    r"^\s*(?:(?:请你|请帮我|请|麻烦你|麻烦|帮我|给我|为我|"
    r"我希望你|我想让你|我要你|需要你)\s*)+"
)
_DECLARATIVE_ACTION_PATTERN = re.compile(
    r"^(?:我(?:会|通常|一般|总是|习惯|都)|通常|一般|平时|习惯于)"
)


def _chinese_number(value: str) -> float:
    if value.isdigit():
        return float(value)
    if value == "半":
        return 0.5
    digits = {
        "零": 0, "一": 1, "二": 2, "两": 2, "三": 3,
        "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
    }
    if value == "十":
        return 10
    if "百" in value:
        hundreds, remainder = value.split("百", 1)
        return digits.get(hundreds, 1) * 100 + (_chinese_number(remainder) if remainder else 0)
    if "十" in value:
        tens, ones = value.split("十", 1)
        return digits.get(tens, 1) * 10 + digits.get(ones, 0)
    if len(value) == 1 and value in digits:
        return digits[value]
    raise ValueError(f"Unsupported Chinese number: {value}")


def _duration_seconds(count: str, unit: str) -> int:
    seconds = int(_chinese_number(count) * _DURATION_SECONDS[unit.lower()])
    if seconds <= 0:
        raise ValueError("Automation interval must be positive.")
    return seconds


def _apply_period(hour: int, period: str) -> int:
    normalized = period.lower()
    if normalized in {"pm", "下午"} and hour < 12:
        return hour + 12
    if normalized in {"晚上", "今晚"}:
        if hour == 12:
            return 0
        return hour + 12 if hour < 12 else hour
    if normalized == "中午" and hour < 11:
        return hour + 12
    if normalized in {"am", "上午", "早上", "凌晨", "午夜"} and hour == 12:
        return 0
    return hour


def _validated_clock(hour: int, minute: int, period: str = "") -> time:
    hour = _apply_period(hour, period) if period else hour
    if hour > 23 or minute > 59:
        raise ValueError("Invalid hour or minute in automation schedule.")
    return time(hour, minute)


def _parse_clocks(message: str) -> list[time]:
    clocks: list[time] = []
    chinese_period = r"(?:上午|早上|中午|下午|晚上|今晚|凌晨|午夜)"

    for match in re.finditer(
        rf"(?P<period>{chinese_period})?\s*(?P<hour>\d{{1,2}})\s*[:：]\s*(?P<minute>\d{{1,2}})",
        message,
    ):
        clocks.append(_validated_clock(
            int(match.group("hour")),
            int(match.group("minute")),
            match.group("period") or "",
        ))

    for match in re.finditer(
        rf"(?P<period>{chinese_period})?\s*(?P<hour>{_CLOCK_NUMBER_TOKEN})\s*(?:点|时)"
        rf"(?:(?P<half>半)|(?P<quarter>一刻|三刻)|(?P<minute>{_CLOCK_NUMBER_TOKEN})\s*分?)?",
        message,
    ):
        minute = 0
        if match.group("half"):
            minute = 30
        elif match.group("quarter"):
            minute = 15 if match.group("quarter") == "一刻" else 45
        elif match.group("minute"):
            minute = int(_chinese_number(match.group("minute")))
        clocks.append(_validated_clock(
            int(_chinese_number(match.group("hour"))),
            minute,
            match.group("period") or "",
        ))

    for match in re.finditer(
        r"\bat\s+(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<period>am|pm)?\b",
        message,
        flags=re.IGNORECASE,
    ):
        clocks.append(_validated_clock(
            int(match.group("hour")),
            int(match.group("minute") or 0),
            match.group("period") or "",
        ))

    if not clocks:
        if "中午" in message:
            clocks.append(time(12, 0))
        elif "午夜" in message:
            clocks.append(time(0, 0))

    return list(dict.fromkeys(clocks))


def _parse_clock(message: str) -> Optional[time]:
    clocks = _parse_clocks(message)
    return clocks[0] if clocks else None


def _future_date(month: int, day: int, now: datetime, year: Optional[int] = None) -> date:
    target_year = year or now.year
    target = date(target_year, month, day)
    if year is None and target < now.date():
        target = date(target_year + 1, month, day)
    return target


def _relative_weekday(message: str, now: datetime) -> Optional[date]:
    match = _WEEKDAY_PATTERN.search(message)
    if not match or message[max(0, match.start() - 1):match.start()] == "每":
        return None
    target_weekday = (_WEEKDAY_TO_CRON[match.group("day")] - 1) % 7
    prefix = match.group("prefix") or ""
    if prefix == "下":
        days = 7 - now.weekday() + target_weekday
    elif prefix.startswith(("本", "这")):
        days = target_weekday - now.weekday()
    else:
        days = (target_weekday - now.weekday()) % 7
    return (now + timedelta(days=days)).date()


def _combine_local(target_date: date, target_time: time, zone: ZoneInfo) -> datetime:
    naive = datetime.combine(target_date, target_time)
    candidate = naive.replace(tzinfo=zone, fold=0)
    round_trip = candidate.astimezone(ZoneInfo("UTC")).astimezone(zone).replace(tzinfo=None)
    if round_trip != naive:
        raise ValueError("The requested local time does not exist because of a timezone transition.")
    alternate = naive.replace(tzinfo=zone, fold=1)
    if candidate.utcoffset() != alternate.utcoffset():
        raise ValueError("The requested local time is ambiguous because of a timezone transition.")
    return candidate


def _parse_weekday_values(raw: str) -> list[int]:
    values = [_WEEKDAY_TO_CRON[token] for token in re.findall(r"[一二三四五六日天]", raw)]
    return list(dict.fromkeys(values))


def _parse_weekday_range(start: str, end: str) -> str:
    start_value = _WEEKDAY_TO_CRON[start]
    end_value = _WEEKDAY_TO_CRON[end]
    ordered_week = [1, 2, 3, 4, 5, 6, 0]
    start_index = ordered_week.index(start_value)
    end_index = ordered_week.index(end_value)
    if start_index <= end_index:
        values = ordered_week[start_index:end_index + 1]
    else:
        values = ordered_week[start_index:] + ordered_week[:end_index + 1]
    if len(values) == 1:
        return str(values[0])
    if values == list(range(values[0], values[-1] + 1)):
        return f"{values[0]}-{values[-1]}"
    return ",".join(str(value) for value in values)


def _parse_month_days(raw: str) -> list[int]:
    days = [int(value) for value in re.findall(r"\d{1,2}", raw)]
    if any(day < 1 or day > 31 for day in days):
        raise ValueError("Invalid day of month in automation schedule.")
    return list(dict.fromkeys(days))


def _cron_time_fields(clocks: list[time]) -> Optional[tuple[str, str]]:
    if not clocks:
        return None
    minutes = sorted({clock.minute for clock in clocks})
    hours = sorted({clock.hour for clock in clocks})
    if len(minutes) == 1:
        return str(minutes[0]), ",".join(str(hour) for hour in hours)
    if len(hours) == 1:
        return ",".join(str(minute) for minute in minutes), str(hours[0])
    return None


def _cron_for_clocks(clocks: list[time], suffix: str) -> Optional[str]:
    fields = _cron_time_fields(clocks)
    if fields is None:
        return None
    minute, hour = fields
    return f"{minute} {hour} {suffix}"


def _next_month_day(relative_month: str, day: int, now: datetime) -> date:
    month_offset = 1 if relative_month.startswith("下") else 0
    absolute_month = now.month + month_offset
    year = now.year + (absolute_month - 1) // 12
    month = (absolute_month - 1) % 12 + 1
    return date(year, month, day)


def _next_day_of_month(day: int, now: datetime) -> date:
    target = date(now.year, now.month, day)
    if target >= now.date():
        return target
    absolute_month = now.month + 1
    year = now.year + (absolute_month - 1) // 12
    month = (absolute_month - 1) % 12 + 1
    return date(year, month, day)


def _strip_leading_request(message: str) -> str:
    candidate = _LEADING_REQUEST_PATTERN.sub("", message.strip())
    return re.sub(r"^在\s*", "", candidate)


def _schedule_leads_task(message: str) -> bool:
    candidate = _strip_leading_request(message)
    lower = candidate.lower()
    schedule_patterns = (
        _HOURLY_OFFSET_PATTERN,
        _INTERVAL_PATTERN,
        _DAY_INTERVAL_PATTERN,
        _RELATIVE_DELAY_PATTERN,
        _QUARTERLY_PATTERN,
        _MONTH_END_PATTERN,
        _YEARLY_PATTERN,
        _MONTH_DAY_LIST_PATTERN,
        _RECURRING_WEEKDAY_RANGE_PATTERN,
        _RECURRING_WEEKDAY_PATTERN,
        _RELATIVE_MONTH_DAY_PATTERN,
        _EXPLICIT_DATE_PATTERN,
        _ISO_DATE_PATTERN,
        _SHORT_DATE_PATTERN,
        _DAY_OF_MONTH_ONCE_PATTERN,
        _WEEKDAY_PATTERN,
        _EN_INTERVAL_PATTERN,
        _EN_RELATIVE_DELAY_PATTERN,
        _EN_RECURRING_WEEKDAY_PATTERN,
        _EN_NEXT_WEEKDAY_PATTERN,
        _UNSUPPORTED_RECURRENCE_PATTERN,
        _RECURRENCE_MARKER_PATTERN,
    )
    if any(pattern.match(candidate) for pattern in schedule_patterns):
        return True
    return candidate.startswith(
        ("今天", "明天", "后天", "今晚", "明早", "明晚", "工作日", "周末", "每个工作日")
    ) or lower.startswith(("today", "tomorrow", "next ", "every ", "in "))


def has_automation_schedule_signal(message: str) -> bool:
    """Return whether a message has enough temporal context to merit semantic analysis."""
    lower = message.lower()
    return bool(
        any(token.lower() in lower for token in _AUTOMATION_TOKENS)
        or _HOURLY_OFFSET_PATTERN.search(message)
        or _INTERVAL_PATTERN.search(message)
        or _DAY_INTERVAL_PATTERN.search(message)
        or _RELATIVE_DELAY_PATTERN.search(message)
        or _EN_INTERVAL_PATTERN.search(message)
        or _RECURRENCE_MARKER_PATTERN.search(message)
        or _UNSUPPORTED_RECURRENCE_PATTERN.search(message)
        or _EXPLICIT_DATE_PATTERN.search(message)
        or _ISO_DATE_PATTERN.search(message)
        or _SHORT_DATE_PATTERN.search(message)
        or _RELATIVE_MONTH_DAY_PATTERN.search(message)
        or _DAY_OF_MONTH_ONCE_PATTERN.search(message)
        or _WEEKDAY_PATTERN.search(message)
        or _EN_NEXT_WEEKDAY_PATTERN.search(message)
        or _EN_RELATIVE_DELAY_PATTERN.search(message)
        or _parse_clocks(message)
        or any(token in message for token in ("今天", "明天", "后天", "今晚", "明早", "明晚", "稍后", "待会"))
        or re.search(r"\b(?:today|tomorrow|daily|weekly|monthly|yearly|schedule|scheduled)\b", lower)
    )


def _looks_like_automation(message: str) -> bool:
    lower = message.lower()
    has_action = (
        any(token in message for token in _ACTION_TOKENS)
        or bool(re.search(r"发(?!现|生|布|起|挥|明|热)", message))
        or bool(
            re.search(
                r"\b(?:send|remind|generate|summarize|check|notify|run|execute|create|"
                r"calculate|fetch|get|retrieve|find|search|analyze|process|save|upload|download)\b",
                lower,
            )
        )
    )
    question_like = bool(_QUESTION_PATTERN.search(message))
    explicit_request = bool(
        re.search(
            r"(?:提醒我|告诉我|帮我|给我|为我|麻烦你|请你|请帮我|需要你|我要你|我希望你|我想让你)",
            message,
        )
        or re.search(r"\b(?:please|remind me|tell me)\b", lower)
    )
    has_action_command = has_action and (not question_like or explicit_request)
    if not has_automation_schedule_signal(message):
        return False

    explicit_automation = bool(_EXPLICIT_AUTOMATION_PATTERN.search(message))
    schedule_leads_task = _schedule_leads_task(message)
    business_action = _extract_business_action(message)

    if question_like:
        return explicit_automation or (schedule_leads_task and explicit_request and has_action)
    if explicit_automation:
        return True
    if not schedule_leads_task or not business_action:
        return False
    if _DECLARATIVE_ACTION_PATTERN.search(business_action):
        return False
    return has_action_command or bool(business_action)


def _resolve_timezone(message: str, default_timezone: str) -> str:
    for pattern, timezone_name in _TIMEZONE_ALIASES:
        if pattern.search(message):
            return timezone_name
    if match := _IANA_TIMEZONE_PATTERN.search(message):
        return match.group(0)
    return default_timezone


def _normalize_schedule_phrases(message: str) -> str:
    replacements = (
        ("明早", "明天早上"),
        ("明晚", "明天晚上"),
        ("今早", "今天早上"),
        ("每晚", "每天晚上"),
        ("每早", "每天早上"),
    )
    normalized = message
    for source, target in replacements:
        normalized = normalized.replace(source, target)
    return normalized


def _extract_business_action(message: str) -> str:
    cleaned = message
    schedule_patterns = (
        _HOURLY_OFFSET_PATTERN,
        _INTERVAL_PATTERN,
        _DAY_INTERVAL_PATTERN,
        _RELATIVE_DELAY_PATTERN,
        _QUARTERLY_PATTERN,
        _MONTH_END_PATTERN,
        _YEARLY_PATTERN,
        _MONTH_DAY_LIST_PATTERN,
        _RECURRING_WEEKDAY_RANGE_PATTERN,
        _RECURRING_WEEKDAY_PATTERN,
        _RELATIVE_MONTH_DAY_PATTERN,
        _EXPLICIT_DATE_PATTERN,
        _ISO_DATE_PATTERN,
        _SHORT_DATE_PATTERN,
        _DAY_OF_MONTH_ONCE_PATTERN,
        _WEEKDAY_PATTERN,
        _EN_INTERVAL_PATTERN,
        _EN_RELATIVE_DELAY_PATTERN,
        _EN_RECURRING_WEEKDAY_PATTERN,
        _EN_NEXT_WEEKDAY_PATTERN,
        _TIMEZONE_PATTERN,
        _IANA_TIMEZONE_PATTERN,
        _UNSUPPORTED_RECURRENCE_PATTERN,
    )
    for pattern in schedule_patterns:
        cleaned = pattern.sub("", cleaned)
    cleaned = re.sub(
        r"(?:每天|每日|每晚|每个工作日|工作日|周一到周五|周末|"
        r"今天|明天|后天|今晚|明早|明晚)",
        "",
        cleaned,
    )
    cleaned = re.sub(r"(?:上午|早上|中午|下午|晚上|凌晨|午夜)", "", cleaned)
    cleaned = re.sub(
        rf"{_CLOCK_NUMBER_TOKEN}\s*(?:"
        rf"[:：]\s*{_CLOCK_NUMBER_TOKEN}|"
        rf"(?:点|时)(?:(?:半|一刻|三刻)|(?:{_CLOCK_NUMBER_TOKEN})\s*分?)?"
        rf")",
        "",
        cleaned,
    )
    cleaned = re.sub(r"\bat\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\b(?:every\s+(?:day|weekday|weekend)|weekdays?|weekends?|"
        r"tomorrow(?!['’]s)|today(?!['’]s))\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = _strip_leading_request(cleaned)
    if re.search(r"(?:创建|新建|添加|设置|设定|安排|建立|配置).*任务", message):
        cleaned = re.sub(
            r"^(?:创建|新建|添加|设置|设定|安排|建立|配置)(?:一个|一条|个)?\s*",
            "",
            cleaned,
        )
        cleaned = re.sub(r"\s*的?(?:(?:定时|自动|周期|计划)\s*)?任务$", "", cleaned)
    cleaned = re.sub(r"^(?:定时执行|定时)\s*", "", cleaned)
    cleaned = re.sub(r"^的\s*", "", cleaned)
    cleaned = re.sub(r"^(?:[、,，/]|和|及)+\s*", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，,。；;：:")
    return cleaned


def _clean_action(message: str) -> str:
    return _extract_business_action(message) or message.strip()


def _invalid_schedule(message: str, reason: str, confidence: float = 0.9) -> dict:
    return {
        "is_automation_intent": True,
        "confidence": confidence,
        "title": "",
        "instruction": _clean_action(message),
        "schedule_trigger": None,
        "schedule_error": reason,
        "capability_intents": [],
        "output_requirements": {},
    }


def _success(message: str, trigger: ScheduleTrigger, confidence: float = 0.96) -> dict:
    instruction = _clean_action(message)
    return {
        "is_automation_intent": True,
        "confidence": confidence,
        "title": instruction[:30] or "自动任务",
        "instruction": instruction,
        "schedule_trigger": trigger,
        "schedule_error": None,
        "capability_intents": [],
        "output_requirements": {},
    }


def _cron_trigger(now: datetime, timezone_name: str, expression: str) -> ScheduleTrigger:
    return ScheduleTrigger(
        mode=ScheduleMode.RECURRING,
        rule_type=ScheduleRuleType.CRON,
        timezone=timezone_name,
        start_at=now.replace(second=0, microsecond=0),
        cron_expr=expression,
    )


def _recurring_cron_result(
    message: str,
    now: datetime,
    timezone_name: str,
    clocks: list[time],
    suffix: str,
    missing_time_error: str,
) -> dict:
    if not clocks:
        return _invalid_schedule(message, missing_time_error)
    expression = _cron_for_clocks(clocks, suffix)
    if expression is None:
        return _invalid_schedule(
            message,
            "一个任务中的多个执行时刻必须具有相同的小时或分钟，请拆分为多个任务。",
        )
    return _success(message, _cron_trigger(now, timezone_name, expression))


def parse_automation_intent(
    message: str,
    timezone_name: str = "Asia/Shanghai",
    tenant_id: str | None = None,
    reference_time: Optional[datetime] = None,
) -> dict:
    """Parse natural-language scheduling independently from task prompt generation."""
    del tenant_id
    message = _normalize_schedule_phrases(message)
    timezone_name = _resolve_timezone(message, timezone_name)
    try:
        zone = ZoneInfo(timezone_name)
    except Exception as exc:
        raise ValueError(f"Invalid automation timezone: {timezone_name}") from exc
    now = reference_time or datetime.now(zone)
    now = now.astimezone(zone) if now.tzinfo else now.replace(tzinfo=zone)

    if not _looks_like_automation(message):
        return {"is_automation_intent": False, "confidence": 0.0}

    hourly_offset = _HOURLY_OFFSET_PATTERN.search(message)
    if hourly_offset:
        if hourly_offset.group("marker") == "整点":
            minute = 0
        elif hourly_offset.group("marker") == "半点":
            minute = 30
        else:
            minute = int(_chinese_number(hourly_offset.group("minute")))
        if minute > 59:
            return _invalid_schedule(message, "每小时执行的分钟数必须在 0 到 59 之间。")
        return _success(message, _cron_trigger(now, timezone_name, f"{minute} * * * *"))

    interval_match = _INTERVAL_PATTERN.search(message) or _DAY_INTERVAL_PATTERN.search(message)
    if interval_match:
        count = interval_match.group("count") or "一"
        unit = interval_match.group("unit") if "unit" in interval_match.groupdict() else "天"
        seconds = _duration_seconds(count, unit)
        trigger = ScheduleTrigger(
            mode=ScheduleMode.RECURRING,
            rule_type=ScheduleRuleType.INTERVAL,
            timezone=timezone_name,
            start_at=now.replace(microsecond=0) + timedelta(seconds=seconds),
            interval_seconds=seconds,
        )
        return _success(message, trigger)

    en_interval = _EN_INTERVAL_PATTERN.search(message)
    if en_interval:
        seconds = _duration_seconds(en_interval.group("count") or "1", en_interval.group("unit"))
        trigger = ScheduleTrigger(
            mode=ScheduleMode.RECURRING,
            rule_type=ScheduleRuleType.INTERVAL,
            timezone=timezone_name,
            start_at=now.replace(microsecond=0) + timedelta(seconds=seconds),
            interval_seconds=seconds,
        )
        return _success(message, trigger)

    delay_match = _RELATIVE_DELAY_PATTERN.search(message)
    if delay_match:
        seconds = _duration_seconds(delay_match.group("count"), delay_match.group("unit"))
        trigger = ScheduleTrigger(
            mode=ScheduleMode.ONCE,
            rule_type=ScheduleRuleType.AT,
            timezone=timezone_name,
            start_at=now + timedelta(seconds=seconds),
        )
        return _success(message, trigger)

    en_delay = _EN_RELATIVE_DELAY_PATTERN.search(message)
    if en_delay:
        seconds = _duration_seconds(en_delay.group("count"), en_delay.group("unit"))
        trigger = ScheduleTrigger(
            mode=ScheduleMode.ONCE,
            rule_type=ScheduleRuleType.AT,
            timezone=timezone_name,
            start_at=now + timedelta(seconds=seconds),
        )
        return _success(message, trigger)

    lower = message.lower()
    target_clocks = _parse_clocks(message)
    target_time = target_clocks[0] if target_clocks else None
    if any(token in message for token in ("每天", "每日")) or "every day" in lower:
        return _recurring_cron_result(
            message, now, timezone_name, target_clocks, "* * *", "请明确每天执行的具体时间。"
        )

    if any(token in message for token in ("工作日", "周一到周五", "每个工作日")):
        return _recurring_cron_result(
            message, now, timezone_name, target_clocks, "* * 1-5", "请明确工作日执行的具体时间。"
        )

    if re.search(r"\bevery\s+weekday\b", lower):
        return _recurring_cron_result(
            message,
            now,
            timezone_name,
            target_clocks,
            "* * 1-5",
            "Please specify the execution time for every weekday.",
        )

    if "周末" in message:
        return _recurring_cron_result(
            message, now, timezone_name, target_clocks, "* * 0,6", "请明确周末执行的具体时间。"
        )

    if re.search(r"\bevery\s+weekend\b", lower):
        return _recurring_cron_result(
            message,
            now,
            timezone_name,
            target_clocks,
            "* * 0,6",
            "Please specify the execution time for every weekend.",
        )

    weekday_range_match = _RECURRING_WEEKDAY_RANGE_PATTERN.search(message)
    if weekday_range_match:
        weekdays = _parse_weekday_range(
            weekday_range_match.group("start"),
            weekday_range_match.group("end"),
        )
        return _recurring_cron_result(
            message,
            now,
            timezone_name,
            target_clocks,
            f"* * {weekdays}",
            "请明确每周任务执行的具体时间。",
        )

    weekday_match = _RECURRING_WEEKDAY_PATTERN.search(message)
    if weekday_match:
        weekdays = ",".join(str(day) for day in _parse_weekday_values(weekday_match.group("days")))
        return _recurring_cron_result(
            message,
            now,
            timezone_name,
            target_clocks,
            f"* * {weekdays}",
            "请明确每周任务执行的具体时间。",
        )

    for weekday_name, cron_day in _EN_WEEKDAY_TO_CRON.items():
        if re.search(rf"\bevery\s+{weekday_name}\b", lower):
            return _recurring_cron_result(
                message,
                now,
                timezone_name,
                target_clocks,
                f"* * {cron_day}",
                f"Please specify the execution time for every {weekday_name}.",
            )

    month_match = _MONTH_DAY_LIST_PATTERN.search(message)
    if month_match:
        month_days = ",".join(str(day) for day in _parse_month_days(month_match.group("days")))
        return _recurring_cron_result(
            message,
            now,
            timezone_name,
            target_clocks,
            f"{month_days} * *",
            "请明确每月任务执行的具体时间。",
        )

    if _MONTH_END_PATTERN.search(message):
        return _recurring_cron_result(
            message, now, timezone_name, target_clocks, "L * *", "请明确每月任务执行的具体时间。"
        )

    quarter_match = _QUARTERLY_PATTERN.search(message)
    if quarter_match:
        day_token = quarter_match.group("day")
        day = 1 if day_token == "一" else int(day_token)
        if day < 1 or day > 31:
            return _invalid_schedule(message, "季度任务的日期必须在 1 到 31 之间。")
        return _recurring_cron_result(
            message,
            now,
            timezone_name,
            target_clocks,
            f"{day} 1,4,7,10 *",
            "请明确季度任务执行的具体时间。",
        )

    yearly_match = _YEARLY_PATTERN.search(message)
    if yearly_match:
        month = int(yearly_match.group("month"))
        day = int(yearly_match.group("day"))
        _future_date(month, day, now, now.year)
        return _recurring_cron_result(
            message,
            now,
            timezone_name,
            target_clocks,
            f"{day} {month} *",
            "请明确每年任务执行的具体时间。",
        )

    if unsupported_recurrence := _UNSUPPORTED_RECURRENCE_PATTERN.search(message):
        unit = unsupported_recurrence.group("unit")
        return _invalid_schedule(
            message,
            f"暂不支持按多个{unit}生成单一精确规则，请改用明确月份或拆分任务。",
        )

    if _RECURRENCE_MARKER_PATTERN.search(message):
        return _invalid_schedule(message, "周期任务缺少可确定的日期或时间，请补充完整。")

    if target_time is None:
        return _invalid_schedule(message, "无法确定任务执行时间，请补充具体日期和时间。")
    if len(target_clocks) > 1:
        return _invalid_schedule(
            message,
            "一次性任务只能指定一个执行时刻，请拆分为多个任务。",
        )

    target_date: Optional[date] = None
    explicit_date = _EXPLICIT_DATE_PATTERN.search(message) or _ISO_DATE_PATTERN.search(message)
    if explicit_date:
        target_date = _future_date(
            int(explicit_date.group("month")),
            int(explicit_date.group("day")),
            now,
            int(explicit_date.group("year")) if explicit_date.group("year") else None,
        )
    elif relative_month_date := _RELATIVE_MONTH_DAY_PATTERN.search(message):
        target_date = _next_month_day(
            relative_month_date.group("relative_month"),
            int(relative_month_date.group("day")),
            now,
        )
    elif short_date := _SHORT_DATE_PATTERN.search(message):
        target_date = _future_date(
            int(short_date.group("month")),
            int(short_date.group("day")),
            now,
        )
    elif "后天" in message:
        target_date = (now + timedelta(days=2)).date()
    elif "明天" in message or "tomorrow" in lower:
        target_date = (now + timedelta(days=1)).date()
    elif "今天" in message or "今晚" in message or "today" in lower:
        target_date = now.date()
    elif en_next_weekday := _EN_NEXT_WEEKDAY_PATTERN.search(message):
        cron_weekday = _EN_WEEKDAY_TO_CRON[en_next_weekday.group("day").lower()]
        target_weekday = (cron_weekday - 1) % 7
        days = (target_weekday - now.weekday()) % 7 or 7
        target_date = (now + timedelta(days=days)).date()
    else:
        target_date = _relative_weekday(message, now)
        if target_date is None and (day_match := _DAY_OF_MONTH_ONCE_PATTERN.search(message)):
            target_date = _next_day_of_month(int(day_match.group("day")), now)

    if target_date is None:
        return _invalid_schedule(message, "无法确定任务执行日期，请补充具体日期。")
    if target_time == time(0, 0) and re.search(r"(?:今晚|晚上)\s*12\s*(?:点|时)", message):
        target_date += timedelta(days=1)
    start_at = _combine_local(target_date, target_time, zone)
    if start_at <= now:
        return _invalid_schedule(message, "指定的执行时间已经过去，请提供未来时间。")
    trigger = ScheduleTrigger(
        mode=ScheduleMode.ONCE,
        rule_type=ScheduleRuleType.AT,
        timezone=timezone_name,
        start_at=start_at,
    )
    return _success(message, trigger)
