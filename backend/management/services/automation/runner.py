# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import asyncio
import logging
from datetime import datetime, timezone
from functools import partial
from typing import Any, Dict, Optional

from contracts.constants.environment import AGENT_AUTOMATION_DEFAULT_TIMEOUT_SECONDS
from contracts.agent import AgentRequest
from management.db.automation import repository as agent_automation_db
from management.services.agent.service import is_agent_running, run_agent_background, stop_agent_tasks
from management.services.agent.background import BackgroundExecutionState

from management.services.automation.capabilities import validate_bindings_available
from management.services.automation.conversation import automation_conversation_adapter
from contracts.automation import AutomationRunStatus, ScheduleTrigger



logger = logging.getLogger("agent_automation.runner")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _utcnow()


class AgentAutomationRunner:
    async def execute_task(
        self,
        task: Dict[str, Any],
        trigger_type: str = "SCHEDULED",
        scheduled_fire_at: Optional[datetime] = None,
        lease_owner: Optional[str] = None,
    ) -> Dict[str, Any]:
        scheduled = scheduled_fire_at or _parse_dt(task.get("next_fire_at"))
        busy = agent_automation_db.has_active_run_for_conversation(task["conversation_id"]) or is_agent_running(
            task["conversation_id"], task["user_id"],
        )
        values = {
            "task_id": task["task_id"], "tenant_id": task["tenant_id"],
            "user_id": task["user_id"], "conversation_id": task["conversation_id"],
            "scheduled_fire_at": scheduled, "actual_fire_at": _utcnow(),
            "trigger_type": trigger_type, "status": AutomationRunStatus.RUNNING.value,
            "started_at": _utcnow(),
        }
        if trigger_type == "SCHEDULED" and lease_owner:
            with agent_automation_db.task_run_transaction(
                task["task_id"], task["tenant_id"], task["user_id"],
            ) as (session, current, _):
                if not self._owns_occurrence(current, scheduled, lease_owner):
                    return {}
                task = current
                run = agent_automation_db.create_run(values, task["user_id"], db_session=session)
        else:
            run = agent_automation_db.create_run(values, task["user_id"])
        if lease_owner:
            run["_lease_owner"] = lease_owner
        if busy:
            return self._finish_run(run, task, AutomationRunStatus.SKIPPED.value, {
                "error_code": "AUTOMATION_RUN_ALREADY_ACTIVE",
                "error_message": "Conversation already has an active automation run.",
            })

        timeout_seconds = float(task.get("timeout_seconds") or AGENT_AUTOMATION_DEFAULT_TIMEOUT_SECONDS)
        try:
            return await asyncio.wait_for(
                self._execute_active_run(run, task, scheduled, trigger_type),
                timeout=max(1, timeout_seconds),
            )
        except asyncio.TimeoutError:
            self.cancel_for_conversation(task["conversation_id"], task["user_id"], run["run_id"])
            return self._finish_run(run, task, AutomationRunStatus.TIMEOUT.value, {
                "error_code": "AUTOMATION_RUN_TIMEOUT",
                "error_message": f"Automation run exceeded {timeout_seconds} seconds.",
            })
        except asyncio.CancelledError:
            current = agent_automation_db.get_run(run["run_id"], task["tenant_id"], task["user_id"])
            caller = asyncio.current_task()
            # Only a durable user cancellation may become a normal domain result.
            # Shutdown, lease loss and cancellation of the caller still propagate.
            if (current and current.get("status") == "CANCELED"
                    and current.get("error_code") == "AUTOMATION_RUN_CANCELED"
                    and (caller is None or not caller.cancelling())):
                return current
            self.cancel_for_conversation(task["conversation_id"], task["user_id"], run["run_id"])
            self._finish_run(run, task, AutomationRunStatus.CANCELED.value, {
                "error_code": "AUTOMATION_EXECUTION_INTERRUPTED",
                "error_message": "Scheduler execution was interrupted before completion.",
            })
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
        turn = automation_conversation_adapter.append_run_prompt(
            task["conversation_id"],
            generated_prompt,
            task["user_id"],
            task["tenant_id"],
            run_id=run["run_id"],
        )

        agent_request = AgentRequest(
            query=generated_prompt,
            conversation_id=task["conversation_id"],
            history=turn["history"],
            agent_id=task["agent_id"],
            model_id=runtime_snapshot.get("model_id"),
            version_no=task.get("agent_version_no"),
            tool_params=runtime_snapshot.get("tool_params"),
            enable_automation_tool=False,
        )
        result = await run_agent_background(
            agent_request=agent_request,
            user_id=task["user_id"],
            tenant_id=task["tenant_id"],
            skip_user_save=True,
            execution_state=BackgroundExecutionState(
                runtime_generation=str(run["run_id"]),
                is_active=partial(self._run_is_active, run, task),
                create_assistant=partial(
                automation_conversation_adapter.append_run_assistant,
                run_id=run["run_id"], user_id=task["user_id"], tenant_id=task["tenant_id"],
            )),
        )
        if (result.get("status") == "completed" and result.get("persisted")
                and result.get("assistant_message_id") is not None):
            return self._finish_run(run, task, AutomationRunStatus.SUCCEEDED.value, {})
        return self._fail_run(
            run, task, result.get("error_code") or "AUTOMATION_EXECUTION_FAILED",
            result.get("error_message") or "Agent execution did not complete successfully.",
        )

    @staticmethod
    def _run_is_active(run, task):
        current = agent_automation_db.get_run(run["run_id"], task["tenant_id"], task["user_id"])
        return bool(current and current["status"] == "RUNNING")

    def cancel_for_conversation(self, conversation_id: int, user_id: str, run_id=None) -> None:
        if run_id is None:
            stop_agent_tasks(conversation_id, user_id)
        else:
            stop_agent_tasks(conversation_id, user_id, expected_generation=str(run_id))

    def cancel_run_by_user(self, run, task):
        transitioned = []
        result = self._finish_run(run, task, "CANCELED", {
            "error_code": "AUTOMATION_RUN_CANCELED",
            "error_message": "Automation run was canceled by user.",
        }, user_cancel=True, transitioned=transitioned)
        return result, bool(transitioned)

    @staticmethod
    def _owns_occurrence(task, scheduled, lease_owner, require_active=True):
        return bool(task and (not require_active or task.get("status") == "ACTIVE")
                    and task.get("next_fire_at") is not None
                    and _parse_dt(task["next_fire_at"]) == _parse_dt(scheduled)
                    and task.get("lock_owner") == lease_owner
                    and task.get("lock_until") is not None
                    and _parse_dt(task["lock_until"]) > _utcnow())

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
        user_cancel: bool = False,
        transitioned=None,
    ) -> Dict[str, Any]:
        with agent_automation_db.task_run_transaction(
            task["task_id"], task["tenant_id"], task["user_id"], run["run_id"],
        ) as (session, current_task, current_run):
            if not current_task or not current_run:
                return run
            if current_run["status"] not in {"QUEUED", "RUNNING"}:
                return current_run
            scheduled = current_run.get("trigger_type") == "SCHEDULED"
            owner = run.get("_lease_owner")
            owns_lease = not owner or self._owns_occurrence(
                current_task, current_run["scheduled_fire_at"], owner, require_active=False,
            )
            now = _utcnow()
            updated = agent_automation_db.update_run(run["run_id"], {
                **extra, "status": status, "finished_at": now,
                "duration_ms": max(0, int((now - _parse_dt(current_run.get("started_at"))).total_seconds() * 1000)),
            }, task["user_id"], expected_statuses=["QUEUED", "RUNNING"], db_session=session)
            if not updated:
                return current_run
            if scheduled and not owns_lease and not user_cancel:
                # Losing a lease cannot rewrite a reclaimed or edited task.
                return updated
            values = {"last_fire_at": now, "last_run_status": status,
                      "last_error": extra.get("error_message")}
            # An edited/reclaimed schedule must not be advanced by an old run.
            same_occurrence = (current_task.get("next_fire_at") is not None and
                               _parse_dt(current_task["next_fire_at"]) == _parse_dt(current_run["scheduled_fire_at"]))
            if scheduled and same_occurrence:
                count, next_fire, task_status = self._advance_scheduled_task(current_task, now)
                failures = int(current_task.get("consecutive_failures") or 0)
                if status == "SUCCEEDED":
                    failures = 0
                elif status in {"FAILED", "TIMEOUT"}:
                    failures += 1
                    if failures >= 5 and next_fire is not None:
                        task_status = "PAUSED_BY_SYSTEM"
                if current_task.get("status") in {"PAUSED", "PAUSED_BY_SYSTEM"}:
                    task_status = current_task["status"]
                values.update(status=task_status, fire_count=count, next_fire_at=next_fire,
                              consecutive_failures=failures, lock_owner=None, lock_until=None)
            agent_automation_db.update_task(task["task_id"], task["tenant_id"], task["user_id"],
                                            values, db_session=session)
            if transitioned is not None:
                transitioned.append(True)
            return updated

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
        from management.services.automation.scheduler import compute_next_fire_at

        next_fire_at = compute_next_fire_at(trigger, after, fire_count)
        task_status = task.get("status", "ACTIVE")
        if next_fire_at is None:
            task_status = "COMPLETED"
        return fire_count, next_fire_at, task_status


agent_automation_runner = AgentAutomationRunner()
