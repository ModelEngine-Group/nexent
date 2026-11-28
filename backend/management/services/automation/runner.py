# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import asyncio
import logging
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from contracts.agent import AgentRequest, WorkbenchSessionConfig
from contracts.agentos import AgentRunLookup, AgentRunReference, AgentStop
from contracts.automation import AutomationRunStatus, ScheduleTrigger
from contracts.constants.environment import AGENT_AUTOMATION_DEFAULT_TIMEOUT_SECONDS
from contracts.conversation import MessageSource
from contracts.errors.exceptions import (
    AgentRunAlreadyActiveError, RuntimeServiceTimeoutError, RuntimeServiceUnavailableError, RuntimeUpstreamError,
    RunModelControlsError, WorkbenchError,
)
from management.db.automation import repository as agent_automation_db
from management.db.conversation.repository import get_conversation, get_prepared_projection_receipt
from management.services.agent.preparation.evaluation_snapshot import prepare_conversation_snapshot
from management.services.agent.prepared_projection import ProjectedRun, acknowledge_projection, resume_assistant_projection
from management.services.agent.runtime_client import (
    _agentos_client, forward_active_run, forward_scoped_stop, forward_tracked_background,
)
from management.services.agent.workbench import prepare_portable_workbench
from management.services.automation.capabilities import validate_bindings_available
from management.services.automation.conversation import automation_conversation_adapter
from management.services.model.run_controls import validate_selected_model
from nexent.core.concurrency import run_blocking


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
    def __init__(self) -> None:
        self._local_runs: set[int] = set()

    async def execute_task(
        self,
        task: Dict[str, Any],
        trigger_type: str = "SCHEDULED",
        scheduled_fire_at: Optional[datetime] = None,
        lease_owner: Optional[str] = None,
    ) -> Dict[str, Any]:
        scheduled = scheduled_fire_at or _parse_dt(task.get("next_fire_at"))
        busy = agent_automation_db.has_active_run_for_conversation(
            task["conversation_id"], task["user_id"], task["tenant_id"],
        )
        inspection_error = None
        if not busy:
            try:
                busy = await forward_active_run(task["conversation_id"], task["user_id"], task["tenant_id"]) is not None
            except (RuntimeServiceTimeoutError, RuntimeServiceUnavailableError, RuntimeUpstreamError) as exc:
                inspection_error = exc
        values = {
            "task_id": task["task_id"], "tenant_id": task["tenant_id"],
            "user_id": task["user_id"], "conversation_id": task["conversation_id"],
            "scheduled_fire_at": scheduled, "actual_fire_at": _utcnow(),
            "trigger_type": trigger_type, "status": AutomationRunStatus.RUNNING.value,
            "started_at": _utcnow(), "runtime_run_id": uuid4().hex,
        }
        occurrence_started = False
        if trigger_type == "SCHEDULED" and lease_owner:
            with agent_automation_db.task_run_transaction(
                task["task_id"], task["tenant_id"], task["user_id"],
            ) as (session, current, _):
                if not self._owns_occurrence(session, current, scheduled, lease_owner):
                    return {}
                task = current
                if not busy:
                    occurrence_started = agent_automation_db.has_started_scheduled_occurrence(
                        session, task["task_id"], task["tenant_id"], task["user_id"], scheduled,
                    )
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
        if occurrence_started:
            return self._finish_run(run, task, AutomationRunStatus.SKIPPED.value, {
                "error_code": "AUTOMATION_OCCURRENCE_ALREADY_STARTED",
                "error_message": "This scheduled occurrence already started before its lease was lost.",
            })

        if inspection_error is not None:
            return self._fail_run(run, task, "AUTOMATION_RUN_FAILED", str(inspection_error))

        timeout_seconds = float(task.get("timeout_seconds") or AGENT_AUTOMATION_DEFAULT_TIMEOUT_SECONDS)
        self._local_runs.add(run["run_id"])
        try:
            return await asyncio.wait_for(
                self._execute_active_run(run, task),
                timeout=max(1, timeout_seconds),
            )
        except AgentRunAlreadyActiveError:
            return self._finish_run(run, task, AutomationRunStatus.SKIPPED.value, {
                "error_code": "AUTOMATION_RUN_ALREADY_ACTIVE",
                "error_message": "Conversation already has an active run.",
            })
        except asyncio.TimeoutError:
            await self.cancel_runtime_run(run.get("runtime_run_id"), task["conversation_id"], task["user_id"], task["tenant_id"])
            return self._finish_run(run, task, AutomationRunStatus.TIMEOUT.value, {
                "error_code": "AUTOMATION_RUN_TIMEOUT",
                "error_message": f"Automation run exceeded {timeout_seconds} seconds.",
            })
        except asyncio.CancelledError:
            if run.get("projection_message_index") is not None or run.get("_background_outcome_unknown"):
                raise
            current = agent_automation_db.get_run(run["run_id"], task["tenant_id"], task["user_id"])
            caller = asyncio.current_task()
            # Only a durable user cancellation may become a normal domain result.
            # Shutdown, lease loss and cancellation of the caller still propagate.
            if (current and current.get("status") == "CANCELED"
                    and current.get("error_code") == "AUTOMATION_RUN_CANCELED"
                    and (caller is None or not caller.cancelling())):
                return current
            await self.cancel_runtime_run(run.get("runtime_run_id"), task["conversation_id"], task["user_id"], task["tenant_id"])
            self._finish_run(run, task, AutomationRunStatus.CANCELED.value, {
                "error_code": "AUTOMATION_EXECUTION_INTERRUPTED",
                "error_message": "Scheduler execution was interrupted before completion.",
            })
            raise
        except Exception as exc:
            if run.get("projection_message_index") is not None or run.get("_background_outcome_unknown"):
                logger.warning("Deferred automation projection run_id=%s error=%s", run["run_id"], type(exc).__name__)
                return run
            if isinstance(exc, RunModelControlsError) and exc.code in {
                "model_not_available", "model_unavailable", "model_type_invalid",
            }:
                return self._fail_run(
                    run, task, "AUTOMATION_MODEL_UNAVAILABLE",
                    "No usable model is selected in the source conversation. Select a model and try again.",
                )
            return self._fail_run(run, task, "AUTOMATION_RUN_FAILED", str(exc))
        finally:
            self._local_runs.discard(run["run_id"])

    async def _execute_active_run(
        self,
        run: Dict[str, Any],
        task: Dict[str, Any],
    ) -> Dict[str, Any]:
        source_id = run.get("user_message_id")
        generated_prompt = run.get("generated_prompt") if source_id is not None else None
        if generated_prompt is None:
            generated_prompt = task["instruction"].strip()
        reference = AgentRunReference(run_id=run["runtime_run_id"], conversation_id=run["conversation_id"])
        conversation = await run_blocking(
            "automation-conversation", get_conversation, reference.conversation_id,
            user_id=run["user_id"], tenant_id=run["tenant_id"], lane="control-io", owner="management",
        )
        if conversation is None:
            return self._fail_run(run, task, "AUTOMATION_CONVERSATION_UNAVAILABLE",
                                  "The conversation bound to this task is unavailable.")
        model_id = conversation.get("selected_model_id")
        if model_id is None:
            raise RunModelControlsError("model_not_available")
        await run_blocking(
            "automation-model", validate_selected_model, model_id, run["tenant_id"],
            lane="control-io", owner="management",
        )
        capability_status = await validate_bindings_available(
            agent_id=task["agent_id"],
            tenant_id=task["tenant_id"],
            user_id=task["user_id"],
            instruction=generated_prompt if source_id is not None else task["instruction"],
            bindings=task.get("capability_bindings") or [],
            version_no=task.get("agent_version_no") or 0,
            model_id=model_id,
        )
        if not capability_status["available"]:
            return self._fail_run(
                run,
                task,
                "AUTOMATION_CAPABILITY_UNAVAILABLE",
                "Required automation capability is unavailable.",
            )

        stored_snapshot = task.get("runtime_snapshot") or {}
        if source_id is None:
            lease_owner = run.get("_lease_owner")
            turn = automation_conversation_adapter.append_run_prompt(
                task["conversation_id"], generated_prompt, task["user_id"], task["tenant_id"],
                run_id=run["run_id"], **({"lease_owner": lease_owner} if lease_owner is not None else {}),
            )
        else:
            turn = await run_blocking(
                "automation-preparation-source", automation_conversation_adapter.load_run_prompt,
                task["conversation_id"], source_id, generated_prompt, task["user_id"], task["tenant_id"],
                lane="control-io", owner="management",
            )
        message_index = turn["assistant_message_index"]
        saved = agent_automation_db.update_run(run["run_id"], {
            "generated_prompt": generated_prompt, "user_message_id": turn["user_message_id"],
        }, run["user_id"], expected_statuses=[AutomationRunStatus.RUNNING.value], tenant_id=run["tenant_id"])
        if saved is None:
            return agent_automation_db.get_run(run["run_id"], run["tenant_id"], run["user_id"]) or run
        run.update(saved)

        agent_request = AgentRequest(
            query=generated_prompt,
            conversation_id=task["conversation_id"],
            history=turn["history"],
            agent_id=task["agent_id"],
            model_id=model_id,
            version_no=task.get("agent_version_no"),
            tool_params=stored_snapshot.get("tool_params"),
            enable_automation_tool=False,
        )
        execution = agent_automation_db.workbench_execution_config(
            stored_snapshot, conversation.get("workbench_config"), conversation.get("workbench_config_version"),
        )
        workbench = None
        try:
            if execution is not None:
                version = execution["version"]
                if type(version) is not int or version < 1 or conversation.get("workbench_config") is None:
                    raise WorkbenchError("WORKBENCH_CONFIG_UNAVAILABLE")
                agent_request = agent_request.model_copy(update={
                    "entrypoint": "workbench",
                    "workbench": WorkbenchSessionConfig.model_validate(execution["config"]),
                    "expected_workbench_config_version": conversation["workbench_config_version"],
                })
                workbench = await run_blocking(
                    "automation-workbench", prepare_portable_workbench, agent_request, conversation,
                    run["user_id"], run["tenant_id"], lane="control-io", owner="management",
                )
                if workbench is None:
                    raise WorkbenchError("WORKBENCH_CONFIG_UNAVAILABLE")
                if workbench.knowledge is not None and any(
                    warning["code"] == "KNOWLEDGE_SCOPE_ITEM_UNAVAILABLE"
                    for warning in workbench.knowledge.warnings
                ):
                    raise WorkbenchError("WORKBENCH_KNOWLEDGE_UNAVAILABLE")
                # This run uses the task configuration without editing the chat settings.
                workbench = replace(workbench, version=version)
            snapshot = await prepare_conversation_snapshot(
                agent_request, reference, run["user_id"], run["tenant_id"],
                current_user_message_id=turn["user_message_id"], owned_conversation=conversation,
                workbench=workbench,
            )
        except WorkbenchError as exc:
            return self._fail_run(run, task, exc.code, f"Workbench execution setup failed: {exc.code}.")
        except ValidationError:
            if execution is None:
                raise
            return self._fail_run(run, task, "WORKBENCH_CONFIG_INVALID",
                                  "The configuration saved for this Workbench task is invalid.")
        if snapshot is None and execution is not None:
            return self._fail_run(run, task, "WORKBENCH_CONFIG_UNAVAILABLE",
                                  "The Workbench configuration could not be prepared for this run.")
        if snapshot is None:
            try:
                result = await forward_tracked_background(
                    agent_request=agent_request,
                    run_id=run["runtime_run_id"],
                    user_id=task["user_id"],
                    tenant_id=task["tenant_id"],
                )
            finally:
                try:
                    current = agent_automation_db.get_run(run["run_id"], run["tenant_id"], run["user_id"])
                    if current is not None:
                        run.update(current)
                except (SQLAlchemyError, RuntimeError):
                    run["_background_outcome_unknown"] = True
                    logger.warning("Background projection ownership refresh deferred run_id=%s", run["run_id"])
            if run.get("_background_outcome_unknown"):
                return run
            if run.get("projection_message_index") is not None:
                return self._finish_prepared_projection(run, task, ProjectedRun(
                    result.assistant_message_id, "completed", result.chunks,
                ))
            return self._finish_run(run, task, AutomationRunStatus.SUCCEEDED.value, {
                "generated_prompt": generated_prompt,
                "user_message_id": turn["user_message_id"],
                "assistant_message_id": result.assistant_message_id,
            })

        pending = agent_automation_db.update_run(run["run_id"], {
            "projection_message_index": message_index,
            "projection_memory_agent_id": snapshot.resource.agent_id if snapshot.memory_enabled else None,
        }, run["user_id"], expected_statuses=[AutomationRunStatus.RUNNING.value], tenant_id=run["tenant_id"])
        if pending is None:
            return agent_automation_db.get_run(run["run_id"], run["tenant_id"], run["user_id"]) or run
        run.update(pending)
        client = _agentos_client()
        try:
            admitted = await client.start_prepared_run(snapshot, run["user_id"], run["tenant_id"])
            if admitted != reference:
                raise RuntimeServiceUnavailableError("AgentOS returned a different automation run")
        except (RuntimeServiceTimeoutError, RuntimeServiceUnavailableError):
            return run
        except RuntimeUpstreamError as exc:
            if exc.status_code in {400, 401, 403, 404, 413, 422}:
                return self._finish_prepared_projection(run, task, None)
            return run
        projected = await self._project_prepared_run(client, reference, run)
        return self._finish_prepared_projection(run, task, projected)

    async def _project_prepared_run(self, client, reference, run) -> ProjectedRun:
        receipt = await run_blocking(
            "automation-projection-receipt", get_prepared_projection_receipt,
            projection_run_id=reference.run_id, conversation_id=reference.conversation_id,
            message_index=run["projection_message_index"], message_source=MessageSource.AUTOMATION,
            user_id=run["user_id"], tenant_id=run["tenant_id"], lane="control-io", owner="management",
        )
        if receipt is not None:
            projected = ProjectedRun(receipt[0], receipt[1], 0)
        else:
            memory_scope = {}
            if run.get("projection_memory_agent_id") is not None:
                memory_scope = {
                    "memory_agent_id": run["projection_memory_agent_id"], "memory_source_message_id": run["user_message_id"],
                }
            projected = await resume_assistant_projection(
                client.resume, reference, run["user_id"], run["tenant_id"],
                message_index=run["projection_message_index"], message_source=MessageSource.AUTOMATION, **memory_scope,
            )
        await acknowledge_projection(client, reference, run["user_id"], run["tenant_id"])
        return projected

    async def recover_prepared_run(self, run: dict) -> None:
        if run["run_id"] in self._local_runs:
            return
        user_id, tenant_id = run["user_id"], run["tenant_id"]
        task = await run_blocking(
            "automation-projection-task", agent_automation_db.get_task,
            run["task_id"], tenant_id, user_id, lane="control-io", owner="management",
        )
        if task is None:
            return
        reference = AgentRunReference(run_id=run["runtime_run_id"], conversation_id=run["conversation_id"])
        lookup = AgentRunLookup(**reference.model_dump())
        client = _agentos_client()
        timeout = float(task.get("timeout_seconds") or AGENT_AUTOMATION_DEFAULT_TIMEOUT_SECONDS)
        expired = (_utcnow() - _parse_dt(run["started_at"])).total_seconds() >= timeout
        stopped = run["status"] in {AutomationRunStatus.CANCELED.value, AutomationRunStatus.TIMEOUT.value}
        try:
            state = await client.inspect_run(lookup, user_id, tenant_id)
        except RuntimeUpstreamError as exc:
            if exc.status_code != 404:
                raise
            state = None
        if state is None or state.status in {"starting", "running"}:
            if not (expired or stopped):
                return
            try:
                state = await client.stop_run(AgentStop(**lookup.model_dump(), prevent_start=True), user_id, tenant_id)
            except RuntimeUpstreamError as exc:
                if exc.status_code != 404:
                    raise
                state = None
            if not stopped and (state is None or state.status not in {"completed", "failed"}):
                await run_blocking(
                    "automation-recovery-timeout", self._finish_run, run, task, AutomationRunStatus.TIMEOUT.value,
                    {"error_code": "AUTOMATION_RUN_TIMEOUT",
                     "error_message": f"Automation run exceeded {timeout} seconds."},
                    lane="control-io", owner="management",
                )
                return
            if state is not None and state.status in {"starting", "running"}:
                return
        if state is not None and (state.run_id, state.conversation_id) != (reference.run_id, reference.conversation_id):
            raise RuntimeServiceUnavailableError("AgentOS returned a different automation run")
        try:
            projected = await self._project_prepared_run(client, reference, run)
        except RuntimeUpstreamError as exc:
            if exc.status_code not in {404, 410}:
                raise
            projected = None
        await run_blocking(
            "automation-recovery-finish", self._finish_prepared_projection, run, task, projected,
            lane="control-io", owner="management",
        )

    def _finish_prepared_projection(self, run, task, projected: ProjectedRun | None):
        extra = {"projection_message_index": None, "projection_memory_agent_id": None}
        if projected is not None:
            extra["assistant_message_id"] = projected.assistant_message_id
        if run["status"] == AutomationRunStatus.CANCELED.value:
            return self._finish_run(run, task, AutomationRunStatus.CANCELED.value, {
                **extra, "error_message": run.get("error_message"),
            })
        if run["status"] == AutomationRunStatus.TIMEOUT.value:
            updated = run
        elif projected is not None and projected.status == "completed":
            updated = self._finish_run(run, task, AutomationRunStatus.SUCCEEDED.value, extra)
        else:
            updated = self._finish_run(run, task, AutomationRunStatus.FAILED.value, {
                **extra, "error_code": "AUTOMATION_RUN_FAILED",
                "error_message": "AgentOS did not complete the automation run with a recoverable output.",
            })
        if updated["status"] == AutomationRunStatus.TIMEOUT.value:
            updated = agent_automation_db.update_run(
                run["run_id"], extra, run["user_id"], expected_statuses=[updated["status"]],
            ) or updated
        return updated

    async def cancel_for_conversation(self, conversation_id: int, user_id: str, tenant_id: str) -> None:
        for run_id in agent_automation_db.list_active_runtime_run_ids(conversation_id, user_id, tenant_id):
            await self.cancel_runtime_run(run_id, conversation_id, user_id, tenant_id)

    async def cancel_runtime_run(self, run_id: str | None, conversation_id: int, user_id: str, tenant_id: str) -> None:
        if run_id is None:
            return
        payload = AgentStop(run_id=run_id, conversation_id=conversation_id, prevent_start=True)
        try:
            await asyncio.wait_for(forward_scoped_stop(payload, user_id, tenant_id), timeout=3)
        except (TimeoutError, RuntimeServiceTimeoutError, RuntimeServiceUnavailableError, RuntimeUpstreamError):
            logger.warning("Unable to stop automation run_id=%s", run_id)

    @staticmethod
    def _owns_occurrence(session, task, scheduled, lease_owner, require_active=True):
        return bool(task and (not require_active or task.get("status") == "ACTIVE")
                    and task.get("next_fire_at") is not None
                    and _parse_dt(task["next_fire_at"]) == _parse_dt(scheduled)
                    and task.get("lock_owner") == lease_owner
                    and task.get("lock_until") is not None
                    and agent_automation_db.lease_is_unexpired(session, _parse_dt(task["lock_until"])))

    def cancel_run_by_user(self, run, task):
        transitioned = []
        result = self._finish_run(run, task, "CANCELED", {
            "error_code": "AUTOMATION_RUN_CANCELED",
            "error_message": "Automation run was canceled by user.",
        }, user_cancel=True, transitioned=transitioned)
        return result, bool(transitioned)

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
        if run.get("projection_message_index") is not None:
            return self._finish_prepared_run_state(run, task, status, extra)
        with agent_automation_db.task_run_transaction(
            task["task_id"], task["tenant_id"], task["user_id"], run["run_id"],
        ) as (session, current_task, current_run):
            if not current_task or not current_run:
                return run
            if current_run["status"] not in {"QUEUED", "RUNNING"}:
                return current_run
            scheduled = current_run.get("trigger_type") == "SCHEDULED"
            owner = run.get("_lease_owner")
            if scheduled and owner and not user_cancel and not self._owns_occurrence(
                session, current_task, current_run["scheduled_fire_at"], owner, require_active=False,
            ):
                return current_run
            now = _utcnow()
            updated = agent_automation_db.update_run(run["run_id"], {
                **extra, "status": status, "finished_at": now,
                "duration_ms": max(0, int((now - _parse_dt(current_run.get("started_at"))).total_seconds() * 1000)),
            }, task["user_id"], expected_statuses=["QUEUED", "RUNNING"], db_session=session)
            if not updated:
                return current_run
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

    def _finish_prepared_run_state(
        self,
        run: Dict[str, Any],
        task: Dict[str, Any],
        status: str,
        extra: Dict[str, Any],
    ) -> Dict[str, Any]:
        now = _utcnow()
        started_at = _parse_dt(run.get("started_at"))
        duration_ms = int((now - started_at).total_seconds() * 1000)
        run_values = {**extra, "status": status, "finished_at": now, "duration_ms": duration_ms}
        prepared = run.get("projection_message_index") is not None
        if prepared and status == AutomationRunStatus.CANCELED.value:
            run_values["finished_at"] = run["finished_at"]
            run_values["duration_ms"] = int((_parse_dt(run["finished_at"]) - started_at).total_seconds() * 1000)
        if not prepared:
            updated_run = agent_automation_db.update_run(
                run["run_id"], run_values, task["user_id"], expected_statuses=[AutomationRunStatus.RUNNING.value],
            )
            if not updated_run:
                return agent_automation_db.get_run(run["run_id"], task["tenant_id"], task["user_id"]) or run

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
        if prepared:
            return (agent_automation_db.finish_prepared_run(run, run_values, task_values)
                    or agent_automation_db.get_run(run["run_id"], task["tenant_id"], task["user_id"])
                    or run)
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
        from management.services.automation.scheduler import compute_next_fire_at

        next_fire_at = compute_next_fire_at(trigger, after, fire_count)
        task_status = task.get("status", "ACTIVE")
        if next_fire_at is None:
            task_status = "COMPLETED"
        return fire_count, next_fire_at, task_status


agent_automation_runner = AgentAutomationRunner()
