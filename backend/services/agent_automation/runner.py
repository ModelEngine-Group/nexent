import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from consts.const import AGENT_AUTOMATION_DEFAULT_TIMEOUT_SECONDS
from consts.model import AgentRequest, HistoryItem, MessageRequest, MessageUnit
from database import agent_automation_db
from services.agent_service import is_agent_running, run_agent_background, stop_agent_tasks
from services.conversation_management_service import (
    get_conversation_history_service,
    save_message,
    save_message_unit,
)

from .capability_resolver import validate_bindings_available
from .models import AutomationRunStatus, ScheduleTrigger
from .schedule_engine import compute_next_fire_at


logger = logging.getLogger("agent_automation.runner")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _utcnow()


def _message_content(message: Dict[str, Any]) -> str:
    content = message.get("message", "")
    if isinstance(content, list):
        final = next((unit.get("content") for unit in reversed(content) if unit.get("type") == "final_answer"), "")
        visible_units = [
            unit
            for unit in content
            if unit.get("type") not in {"automation_proposal"}
        ]
        content = final or " ".join(str(unit.get("content", "")) for unit in visible_units)
    return str(content or "")


def _history_items(history_payload: List[Dict[str, Any]]) -> List[HistoryItem]:
    if not history_payload:
        return []
    items: List[HistoryItem] = []
    for msg in history_payload[0].get("message", []):
        content = _message_content(msg)
        if content:
            items.append(HistoryItem(role=msg.get("role", "user"), content=content))
    return items


