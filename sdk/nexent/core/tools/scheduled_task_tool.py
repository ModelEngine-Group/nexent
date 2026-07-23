"""Scheduled task tool - thin CRUD wrapper for creating, listing, and cancelling scheduled tasks."""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from smolagents.tools import Tool

logger = logging.getLogger("scheduled_task_tool")


class ScheduledTaskTool(Tool):
    name = "scheduled_task"
    description = (
        "Manage scheduled tasks via the 'action' parameter:\n"
        "- 'create': schedule a new task (needs task_prompt + a time field).\n"
        "- 'list': return all of the caller's pending tasks (no other params).\n"
        "- 'cancel': delete a task. Call 'list' first, cancel by the task_uuid returned in "
        "that result, then call 'list' again to confirm it is gone before reporting success."
    )
    description_zh = (
        "通过 'action' 参数管理定时任务：\n"
        "- 'create'：创建新任务（需要 task_prompt + 时间字段）。\n"
        "- 'list'：返回调用者当前所有待执行任务（无需其他参数）。\n"
        "- 'cancel'：删除任务。先调用 list，用返回结果里的 task_uuid 取消，"
        "再调用 list 确认已删除后，才回报成功。"
    )

    inputs = {
        "action": {
            "type": "string",
            "description": "'create', 'list', or 'cancel'.",
            "description_zh": "'create'（创建）、'list'（查看）或 'cancel'（取消）。",
        },
        "task_name": {
            "type": "string",
            "description": "Human-readable task name. Used in create; accepted as identifier in cancel.",
            "description_zh": "任务名称（人类可读）。创建时使用，取消时也可作为标识。",
            "nullable": True,
        },
        "task_prompt": {
            "type": "string",
            "description": "Instruction executed when the task fires. Required for create.",
            "description_zh": "任务触发时要执行的指令，create 时必填。",
            "nullable": True,
        },
        "task_type": {
            "type": "string",
            "description": "Auto-inferred from the time field; usually omit. 'cron' or 'oneshot'.",
            "description_zh": "由时间字段自动推断，通常无需指定。取值 'cron' 或 'oneshot'。",
            "nullable": True,
        },
        "cron_expression": {
            "type": "string",
            "description": "Standard 5-field cron expression for a recurring task. Mutually exclusive with delay_seconds.",
            "description_zh": "标准 5 字段 cron 表达式，用于周期任务。与 delay_seconds 互斥。",
            "nullable": True,
        },
        "delay_seconds": {
            "type": "integer",
            "description": "Seconds to wait before a one-shot task fires. Must be positive. Mutually exclusive with cron_expression.",
            "description_zh": "一次性任务触发前的等待秒数，必须为正数。与 cron_expression 互斥。",
            "nullable": True,
        },
        "task_uuid": {
            "type": "string",
            "description": "Task uuid returned by list. Used in cancel; task_name also accepted.",
            "description_zh": "list 返回的任务 uuid。取消时使用，也可用 task_name。",
            "nullable": True,
        },
    }
    output_type = "string"

    # These attributes are injected via metadata at runtime
    db_create: Callable = None
    db_list: Callable = None
    db_cancel: Callable = None
    agent_id: int = None
    tenant_id: str = None
    user_id: str = None
    conversation_id: int = None

    def forward(
        self,
        action: str,
        task_name: Optional[str] = None,
        task_prompt: Optional[str] = None,
        task_type: Optional[str] = "oneshot",
        cron_expression: Optional[str] = None,
        delay_seconds: Optional[int] = None,
        task_uuid: Optional[str] = None,
    ) -> str:
        if action == "create":
            return self._handle_create(task_name, task_prompt, task_type, cron_expression, delay_seconds)
        elif action == "list":
            return self._handle_list()
        elif action == "cancel":
            # Accept either task_uuid or task_name — callers sometimes pass the
            # task id via task_name. If a name (not a uuid) is given, look it up.
            return self._handle_cancel(task_uuid or task_name)
        else:
            return f"Unknown action '{action}'. Use 'create', 'list', or 'cancel'."

    def _handle_create(self, task_name, task_prompt, task_type, cron_expression, delay_seconds):
        if not task_prompt:
            return "Error: task_prompt is required for creating a task."

        # Infer the task type from which time field was provided, so callers
        # don't need to set task_type explicitly (and can't accidentally leave
        # it as the default 'oneshot' while passing cron_expression).
        task_type = self._resolve_task_type(task_type, cron_expression, delay_seconds)
        if isinstance(task_type, str) and task_type.startswith("Error:"):
            return task_type

        # Compute next_fire_time
        now = datetime.now(timezone.utc)
        if task_type == "cron":
            cron_parts = self._parse_cron(cron_expression)
            if cron_parts is None:
                return f"Error: invalid cron expression '{cron_expression}'."
            next_fire = self._compute_next_fire(cron_parts, now)
        else:
            # oneshot — delay_seconds is guaranteed present by _resolve_task_type
            next_fire = now + timedelta(seconds=delay_seconds)

        data = {
            "task_uuid": str(uuid.uuid4()),
            "task_name": task_name or "",
            "task_prompt": task_prompt,
            "task_type": task_type,
            "cron_expression": cron_expression,
            "delay_seconds": delay_seconds,
            "status": "pending",
            "next_fire_time": next_fire.replace(tzinfo=None),
            "fire_count": 0,
            "agent_id": self.agent_id,
            "conversation_id": self.conversation_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "delete_flag": "N",
        }

        try:
            record = self.db_create(data)
            return f"Scheduled task created successfully. task_uuid={record.get('task_uuid')}, next_fire_time={next_fire.isoformat()}"
        except Exception as e:
            logger.error(f"Failed to create scheduled task: {e}")
            return f"Error creating scheduled task: {e}"

    @staticmethod
    def _resolve_task_type(task_type, cron_expression, delay_seconds):
        """Resolve the effective task type from the provided fields.

        Time fields are the source of truth: passing ``cron_expression`` means
        a recurring task, passing ``delay_seconds`` means a one-shot task. The
        optional ``task_type`` is honoured when consistent, and otherwise
        inferred. Returns the resolved type string, or an ``"Error: ..."``
        string when the inputs are missing or contradictory.
        """
        has_cron = bool(cron_expression)
        has_delay = delay_seconds is not None and delay_seconds > 0

        if has_cron and has_delay:
            return (
                "Error: cron_expression and delay_seconds are mutually "
                "exclusive — provide exactly one of them."
            )
        if not has_cron and not has_delay:
            return (
                "Error: provide either cron_expression (recurring) or "
                "delay_seconds (one-shot) to schedule a task."
            )

        # Infer from whichever field was provided; this lets callers skip the
        # task_type argument entirely.
        inferred = "cron" if has_cron else "oneshot"
        if task_type and task_type not in ("cron", "oneshot"):
            return f"Error: invalid task_type '{task_type}'. Use 'cron' or 'oneshot'."
        # If task_type was explicitly given and contradicts the fields, prefer
        # the fields (source of truth) but they can never actually disagree
        # here because has_cron/has_delay already exclude each other.
        return inferred

    def _handle_list(self):
        tasks = self._safe_call("list", lambda: self.db_list(self.agent_id, self.tenant_id, self.user_id))
        if isinstance(tasks, str):  # error message
            return tasks
        if not tasks:
            return "No scheduled tasks found."
        lines = [
            f"- [{t.get('status', 'unknown')}] {t.get('task_name', 'unnamed')} "
            f"({t.get('task_type', '?')}) uuid={t.get('task_uuid')}, next_fire={t.get('next_fire_time', '?')}"
            for t in tasks
        ]
        return "Scheduled tasks:\n" + "\n".join(lines)

    def _handle_cancel(self, task_identifier):
        """Cancel a task by uuid or by name.

        ``task_identifier`` may be a task uuid (preferred) or a task name. When
        it does not match any task uuid directly, we look it up among the
        caller's tasks by name, so callers that pass the name still succeed.
        """
        if not task_identifier:
            return "Error: task_uuid or task_name is required for cancelling a task."

        # First try cancelling directly by uuid.
        ok = self._safe_call(
            "cancel", lambda: self.db_cancel(task_identifier, self.agent_id, self.tenant_id, self.user_id)
        )
        if isinstance(ok, str):  # error message from _safe_call
            return ok
        if ok:
            return f"Task {task_identifier} cancelled successfully."

        # Direct uuid cancel matched nothing — try resolving the identifier as
        # a task name to its uuid, then cancel that.
        tasks = self._safe_call("list", lambda: self.db_list(self.agent_id, self.tenant_id, self.user_id))
        if isinstance(tasks, str):
            return tasks
        matched = [t for t in tasks if t.get("task_name") == task_identifier]
        if not matched:
            return f"Task '{task_identifier}' not found or already cancelled."
        cancelled = []
        for t in matched:
            uuid = t.get("task_uuid")
            res = self._safe_call(
                "cancel", lambda u=uuid: self.db_cancel(u, self.agent_id, self.tenant_id, self.user_id)
            )
            if not isinstance(res, str) and res:
                cancelled.append(uuid)
        if cancelled:
            return f"Task '{task_identifier}' cancelled successfully (uuid={cancelled[0]})."
        return f"Task '{task_identifier}' not found or already cancelled."

    def _safe_call(self, action: str, fn: Callable) -> Any:
        """Execute a DB call with unified error handling."""
        try:
            return fn()
        except Exception as e:
            logger.error(f"Failed to {action} scheduled task(s): {e}")
            return f"Error {action} scheduled task(s): {e}"

    @staticmethod
    def _parse_cron(expression: str):
        """Parse a 5-field cron expression into field sets.

        Supports standard cron syntax: '*', exact values ('9'), ranges
        ('1-5'), step values ('*/15' or '1-30/2'), and comma-separated
        lists ('1,3,5').

        Returns dict mapping each field name to a frozenset of allowed
        integer values, plus boolean ``day_of_month_restricted`` /
        ``day_of_week_restricted`` flags used for OR-semantics between the
        two day fields. Returns None if the expression is invalid.
        """
        parts = expression.strip().split()
        if len(parts) != 5:
            return None

        # (field_name, raw_field, lo, hi) for each of the 5 cron fields
        field_bounds = [
            ("minute", parts[0], 0, 59),
            ("hour", parts[1], 0, 23),
            ("day_of_month", parts[2], 1, 31),
            ("month", parts[3], 1, 12),
            ("day_of_week", parts[4], 0, 7),  # 0 and 7 both mean Sunday
        ]
        result = {}
        for name, field, lo, hi in field_bounds:
            try:
                result[name] = _expand_cron_field(field, lo, hi)
            except ValueError:
                return None

        # Standard cron: when BOTH day-of-month and day-of-week are
        # restricted (non-'*'), they combine with OR semantics. A field is
        # "restricted" when it was not a bare '*'.
        result["day_of_month_restricted"] = parts[2].strip() != "*"
        result["day_of_week_restricted"] = parts[4].strip() != "*"
        return result

    @staticmethod
    def _compute_next_fire(cron_parts: dict, from_timestamp: datetime) -> datetime:
        """Compute the next fire time via direct datetime arithmetic.

        Walks field-by-field (month -> day -> hour -> minute) advancing the
        candidate timestamp to the next matching value, instead of iterating
        minute-by-minute. Caps the search at 366 days to guarantee
        termination for impossible expressions.

        Day-of-month and day-of-week follow standard cron OR semantics: when
        both fields are restricted, a day matches if it satisfies either
        field; when only one is restricted, that field must match (the
        unrestricted '*' field always matches).
        """
        allowed_month = cron_parts["month"]
        allowed_dom = cron_parts["day_of_month"]
        allowed_dow = cron_parts["day_of_week"]
        allowed_hour = cron_parts["hour"]
        allowed_minute = cron_parts["minute"]
        dom_restricted = cron_parts.get("day_of_month_restricted", True)
        dow_restricted = cron_parts.get("day_of_week_restricted", True)

        # Python's weekday(): Monday=0 .. Sunday=6. Cron's day_of_week:
        # Sunday=0(==7), Monday=1 .. Saturday=6.
        def cron_dow(dt: datetime) -> int:
            return (dt.weekday() + 1) % 7

        def day_matches(dt: datetime) -> bool:
            dom_ok = (dt.day in allowed_dom) if dom_restricted else True
            dow_ok = (cron_dow(dt) in allowed_dow) if dow_restricted else True
            if dom_restricted and dow_restricted:
                return dom_ok or dow_ok  # OR semantics
            return dom_ok and dow_ok

        # Start from the next minute after from_timestamp
        candidate = from_timestamp.replace(second=0, microsecond=0) + timedelta(minutes=1)
        deadline = from_timestamp + timedelta(days=366)

        while candidate <= deadline:
            if candidate.month not in allowed_month:
                # Advance to the first day of the next allowed month
                next_month = candidate.month % 12 + 1
                next_year = candidate.year + (1 if candidate.month == 12 else 0)
                candidate = candidate.replace(year=next_year, month=next_month, day=1, hour=0, minute=0)
                continue

            if not day_matches(candidate):
                # Advance to the next day at 00:00
                candidate = (candidate + timedelta(days=1)).replace(hour=0, minute=0)
                continue

            if candidate.hour not in allowed_hour:
                # Advance to the next hour (or next day if past 23)
                if candidate.hour >= 23:
                    candidate = (candidate + timedelta(days=1)).replace(hour=0, minute=0)
                else:
                    candidate = candidate + timedelta(hours=1)
                    candidate = candidate.replace(minute=0)
                continue

            if candidate.minute not in allowed_minute:
                # Advance to the next minute (or next hour if past 59)
                if candidate.minute >= 59:
                    candidate = candidate + timedelta(hours=1)
                    candidate = candidate.replace(minute=0)
                else:
                    candidate = candidate + timedelta(minutes=1)
                continue

            return candidate

        # Fallback for expressions that never match within a year
        return from_timestamp + timedelta(hours=1)


def _expand_cron_field(field: str, lo: int, hi: int) -> frozenset:
    """Expand a single cron field expression into a frozenset of integers.

    Supports '*', exact values, comma-separated lists, ranges ('1-5'),
    and step values ('*/15', '1-30/2').
    """
    values = set()
    for item in field.split(","):
        item = item.strip()
        if "/" in item:
            base, step_str = item.split("/", 1)
            step = int(step_str)
            if step <= 0:
                raise ValueError(f"Invalid step value: {step}")
        else:
            base, step = item, 1

        if base == "*":
            start, end = lo, hi
        elif "-" in base:
            start_s, end_s = base.split("-", 1)
            start, end = int(start_s), int(end_s)
        else:
            start = end = int(base)

        if start < lo or end > hi or start > end:
            raise ValueError(f"Field '{field}' out of range [{lo}, {hi}]")

        values.update(range(start, end + 1, step))

    # Normalize Sunday: 7 -> 0
    if hi == 7 and 7 in values:
        values.discard(7)
        values.add(0)
    return frozenset(values)
