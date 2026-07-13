import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import IntegrityError

from consts.const import AGENT_AUTOMATION_DEFAULT_TIMEOUT_SECONDS, AGENT_AUTOMATION_MIN_INTERVAL_SECONDS
from database import agent_automation_db
from database.conversation_db import get_conversation
from services.conversation_management_service import (
    create_new_conversation,
    update_conversation_agent_id_service,
)
from .capability_resolver import resolve_agent_capabilities, validate_bindings_available
from .conversation_adapter import automation_conversation_adapter
from .errors import (
    AutomationCapabilityBindingInvalidError,
    AutomationCapabilityNotReadyError,
    AutomationConversationAlreadyBoundError,
    AutomationNotFoundError,
    AutomationScheduleInvalidError,
)
from .intent_analyzer import AutomationIntentContext, automation_intent_analyzer
from .models import (
    AutomationProposalConfirmRequest,
    AutomationProposalCreateRequest,
    AutomationProposalStatus,
    AutomationRunStatus,
    AutomationSource,
    AutomationTaskCreateRequest,
    AutomationTaskPatchRequest,
    AutomationTaskStatus,
    CapabilityBinding,
    ScheduleTrigger,
)
from .prompt_generator import (
    AutomationPromptContext,
    AutomationTaskContent,
    automation_prompt_generator,
    detect_instruction_language,
)
from .schedule_engine import compute_next_fire_at, is_valid_cron_expression

logger = logging.getLogger("agent_automation.facade")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _json(data: Any) -> Any:
    if hasattr(data, "model_dump"):
        return data.model_dump(mode="json")
    if isinstance(data, list):
        return [_json(item) for item in data]
    return data


def _parse_trigger(raw: Dict[str, Any] | ScheduleTrigger) -> ScheduleTrigger:
    return raw if isinstance(raw, ScheduleTrigger) else ScheduleTrigger.model_validate(raw)


def _validate_schedule_policy(trigger: ScheduleTrigger) -> None:
    if trigger.mode.value == "ONCE" and _as_utc(trigger.start_at) <= _utcnow():
        raise AutomationScheduleInvalidError(
            "Automation execution time must be in the future.",
            details={"start_at": trigger.start_at.isoformat()},
        )
    if trigger.rule_type.value == "CRON" and not is_valid_cron_expression(trigger.cron_expr or ""):
        raise AutomationScheduleInvalidError(
            "Automation cron expression is invalid.",
            details={"cron_expr": trigger.cron_expr},
        )
    if (
        trigger.rule_type.value == "INTERVAL"
        and trigger.interval_seconds is not None
        and trigger.interval_seconds < AGENT_AUTOMATION_MIN_INTERVAL_SECONDS
    ):
        raise AutomationScheduleInvalidError(
            f"Automation interval must be at least {AGENT_AUTOMATION_MIN_INTERVAL_SECONDS} seconds.",
            details={
                "min_interval_seconds": AGENT_AUTOMATION_MIN_INTERVAL_SECONDS,
                "interval_seconds": trigger.interval_seconds,
            },
        )