class AgentAutomationRunner:
    async def execute_task(
        self,
        task: Dict[str, Any],
        trigger_type: str = "SCHEDULED",
        scheduled_fire_at: Optional[datetime] = None,
        lease_owner: Optional[str] = None,
    ) -> Dict[str, Any]:
        scheduled = scheduled_fire_at or _parse_dt(task.get("next_fire_at"))
        if agent_automation_db.has_active_run_for_conversation(task["conversation_id"]) or is_agent_running(
            task["conversation_id"],
            task["user_id"],
        ):
            skipped_at = _utcnow()
            run = agent_automation_db.create_run({
                "task_id": task["task_id"],
                "tenant_id": task["tenant_id"],
                "user_id": task["user_id"],
                "conversation_id": task["conversation_id"],
                "scheduled_fire_at": scheduled,
                "actual_fire_at": skipped_at,
                "trigger_type": trigger_type,
                "status": AutomationRunStatus.SKIPPED.value,
                "started_at": skipped_at,
                "finished_at": skipped_at,
                "error_code": "AUTOMATION_RUN_ALREADY_ACTIVE",
                "error_message": "Conversation already has an active automation run.",
            }, task["user_id"])
            fire_count, next_fire_at, task_status = self._advance_scheduled_task(task, skipped_at)
            task_values = {
                "status": task_status,
                "last_fire_at": skipped_at,
                "last_run_status": AutomationRunStatus.SKIPPED.value,
                "last_error": "Conversation already has an active automation run.",
                "fire_count": fire_count,
                "next_fire_at": next_fire_at,
                "lock_owner": None,
                "lock_until": None,
            }
            self._update_task_state(task, task_values, trigger_type, lease_owner)
            return run

        run = agent_automation_db.create_run({
            "task_id": task["task_id"],
            "tenant_id": task["tenant_id"],
            "user_id": task["user_id"],
            "conversation_id": task["conversation_id"],
            "scheduled_fire_at": scheduled,
            "actual_fire_at": _utcnow(),
            "trigger_type": trigger_type,
            "status": AutomationRunStatus.RUNNING.value,
            "started_at": _utcnow(),
        }, task["user_id"])
        if lease_owner:
            run["_lease_owner"] = lease_owner

        timeout_seconds = float(task.get("timeout_seconds") or AGENT_AUTOMATION_DEFAULT_TIMEOUT_SECONDS)
        try:
            return await asyncio.wait_for(
                self._execute_active_run(run, task, scheduled, trigger_type),
                timeout=max(1, timeout_seconds),
            )
        except asyncio.TimeoutError:
            self.cancel_for_conversation(task["conversation_id"], task["user_id"])
            return self._finish_run(run, task, AutomationRunStatus.TIMEOUT.value, {
                "error_code": "AUTOMATION_RUN_TIMEOUT",
                "error_message": f"Automation run exceeded {timeout_seconds} seconds.",
            })
        except asyncio.CancelledError:
            self.cancel_for_conversation(task["conversation_id"], task["user_id"])
            agent_automation_db.cancel_run(
                run["run_id"],
                task["tenant_id"],
                task["user_id"],
                "Scheduler execution was interrupted before completion.",
            )
            raise
        except Exception as exc:
            return self._fail_run(run, task, "AUTOMATION_RUN_FAILED", str(exc))

    async def _execute_active_run(
        self,
        run: Dict[str, Any],
        task: Dict[str, Any],
        scheduled: datetime,
        trigger_type: str,
    ) -> Dict[str, Any]:
        capability_status = await validate_bindings_available(
            agent_id=task["agent_id"],
            tenant_id=task["tenant_id"],
            user_id=task["user_id"],
            instruction=task["instruction"],
            bindings=task.get("capability_bindings") or [],
            version_no=task.get("agent_version_no") or 0,
        )
        if not capability_status["available"]:
            return self._fail_run(
                run,
                task,
                "AUTOMATION_CAPABILITY_UNAVAILABLE",
                "Required automation capability is unavailable.",
            )

        history_payload = get_conversation_history_service(task["conversation_id"], task["user_id"])
        history = _history_items(history_payload)
        stored_snapshot = task.get("runtime_snapshot") or {"agent_id": task["agent_id"]}
        current_resolution = capability_status.get("resolution") or {}
        current_agent_snapshot = current_resolution.get("agent_snapshot") or {}
        runtime_snapshot = {
            **stored_snapshot,
            **current_agent_snapshot,
            # Runtime selections belong to the task even when the Agent metadata changes.
            "model_id": stored_snapshot.get("model_id"),
            "tool_params": stored_snapshot.get("tool_params"),
            "original_instruction": (
                stored_snapshot.get("original_instruction") or task["instruction"]
            ),
        }
        generated_prompt = task["instruction"].strip()
        message_request = MessageRequest(
            conversation_id=task["conversation_id"],
            message_idx=len(history_payload[0].get("message", [])) if history_payload else 0,
            role="user",
            message=[MessageUnit(type="string", content=generated_prompt)],
        )
        user_message_id = save_message(message_request, task["user_id"], task["tenant_id"])
        save_message_unit(
            message_id=user_message_id,
            conversation_id=task["conversation_id"],
            unit_index=0,
            unit_type="automation_prompt",
            unit_content=generated_prompt,
            user_id=task["user_id"],
        )

        agent_request = AgentRequest(
            query=generated_prompt,
            conversation_id=task["conversation_id"],
            history=history,
            agent_id=task["agent_id"],
            model_id=runtime_snapshot.get("model_id"),
            version_no=task.get("agent_version_no"),
            tool_params=runtime_snapshot.get("tool_params"),
        )
        result = await run_agent_background(
            agent_request=agent_request,
            user_id=task["user_id"],
            tenant_id=task["tenant_id"],
            skip_user_save=True,
        )
        return self._finish_run(run, task, AutomationRunStatus.SUCCEEDED.value, {
            "generated_prompt": generated_prompt,
            "user_message_id": user_message_id,
            "assistant_message_id": result.get("assistant_message_id"),
        })

    def cancel_for_conversation(self, conversation_id: int, user_id: str) -> None:
        stop_agent_tasks(conversation_id, user_id)

    def _fail_run(
        self,
        run: Dict[str, Any],
        task: Dict[str, Any],
        error_code: str,
        error_message: str,
    ) -> Dict[str, Any]:
        return self._finish_run(run, task, AutomationRunStatus.FAILED.value, {
            "error_code": error_code,
            "error_message": error_message,
        })

    def _finish_run(
        self,
        run: Dict[str, Any],
        task: Dict[str, Any],
        status: str,
        extra: Dict[str, Any],
    ) -> Dict[str, Any]:
        now = _utcnow()
        started_at = _parse_dt(run.get("started_at"))
        duration_ms = int((now - started_at).total_seconds() * 1000)
        updated_run = agent_automation_db.update_run(run["run_id"], {
            **extra,
            "status": status,
            "finished_at": now,
            "duration_ms": duration_ms,
        }, task["user_id"], expected_statuses=[AutomationRunStatus.RUNNING.value])
        if not updated_run:
            current_run = agent_automation_db.get_run(
                run["run_id"],
                task["tenant_id"],
                task["user_id"],
            )
            return current_run or run

        fire_count = int(task.get("fire_count") or 0)
        next_fire_at = task.get("next_fire_at")
        task_status = task.get("status", "ACTIVE")
        consecutive_failures = int(task.get("consecutive_failures") or 0)
        is_scheduled_run = run.get("trigger_type") == "SCHEDULED"
        if is_scheduled_run:
            fire_count, next_fire_at, task_status = self._advance_scheduled_task(task, now)
            if status == AutomationRunStatus.SUCCEEDED.value:
                consecutive_failures = 0
            elif status in {AutomationRunStatus.FAILED.value, AutomationRunStatus.TIMEOUT.value}:
                consecutive_failures += 1
                if consecutive_failures >= 5 and next_fire_at is not None:
                    task_status = "PAUSED_BY_SYSTEM"

        current_task = agent_automation_db.get_task(
            task["task_id"],
            task["tenant_id"],
            task["user_id"],
        )
        if current_task and current_task.get("status") in {
            "PAUSED",
            "PAUSED_BY_SYSTEM",
        }:
            task_status = current_task["status"]

        task_values = {
            "status": task_status,
            "last_fire_at": now,
            "last_run_status": status,
            "last_error": extra.get("error_message"),
            "consecutive_failures": consecutive_failures,
            "fire_count": fire_count,
            "next_fire_at": next_fire_at,
            "lock_owner": None,
            "lock_until": None,
        }
        self._update_task_state(
            task,
            task_values,
            str(run.get("trigger_type") or "SCHEDULED"),
            run.get("_lease_owner"),
        )
        return updated_run or run

    @staticmethod
    def _update_task_state(
        task: Dict[str, Any],
        values: Dict[str, Any],
        trigger_type: str,
        lease_owner: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        if trigger_type == "SCHEDULED" and lease_owner:
            updated = agent_automation_db.update_task_if_lock_owner(
                task["task_id"],
                task["tenant_id"],
                task["user_id"],
                lease_owner,
                values,
            )
            if not updated:
                logger.warning(
                    "Discarded stale scheduled task update after lease loss: task_id=%s owner=%s",
                    task["task_id"],
                    lease_owner,
                )
            return updated
        return agent_automation_db.update_task(
            task["task_id"],
            task["tenant_id"],
            task["user_id"],
            values,
        )

    @staticmethod
    def _advance_scheduled_task(
        task: Dict[str, Any],
        after: datetime,
    ) -> tuple[int, Optional[datetime], str]:
        """Advance exactly one scheduled occurrence without consuming manual runs."""
        fire_count = int(task.get("fire_count") or 0) + 1
        trigger = ScheduleTrigger.model_validate(task["schedule_config"])
        next_fire_at = compute_next_fire_at(trigger, after, fire_count)
        task_status = task.get("status", "ACTIVE")
        if next_fire_at is None:
            task_status = "COMPLETED"
        return fire_count, next_fire_at, task_status


agent_automation_runner = AgentAutomationRunner()
