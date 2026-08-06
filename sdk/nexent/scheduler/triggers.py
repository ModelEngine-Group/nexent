"""Pure schedule calculation for one-shot, interval, and cron triggers."""

from calendar import monthrange
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from zoneinfo import ZoneInfo


try:
    from croniter import croniter
except ImportError:  # pragma: no cover - optional optimized evaluator
    croniter = None


class ScheduleMode(str, Enum):
    ONCE = "ONCE"
    RECURRING = "RECURRING"


class ScheduleRuleType(str, Enum):
    AT = "AT"
    INTERVAL = "INTERVAL"
    CRON = "CRON"


@dataclass(frozen=True)
class ScheduleSpec:
    """Framework-independent normalized schedule definition."""

    mode: ScheduleMode
    rule_type: ScheduleRuleType
    timezone: str
    start_at: datetime
    end_at: datetime | None = None
    cron_expr: str | None = None
    interval_seconds: int | None = None
    max_fire_count: int | None = None


def is_valid_cron_expression(expression: str) -> bool:
    """Validate a five-field cron expression."""
    if len((expression or "").split()) != 5:
        return False
    if croniter is not None:
        try:
            return bool(croniter.is_valid(expression))
        except Exception:
            return False
    minute, hour, day_of_month, month, day_of_week = expression.split()
    return all((
        _is_valid_cron_field(minute, 0, 59),
        _is_valid_cron_field(hour, 0, 23),
        _is_valid_cron_field(day_of_month, 1, 31, allow_last=True),
        _is_valid_cron_field(month, 1, 12),
        _is_valid_cron_field(day_of_week, 0, 7),
    ))


def _is_valid_cron_field(field: str, minimum: int, maximum: int, allow_last: bool = False) -> bool:
    if not field:
        return False
    for part in field.split(","):
        base, separator, step = part.partition("/")
        if separator and (not step.isdigit() or int(step) <= 0):
            return False
        if base == "*":
            continue
        if allow_last and base == "L" and not separator:
            continue
        if "-" in base:
            start, end = base.split("-", 1)
            if not start.isdigit() or not end.isdigit():
                return False
            if not (minimum <= int(start) <= int(end) <= maximum):
                return False
            continue
        if not base.isdigit() or not minimum <= int(base) <= maximum:
            return False
    return True


def _ensure_aware(value: datetime, timezone_name: str) -> datetime:
    zone = ZoneInfo(timezone_name)
    if value.tzinfo is None:
        return value.replace(tzinfo=zone)
    return value.astimezone(zone)


def compute_next_fire_at(spec: ScheduleSpec, after: datetime, fire_count: int) -> datetime | None:
    """Compute the next UTC fire time without persistence or framework dependencies."""
    local_after = _ensure_aware(after, spec.timezone)
    start_at = _ensure_aware(spec.start_at, spec.timezone)
    end_at = _ensure_aware(spec.end_at, spec.timezone) if spec.end_at else None

    if spec.max_fire_count is not None and fire_count >= spec.max_fire_count:
        return None

    if spec.mode == ScheduleMode.ONCE:
        if fire_count > 0:
            return None
        next_fire = start_at if start_at >= local_after else local_after
    elif spec.rule_type == ScheduleRuleType.INTERVAL:
        if not spec.interval_seconds or spec.interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive for interval schedules")
        if local_after <= start_at:
            next_fire = start_at
        else:
            elapsed = (local_after - start_at).total_seconds()
            steps = int(elapsed // spec.interval_seconds) + 1
            next_fire = start_at + timedelta(seconds=steps * spec.interval_seconds)
    elif spec.rule_type == ScheduleRuleType.CRON:
        if not is_valid_cron_expression(spec.cron_expr or ""):
            raise ValueError(f"Invalid cron expression: {spec.cron_expr}")
        base = max(local_after, start_at)
        if local_after <= start_at and _cron_matches_start(spec.cron_expr or "", start_at):
            next_fire = start_at
        elif croniter is not None:
            next_fire = croniter(spec.cron_expr, base).get_next(datetime)
            if next_fire < start_at:
                next_fire = croniter(spec.cron_expr, start_at).get_next(datetime)
        else:
            next_fire = _fallback_next_cron(spec.cron_expr or "", base)
    else:
        raise ValueError(f"Unsupported schedule combination: {spec.mode}/{spec.rule_type}")

    if end_at and next_fire > end_at:
        return None
    return next_fire.astimezone(timezone.utc)


def _cron_matches_start(expr: str, start_at: datetime) -> bool:
    if croniter is not None:
        try:
            return bool(croniter.match(expr, start_at))
        except Exception:
            return False
    parts = (expr or "").split()
    if len(parts) != 5:
        return False

    minute, hour, day_of_month, month, day_of_week = parts
    day_of_month_matches = _cron_day_of_month_matches(day_of_month, start_at)
    day_of_week_matches = _cron_weekday_matches(day_of_week, start_at)
    if day_of_month != "*" and day_of_week != "*":
        calendar_day_matches = day_of_month_matches or day_of_week_matches
    else:
        calendar_day_matches = day_of_month_matches and day_of_week_matches
    return all((
        _cron_field_matches(minute, start_at.minute),
        _cron_field_matches(hour, start_at.hour),
        _cron_field_matches(month, start_at.month),
        calendar_day_matches,
    ))


def _cron_field_matches(field: str, value: int) -> bool:
    if field == "*":
        return True
    for part in field.split(","):
        base, _, step = part.partition("/")
        step_value = int(step) if step.isdigit() else 1
        if base == "*" and value % step_value == 0:
            return True
        if "-" in base:
            start, end = (int(item) for item in base.split("-", 1))
            if start <= value <= end and (value - start) % step_value == 0:
                return True
        elif base.isdigit() and int(base) == value:
            return True
    return False


def _cron_day_of_month_matches(field: str, value: datetime) -> bool:
    if field == "L":
        return value.day == monthrange(value.year, value.month)[1]
    return _cron_field_matches(field, value.day)


def _cron_weekday_matches(field: str, value: datetime) -> bool:
    if field == "*":
        return True
    cron_weekday = (value.weekday() + 1) % 7
    return _cron_field_matches(field, cron_weekday) or (
        cron_weekday == 0 and _cron_field_matches(field, 7)
    )


def _fallback_next_cron(expr: str, base: datetime) -> datetime:
    if not is_valid_cron_expression(expr):
        raise ValueError(f"Invalid cron expression: {expr}")
    target = base.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(366 * 5 * 24 * 60):
        if _cron_matches_start(expr, target):
            return target
        target += timedelta(minutes=1)
    raise ValueError("Unable to find the next fire time for cron expression")
