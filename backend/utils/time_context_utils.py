"""Format and remove the runtime-only current-time message prefix."""

from datetime import datetime
from zoneinfo import ZoneInfo

CURRENT_TIME_PREFIX = "[Current time:"


def prepend_current_time(query: str, timezone: str | None, *, now: datetime | None = None) -> str:
    """Leave missing/invalid timezones and already-prefixed messages unchanged."""
    if timezone and query and not query.startswith(CURRENT_TIME_PREFIX):
        try:
            zone = ZoneInfo(timezone)
            current = now.astimezone(zone) if now is not None else datetime.now(zone)
            return f"{CURRENT_TIME_PREFIX} {current:%Y-%m-%d %H:%M:%S}]\n\n{query}"
        except Exception:
            pass
    return query


def strip_current_time_prefix(query: str | None) -> str | None:
    """Strip one complete prefix, preserving unmarked or malformed input."""
    if query and query.startswith(CURRENT_TIME_PREFIX):
        end = query.find("]", len(CURRENT_TIME_PREFIX))
        if end >= 0:
            return query[end + 1:].lstrip("\n").strip()
    return query