class AgentAutomationFacade:
    async def create_proposal(
        self,
        request: AutomationProposalCreateRequest,
        tenant_id: str,
        user_id: str,
    ) -> Dict[str, Any]:
        try:
            parsed = await automation_intent_analyzer.analyze(AutomationIntentContext(
                tenant_id=tenant_id,
                message=request.message,
                timezone=request.timezone,
                model_id=request.model_id,
            ))
        except ValueError as exc:
            raise AutomationScheduleInvalidError(
                f"无法解析任务执行时间：{exc}",
                details={"input": request.message, "timezone": request.timezone},
            ) from exc
        if not parsed.get("is_automation_intent"):
            return {
                "proposal_id": None,
                "conversation_id": request.conversation_id,
                "confidence": parsed.get("confidence", 0),
                "executable": False,
                "task": None,
                "capability_resolution": None,
                "intent_analysis_source": parsed.get("analysis_source", "rule"),
                "task_content_source": parsed.get("task_content_source"),
            }
        if parsed.get("schedule_error") or not parsed.get("schedule_trigger"):
            raise AutomationScheduleInvalidError(
                parsed.get("schedule_error") or "Unable to determine the automation schedule.",
                details={"input": request.message, "timezone": request.timezone},
            )
        _validate_schedule_policy(parsed["schedule_trigger"])

        if parsed.get("task_content_generated"):
            task_content = AutomationTaskContent(
                title=parsed["title"],
                instruction=parsed["instruction"],
            )
        else:
            task_content = await automation_prompt_generator.generate_task_content(AutomationPromptContext(
                tenant_id=tenant_id,
                instruction=parsed["instruction"],
                language=detect_instruction_language(parsed["instruction"]),
            ))

        conversation_id = request.conversation_id
        if conversation_id is None:
            conversation = create_new_conversation(
                task_content.title,
                user_id,
                agent_id=request.agent_id,
            )
            conversation_id = conversation["conversation_id"]
        else:
            conversation = get_conversation(conversation_id, user_id)
        if not conversation:
            raise AutomationNotFoundError("Conversation does not exist or is not accessible.")
        if conversation_id == request.conversation_id:
            update_conversation_agent_id_service(
                conversation_id,
                request.agent_id,
                user_id,
            )
        if agent_automation_db.get_task_by_conversation(conversation_id, user_id):
            raise AutomationConversationAlreadyBoundError("Conversation already has an active automation task.")

        resolution = await resolve_agent_capabilities(
            agent_id=request.agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
            instruction=task_content.instruction,
            version_no=request.agent_version_no or 0,
        )
        proposed_task = {
            "title": task_content.title,
            "instruction": task_content.instruction,
            "original_instruction": parsed["instruction"],
            "agent_id": request.agent_id,
            "agent_version_no": request.agent_version_no,
            "model_id": request.model_id,
            "tool_params": request.tool_params,
            "schedule_trigger": parsed["schedule_trigger"].model_dump(mode="json"),
        }
        proposal = agent_automation_db.create_proposal({
            "tenant_id": tenant_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "agent_id": request.agent_id,
            "proposed_task": proposed_task,
            "capability_resolution": resolution.model_dump(mode="json"),
            "status": AutomationProposalStatus.PENDING.value,
            "expires_at": _utcnow() + timedelta(hours=24),
        }, user_id)
        response = {
            "proposal_id": proposal["proposal_id"],
            "conversation_id": conversation_id,
            "confidence": parsed["confidence"],
            "executable": resolution.executable,
            "task": proposed_task,
            "capability_resolution": resolution.model_dump(mode="json"),
            "intent_analysis_source": parsed.get("analysis_source", "rule"),
            "task_content_source": parsed.get("task_content_source", "rule"),
        }
        try:
            message_refs = automation_conversation_adapter.append_proposal_exchange(
                conversation_id,
                request.message,
                response,
                user_id,
                tenant_id,
            )
            stored_task = {
                **proposed_task,
                "_conversation_message_id": message_refs["message_id"],
                "_conversation_unit_id": message_refs["unit_id"],
            }
            agent_automation_db.update_proposal_task(
                proposal["proposal_id"],
                tenant_id,
                user_id,
                stored_task,
            )
        except Exception as exc:
            logger.warning("Failed to persist automation proposal card: %s", exc, exc_info=True)
        return response

    async def confirm_proposal(
        self,
        proposal_id: int,
        request: AutomationProposalConfirmRequest,
        tenant_id: str,
        user_id: str,
    ) -> Dict[str, Any]:
        proposal = agent_automation_db.get_proposal(proposal_id, tenant_id, user_id)
        if not proposal or proposal["status"] != AutomationProposalStatus.PENDING.value:
            raise AutomationNotFoundError("Automation proposal does not exist or is not pending.")
        expires_at = proposal.get("expires_at")
        if expires_at and _as_utc(expires_at) <= _utcnow():
            agent_automation_db.update_proposal_status(
                proposal_id,
                tenant_id,
                user_id,
                AutomationProposalStatus.EXPIRED.value,
            )
            raise AutomationNotFoundError("Automation proposal has expired.")

        proposed_task = proposal["proposed_task"]
        instruction = request.instruction or proposed_task["instruction"]
        resolution = await resolve_agent_capabilities(
            agent_id=proposal["agent_id"],
            tenant_id=tenant_id,
            user_id=user_id,
            instruction=instruction,
            version_no=proposed_task.get("agent_version_no") or 0,
        )
        if not resolution.executable:
            raise AutomationCapabilityNotReadyError(
                "Required automation capabilities are not ready.",
                details=resolution.model_dump(mode="json"),
            )

        create_request = AutomationTaskCreateRequest(
            title=proposed_task["title"],
            agent_id=proposal["agent_id"],
            instruction=instruction,
            original_instruction=proposed_task.get("original_instruction") or instruction,
            schedule_trigger=_parse_trigger(proposed_task["schedule_trigger"]),
            conversation_id=proposal["conversation_id"],
            agent_version_no=proposed_task.get("agent_version_no"),
            model_id=proposed_task.get("model_id"),
            tool_params=proposed_task.get("tool_params"),
            capability_bindings=resolution.matched_capabilities,
        )
        task = await self.create_task(create_request, tenant_id, user_id)
        agent_automation_db.update_proposal_status(
            proposal_id, tenant_id, user_id, AutomationProposalStatus.ACCEPTED.value)
        public_task = {key: value for key, value in proposed_task.items() if not key.startswith("_")}
        try:
            automation_conversation_adapter.update_proposal(
                proposed_task.get("_conversation_unit_id"),
                {
                    "proposal_id": proposal_id,
                    "executable": True,
                    "task": public_task,
                    "capability_resolution": proposal["capability_resolution"],
                    "confirmed_task_id": task["task_id"],
                },
                user_id,
            )
        except Exception as exc:
            logger.warning("Failed to persist confirmed automation proposal card: %s", exc, exc_info=True)
        return task

    async def create_task(
        self,
        request: AutomationTaskCreateRequest,
        tenant_id: str,
        user_id: str,
    ) -> Dict[str, Any]:
        trigger = request.schedule_trigger
        _validate_schedule_policy(trigger)
        conversation_id = request.conversation_id
        if not get_conversation(conversation_id, user_id):
            raise AutomationNotFoundError("Conversation does not exist or is not accessible.")

        if agent_automation_db.get_task_by_conversation(conversation_id, user_id):
            raise AutomationConversationAlreadyBoundError("Conversation already has an active automation task.")

        resolution = await resolve_agent_capabilities(
            agent_id=request.agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
            instruction=request.instruction,
            version_no=request.agent_version_no or 0,
        )
        if not resolution.executable:
            raise AutomationCapabilityNotReadyError(
                "Required automation capabilities are not ready.",
                details=resolution.model_dump(mode="json"),
            )

        if request.capability_bindings:
            check = await validate_bindings_available(
                request.agent_id,
                tenant_id,
                user_id,
                request.instruction,
                [_json(binding) for binding in request.capability_bindings],
                request.agent_version_no or 0,
            )
            if check["unavailable_bindings"]:
                raise AutomationCapabilityBindingInvalidError(
                    "Submitted capability bindings are not available for this agent.",
                    details=check,
                )
            bindings = [_json(binding) for binding in request.capability_bindings]
        else:
            bindings = resolution.model_dump(mode="json")["matched_capabilities"]

        next_fire_at = compute_next_fire_at(trigger, _utcnow(), 0)
        runtime_snapshot = {
            **resolution.agent_snapshot,
            "model_id": request.model_id,
            "tool_params": request.tool_params,
            "original_instruction": request.original_instruction or request.instruction,
        }
        try:
            task = agent_automation_db.create_task({
                "tenant_id": tenant_id,
                "user_id": user_id,
                "conversation_id": conversation_id,
                "agent_id": request.agent_id,
                "agent_version_no": request.agent_version_no,
                "title": request.title,
                "instruction": request.instruction,
                "status": AutomationTaskStatus.ACTIVE.value,
                "source": AutomationSource.CHAT_INTENT.value,
                "schedule_mode": trigger.mode.value,
                "schedule_rule_type": trigger.rule_type.value,
                "schedule_expr": trigger.cron_expr or str(trigger.interval_seconds or trigger.start_at),
                "schedule_config": trigger.model_dump(mode="json"),
                "capability_requirements": resolution.model_dump(mode="json"),
                "capability_bindings": bindings,
                "runtime_snapshot": runtime_snapshot,
                "timezone": trigger.timezone,
                "next_fire_at": next_fire_at,
                "fire_count": 0,
                "consecutive_failures": 0,
                "timeout_seconds": request.timeout_seconds or AGENT_AUTOMATION_DEFAULT_TIMEOUT_SECONDS,
                "overlap_policy": "SKIP",
                "misfire_policy": "RUN_ONCE",
            }, user_id)
        except IntegrityError as exc:
            constraint_name = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            if constraint_name == "uq_agent_automation_conversation_active":
                raise AutomationConversationAlreadyBoundError(
                    "Conversation already has an active automation task."
                ) from exc
            raise
        return task

    def list_tasks(self, tenant_id: str, user_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
        return agent_automation_db.list_tasks(tenant_id, user_id, status)

    def get_task(self, task_id: int, tenant_id: str, user_id: str) -> Dict[str, Any]:
        task = agent_automation_db.get_task(task_id, tenant_id, user_id)
        if not task:
            raise AutomationNotFoundError("Automation task not found.")
        return task

    def get_task_for_conversation(self, conversation_id: int, user_id: str) -> Optional[Dict[str, Any]]:
        return agent_automation_db.get_task_by_conversation(conversation_id, user_id)

    async def patch_task(
        self,
        task_id: int,
        request: AutomationTaskPatchRequest,
        tenant_id: str,
        user_id: str,
    ) -> Dict[str, Any]:
        task = self.get_task(task_id, tenant_id, user_id)
        values: Dict[str, Any] = {}
        instruction = request.instruction or task["instruction"]
        if request.title is not None:
            values["title"] = request.title
        if request.instruction is not None:
            values["instruction"] = request.instruction
        if request.timeout_seconds is not None:
            values["timeout_seconds"] = request.timeout_seconds
        if request.model_id is not None or request.tool_params is not None:
            snapshot = dict(task.get("runtime_snapshot") or {})
            if request.model_id is not None:
                snapshot["model_id"] = request.model_id
            if request.tool_params is not None:
                snapshot["tool_params"] = request.tool_params
            values["runtime_snapshot"] = snapshot
        if request.schedule_trigger is not None:
            trigger = request.schedule_trigger
            _validate_schedule_policy(trigger)
            values.update({
                "schedule_mode": trigger.mode.value,
                "schedule_rule_type": trigger.rule_type.value,
                "schedule_expr": trigger.cron_expr or str(trigger.interval_seconds or trigger.start_at),
                "schedule_config": trigger.model_dump(mode="json"),
                "timezone": trigger.timezone,
                "next_fire_at": compute_next_fire_at(trigger, _utcnow(), int(task.get("fire_count") or 0)),
            })
        if request.instruction is not None or request.capability_bindings is not None:
            resolution = await resolve_agent_capabilities(
                task["agent_id"], tenant_id, user_id, instruction, task.get("agent_version_no") or 0)
            if not resolution.executable:
                raise AutomationCapabilityNotReadyError(
                    "Required automation capabilities are not ready.",
                    details=resolution.model_dump(mode="json"),
                )
            values["capability_requirements"] = resolution.model_dump(mode="json")
            values["capability_bindings"] = (
                _json(request.capability_bindings)
                if request.capability_bindings
                else resolution.model_dump(mode="json")["matched_capabilities"]
            )
            snapshot = dict(values.get("runtime_snapshot") or task.get("runtime_snapshot") or {})
            snapshot.update(resolution.agent_snapshot)
            if request.instruction is not None:
                snapshot["original_instruction"] = request.instruction
            values["runtime_snapshot"] = snapshot
        updated = agent_automation_db.update_task(task_id, tenant_id, user_id, values)
        if not updated:
            raise AutomationNotFoundError("Automation task not found.")
        return updated

    def pause_task(self, task_id: int, tenant_id: str, user_id: str) -> Dict[str, Any]:
        task = agent_automation_db.update_task(
            task_id,
            tenant_id,
            user_id,
            {"status": AutomationTaskStatus.PAUSED.value},
        )
        if not task:
            raise AutomationNotFoundError("Automation task not found.")
        return task

    def resume_task(self, task_id: int, tenant_id: str, user_id: str) -> Dict[str, Any]:
        task = self.get_task(task_id, tenant_id, user_id)
        trigger = _parse_trigger(task["schedule_config"])
        next_fire_at = compute_next_fire_at(trigger, _utcnow(), int(task.get("fire_count") or 0))
        if next_fire_at is None:
            raise AutomationScheduleInvalidError("Automation task has no future fire time.")
        updated = agent_automation_db.update_task(task_id, tenant_id, user_id, {
            "status": AutomationTaskStatus.ACTIVE.value,
            "next_fire_at": next_fire_at,
        })
        if not updated:
            raise AutomationNotFoundError("Automation task not found.")
        return updated

    def delete_task(self, task_id: int, tenant_id: str, user_id: str) -> bool:
        task = self.get_task(task_id, tenant_id, user_id)
        self._cancel_active_runs_for_conversation(
            task["conversation_id"],
            user_id,
            "Automation task was deleted.",
        )
        if not agent_automation_db.soft_delete_task(task_id, tenant_id, user_id):
            raise AutomationNotFoundError("Automation task not found.")
        return True

    def list_runs(self, task_id: int, tenant_id: str, user_id: str) -> List[Dict[str, Any]]:
        self.get_task(task_id, tenant_id, user_id)
        return agent_automation_db.list_runs(task_id, tenant_id, user_id)

    async def run_task_now(self, task_id: int, tenant_id: str, user_id: str) -> Dict[str, Any]:
        task = self.get_task(task_id, tenant_id, user_id)
        from .runner import agent_automation_runner
        return await agent_automation_runner.execute_task(task, trigger_type="MANUAL")

    def cancel_run(self, run_id: int, tenant_id: str, user_id: str) -> Dict[str, Any]:
        run = agent_automation_db.get_run(run_id, tenant_id, user_id)
        if not run:
            raise AutomationNotFoundError("Automation run not found.")

        if run["status"] not in {AutomationRunStatus.QUEUED.value, AutomationRunStatus.RUNNING.value}:
            return run

        self._request_conversation_stop(run["conversation_id"], user_id)
        canceled = agent_automation_db.cancel_run(
            run_id,
            tenant_id,
            user_id,
            "Automation run was canceled by user.",
        )
        agent_automation_db.update_task(run["task_id"], tenant_id, user_id, {
            "last_run_status": AutomationRunStatus.CANCELED.value,
            "last_error": "Automation run was canceled by user.",
            "lock_owner": None,
            "lock_until": None,
        })
        return canceled or agent_automation_db.get_run(run_id, tenant_id, user_id) or run

    def on_conversation_deleted(self, conversation_id: int, user_id: str) -> int:
        self._cancel_active_runs_for_conversation(
            conversation_id,
            user_id,
            "Conversation was deleted.",
        )
        return agent_automation_db.soft_delete_task_by_conversation(conversation_id, user_id)

    def _cancel_active_runs_for_conversation(self, conversation_id: int, user_id: str, reason: str) -> None:
        self._request_conversation_stop(conversation_id, user_id)
        agent_automation_db.cancel_runs_by_conversation(conversation_id, user_id, reason)

    def _request_conversation_stop(self, conversation_id: int, user_id: str) -> None:
        try:
            from .runner import agent_automation_runner
            agent_automation_runner.cancel_for_conversation(conversation_id, user_id)
        except Exception:
            pass


agent_automation_facade = AgentAutomationFacade()
