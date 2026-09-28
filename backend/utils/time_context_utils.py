"""Format and remove the runtime-only current-time message prefix."""

from datetime import datetime
from zoneinfo import ZoneInfo
from nexent.core.agents.prompt.user_context import has_current_time_prefix, render_user_context


def prepend_current_time(query: str, timezone: str | None, *, now: datetime | None = None, language: str = "en") -> str:
    """Leave missing/invalid timezones and already-prefixed messages unchanged."""
    if timezone and query and not has_current_time_prefix(query):
        try:
            zone = ZoneInfo(timezone)
            current = now.astimezone(zone) if now is not None else datetime.now(zone)
            return render_user_context(language, "current_time", {"time": current.strftime("%Y-%m-%d %H:%M:%S"), "query": query})
        except Exception:
            pass
    return query


def strip_current_time_prefix(query: str | None) -> str | None:
    """Strip one complete prefix, preserving unmarked or malformed input."""
    if query and has_current_time_prefix(query):
        end = query.find("]")
        if end >= 0:
            return query[end + 1:].lstrip("\n").strip()
    return query
