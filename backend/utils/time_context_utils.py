"""Format and remove runtime-only time markers in user messages."""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from nexent.core.agents.prompt.user_context import has_current_time_prefix, render_user_context


def prepend_current_time(query: str, timezone: str | None, *, now: datetime | None = None, language: str = "en") -> str:
    """Append local time before workspace; retain the legacy public function name."""
    if timezone and query and not has_current_time_prefix(query):
        try:
            zone = ZoneInfo(timezone)
            current = now.astimezone(zone) if now is not None else datetime.now(zone)
            return render_user_context(language, "current_time", {"time": current.strftime("%Y-%m-%d %H:%M:%S"), "query": query})
        except Exception:
            pass
    return query


def strip_current_time_prefix(query: str | None) -> str | None:
    """Remove a complete runtime time marker in either supported position."""
    if query and has_current_time_prefix(query):
        return re.sub(
            r"(?m)^\[(?:当前时间|Current time): [^\]\n]+\](?:\n\n|$)", "", query, count=1,
        ).strip()
    return query
