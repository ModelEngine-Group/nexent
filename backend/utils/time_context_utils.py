"""Format and remove runtime-only time markers in user messages."""

from datetime import datetime
from zoneinfo import ZoneInfo

from nexent.core.agents.prompt.user_context import CURRENT_TIME_MARKER, has_current_time_marker, render_user_context


def prepend_current_time(query: str, timezone: str | None, *, now: datetime | None = None, language: str = "en") -> str:
    """Append local time before workspace; retain the legacy public function name."""
    if timezone and query and not has_current_time_marker(query):
        try:
            zone = ZoneInfo(timezone)
            current = now.astimezone(zone) if now is not None else datetime.now(zone)
            return render_user_context(language, "current_time", {"time": current.strftime("%Y-%m-%d %H:%M:%S"), "query": query})
        except Exception:
            pass
    return query


def strip_current_time_prefix(query: str | None) -> str | None:
    """Remove only the current runtime marker appended after the request."""
    if query:
        return CURRENT_TIME_MARKER.sub("", query, count=1)
    return query
