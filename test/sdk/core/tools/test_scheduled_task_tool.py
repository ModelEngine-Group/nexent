"""Unit tests for ScheduledTaskTool cron expression validation and fire-time computation.

These tests focus on the pure cron-parsing logic (``_parse_cron`` /
``_expand_cron_field``) and next-fire-time calculation
(``_compute_next_fire``), which are the most error-prone parts of the
scheduled-task feature.

The target module is loaded directly from its file path with a stubbed
``smolagents.tools.Tool`` base class, so the tests do not require the full
SDK environment (which pulls in memory/embedding model dependencies).
"""
import importlib.util
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Stub smolagents.tools.Tool before loading the module under test, so it
# imports without the heavy SDK dependency chain.
if "smolagents" not in sys.modules:
    smolagents_stub = types.ModuleType("smolagents")
    tools_stub = types.ModuleType("smolagents.tools")

    class _Tool:  # Minimal stand-in for smolagents.tools.Tool
        pass

    tools_stub.Tool = _Tool
    smolagents_stub.tools = tools_stub
    sys.modules["smolagents"] = smolagents_stub
    sys.modules["smolagents.tools"] = tools_stub

# Load the tool module directly from its file to avoid triggering the
# sdk/nexent/__init__.py chain (which imports memory/embedding models).
_TOOL_PATH = (
    Path(__file__).resolve().parents[4]
    / "sdk" / "nexent" / "core" / "tools" / "scheduled_task_tool.py"
)
_spec = importlib.util.spec_from_file_location("scheduled_task_tool", _TOOL_PATH)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

ScheduledTaskTool = _module.ScheduledTaskTool
_expand_cron_field = _module._expand_cron_field


BASE = datetime(2026, 6, 24, 8, 5, tzinfo=timezone.utc)  # Wednesday


# ---------------------------------------------------------------------------
# _expand_cron_field
# ---------------------------------------------------------------------------

def test_expand_star_returns_full_range():
    assert _expand_cron_field("*", 0, 5) == frozenset({0, 1, 2, 3, 4, 5})


def test_expand_exact_value():
    assert _expand_cron_field("9", 0, 59) == frozenset({9})


def test_expand_range():
    assert _expand_cron_field("1-5", 0, 59) == frozenset({1, 2, 3, 4, 5})


def test_expand_step_from_star():
    assert _expand_cron_field("*/15", 0, 59) == frozenset({0, 15, 30, 45})


def test_expand_step_from_range():
    assert _expand_cron_field("1-30/10", 0, 59) == frozenset({1, 11, 21})


def test_expand_comma_list():
    assert _expand_cron_field("1,3,5", 0, 59) == frozenset({1, 3, 5})


def test_expand_comma_mixed():
    assert _expand_cron_field("0,15-18,30", 0, 59) == frozenset({0, 15, 16, 17, 18, 30})


def test_expand_sunday_seven_normalized_to_zero():
    # day_of_week uses [0,7] where both 0 and 7 mean Sunday
    assert _expand_cron_field("7", 0, 7) == frozenset({0})


def test_expand_out_of_range_raises():
    with pytest.raises(ValueError):
        _expand_cron_field("60", 0, 59)
    with pytest.raises(ValueError):
        _expand_cron_field("5-3", 0, 59)


def test_expand_zero_step_raises():
    with pytest.raises(ValueError):
        _expand_cron_field("*/0", 0, 59)


# ---------------------------------------------------------------------------
# _parse_cron
# ---------------------------------------------------------------------------

def test_parse_valid_expression():
    parts = ScheduledTaskTool._parse_cron("0 9 * * *")
    assert parts["minute"] == frozenset({0})
    assert parts["hour"] == frozenset({9})
    assert parts["day_of_month"] == frozenset(range(1, 32))
    assert parts["month"] == frozenset(range(1, 13))
    # day_of_week '*' covers 0-7, but 7 is normalized to Sunday (0)
    assert parts["day_of_week"] == frozenset(range(0, 7))


def test_parse_complex_expression():
    parts = ScheduledTaskTool._parse_cron("*/15 9-18 * * 1-5")
    assert parts["minute"] == frozenset({0, 15, 30, 45})
    assert parts["hour"] == frozenset(range(9, 19))
    assert parts["day_of_week"] == frozenset({1, 2, 3, 4, 5})


@pytest.mark.parametrize("expr", [
    "bad expr",
    "99 * * * *",      # minute out of range
    "* * *",           # too few fields
    "* * * * * *",     # too many fields
    "*/0 * * * *",     # zero step
    "0 13 32 * *",     # day out of range
    "0 9 * 13 *",      # month out of range
    "a b c d e",       # non-numeric
])
def test_parse_invalid_returns_none(expr):
    assert ScheduledTaskTool._parse_cron(expr) is None


# ---------------------------------------------------------------------------
# _compute_next_fire
# ---------------------------------------------------------------------------

def test_next_fire_daily_at_9am():
    parts = ScheduledTaskTool._parse_cron("0 9 * * *")
    nxt = ScheduledTaskTool._compute_next_fire(parts, BASE)
    assert nxt.replace(tzinfo=None) == datetime(2026, 6, 24, 9, 0)


def test_next_fire_every_15_minutes():
    parts = ScheduledTaskTool._parse_cron("*/15 * * * *")
    nxt = ScheduledTaskTool._compute_next_fire(parts, BASE)
    assert nxt.replace(tzinfo=None) == datetime(2026, 6, 24, 8, 15)


def test_next_fire_weekdays_9am():
    parts = ScheduledTaskTool._parse_cron("0 9 * * 1-5")
    nxt = ScheduledTaskTool._compute_next_fire(parts, BASE)
    # 2026-06-24 is a Wednesday (weekday), so same day 9:00
    assert nxt.replace(tzinfo=None) == datetime(2026, 6, 24, 9, 0)


def test_next_fire_skips_to_next_allowed_day():
    # 1st and 15th of each month, 14:30. From June 24 (past the 15th),
    # the next allowed day is July 1.
    parts = ScheduledTaskTool._parse_cron("30 14 1,15 * *")
    nxt = ScheduledTaskTool._compute_next_fire(parts, BASE)
    assert nxt.replace(tzinfo=None) == datetime(2026, 7, 1, 14, 30)


def test_next_fire_specific_month():
    # Only January 1, 9am. From June, must roll to next year.
    parts = ScheduledTaskTool._parse_cron("0 9 1 1 *")
    nxt = ScheduledTaskTool._compute_next_fire(parts, BASE)
    assert nxt.replace(tzinfo=None) == datetime(2027, 1, 1, 9, 0)


def test_next_fire_impossible_expression_falls_back():
    # February 30 never exists. Should fall back to +1 hour instead of
    # looping forever.
    parts = ScheduledTaskTool._parse_cron("0 9 30 2 *")
    assert parts is not None  # parsing succeeds (30 and 2 are individually valid)
    nxt = ScheduledTaskTool._compute_next_fire(parts, BASE)
    # Fallback is from_timestamp + 1 hour
    assert nxt == BASE + timedelta(hours=1)


def test_next_fire_already_past_today_hour_jumps_to_tomorrow():
    # 7am daily, current time is 8:05 → next is tomorrow 7am
    parts = ScheduledTaskTool._parse_cron("0 7 * * *")
    nxt = ScheduledTaskTool._compute_next_fire(parts, BASE)
    assert nxt.replace(tzinfo=None) == datetime(2026, 6, 25, 7, 0)
