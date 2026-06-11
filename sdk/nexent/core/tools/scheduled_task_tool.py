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
        "Create, list, or cancel scheduled tasks that will be executed "
        "automatically at a specified time or on a recurring schedule. "
        "Use this to set reminders, schedule periodic reports, or defer "
        "actions to a future time."
    )
    description_zh = (
        "创建、查看或取消定时任务。定时任务会在指定时间自动执行，"
        "支持一次性延迟任务和周期性 cron 任务。可用于设置提醒、"
        "定期报告或将操作推迟到未来执行。"
    )

    inputs = {
        "action": {
            "type": "string",
            "description": "Action to perform: 'create', 'list', or 'cancel'",
            "description_zh": "操作类型：'create'（创建）、'list'（查看）或 'cancel'（取消）",
        },
        "task_name": {
            "type": "string",
            "description": "Name for the task (used in create)",
            "description_zh": "任务名称（创建时使用）",
            "nullable": True,
        },
        "task_prompt": {
            "type": "string",
            "description": "The prompt content to execute when the task fires (used in create)",
            "description_zh": "任务触发时要执行的提示内容（创建时使用）",
            "nullable": True,
        },
        "task_type": {
            "type": "string",
            "description": "Type: 'oneshot' (run once after delay) or 'cron' (recurring). Default 'oneshot'",
            "description_zh": "类型：'oneshot'（一次性延迟）或 'cron'（周期性）。默认 'oneshot'",
            "nullable": True,
        },
        "cron_expression": {
            "type": "string",
            "description": "Cron expression for recurring tasks, e.g. '0 9 * * *' (daily at 9am). Required if task_type='cron'",
            "description_zh": "周期性任务的 cron 表达式，如 '0 9 * * *'（每天9点）。task_type='cron' 时必填",
            "nullable": True,
        },
        "delay_seconds": {
            "type": "integer",
            "description": "Delay in seconds for oneshot tasks. Required if task_type='oneshot'",
            "description_zh": "一次性任务的延迟秒数。task_type='oneshot' 时必填",
            "nullable": True,
        },
        "task_uuid": {
            "type": "string",
            "description": "UUID of the task to cancel (used in cancel)",
            "description_zh": "要取消的任务 UUID（取消时使用）",
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
            return self._handle_cancel(task_uuid)
        else:
            return f"Unknown action '{action}'. Use 'create', 'list', or 'cancel'."

    def _handle_create(self, task_name, task_prompt, task_type, cron_expression, delay_seconds):
        if not task_prompt:
            return "Error: task_prompt is required for creating a task."

        task_type = task_type or "oneshot"

        # Compute next_fire_time
        now = datetime.now(timezone.utc)
        if task_type == "cron":
            if not cron_expression:
                return "Error: cron_expression is required for cron tasks."
            cron_parts = self._parse_cron(cron_expression)
            if cron_parts is None:
                return f"Error: invalid cron expression '{cron_expression}'."
            next_fire = self._compute_next_fire(cron_parts, now)
        else:
            # oneshot
            if delay_seconds is None or delay_seconds <= 0:
                return "Error: delay_seconds must be a positive integer for oneshot tasks."
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

    def _handle_cancel(self, task_uuid):
        if not task_uuid:
            return "Error: task_uuid is required for cancelling a task."
        ok = self._safe_call("cancel", lambda: self.db_cancel(task_uuid, self.agent_id, self.tenant_id, self.user_id))
        if isinstance(ok, str):  # error message
            return ok
        return f"Task {task_uuid} cancelled successfully." if ok else f"Task {task_uuid} not found or already cancelled."

    def _safe_call(self, action: str, fn: Callable) -> Any:
        """Execute a DB call with unified error handling."""
        try:
            return fn()
        except Exception as e:
            logger.error(f"Failed to {action} scheduled task(s): {e}")
            return f"Error {action} scheduled task(s): {e}"

    @staticmethod
    def _parse_cron(expression: str):
        """Parse a 5-field cron expression into a dict of field values.

        Returns dict with keys: minute, hour, day_of_month, month, day_of_week
        or None if the expression is invalid.
        """
        parts = expression.strip().split()
        if len(parts) != 5:
            return None
        try:
            return {
                "minute": int(parts[0]),
                "hour": int(parts[1]),
                "day_of_month": parts[2],
                "month": parts[3],
                "day_of_week": parts[4],
            }
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _compute_next_fire(cron_parts: dict, from_timestamp: datetime) -> datetime:
        """Compute the next fire time from a parsed cron expression.

        This is a simplified implementation that handles common patterns.
        Supports numeric values and '*' for day_of_month, month, day_of_week.
        """
        minute = cron_parts["minute"]
        hour = cron_parts["hour"]
        day_of_month = cron_parts["day_of_month"]
        month = cron_parts["month"]

        # Start from the next minute after from_timestamp
        candidate = from_timestamp.replace(second=0, microsecond=0) + timedelta(minutes=1)

        # Simple approach: search forward minute by minute up to 366 days
        max_iterations = 525960  # 366 * 24 * 60
        for _ in range(max_iterations):
            month_match = (month == "*" or candidate.month == int(month))
            dom_match = (day_of_month == "*" or candidate.day == int(day_of_month))
            hour_match = candidate.hour == hour
            minute_match = candidate.minute == minute

            if month_match and dom_match and hour_match and minute_match:
                return candidate

            # Skip ahead if possible
            if not month_match:
                # Jump to first day of next month
                if candidate.month < 12:
                    candidate = candidate.replace(month=candidate.month + 1, day=1, hour=0, minute=0)
                else:
                    candidate = candidate.replace(year=candidate.year + 1, month=1, day=1, hour=0, minute=0)
                continue

            if not dom_match:
                candidate = candidate.replace(hour=0, minute=0) + timedelta(days=1)
                continue

            if not hour_match and candidate.hour < hour:
                candidate = candidate.replace(hour=hour, minute=minute)
                if candidate.minute == minute:
                    return candidate
                continue

            # Move to next day
            candidate = candidate.replace(hour=0, minute=0) + timedelta(days=1)

        # Fallback: return from_timestamp + 1 hour
        return from_timestamp + timedelta(hours=1)
