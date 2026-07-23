"""Plan management tools for the agent.

These two tools implement v1.4 of the planning feature: instead of relying on
string-marker parsing (e.g. __STEP_COMPLETE__) in the LLM's free-form output,
the agent is expected to call these tools from inside the Python code block
it writes. Tool calls are structurally validated by smolagents' Pydantic
schema, so invalid arguments are rejected before they reach the plan state.

Dependencies (observer, plan_repo, bound callbacks) are injected via
Field(exclude=True) __init__ parameters, exactly like KnowledgeBaseSearchTool.
"""

from __future__ import annotations

import json
import logging
import uuid
from enum import Enum
from typing import Callable, List, Optional

from pydantic import Field
from smolagents.tools import Tool

from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import ToolCategory, ToolSign

logger = logging.getLogger("plan_tools")


class PlanStatus(str, Enum):
    """Status of a plan step. Mirrors the Literal in PlanStep.status."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class CreatePlanTool(Tool):
    """Tool the LLM calls once at the start of execution to register a plan."""

    name = "create_plan"
    description = (
        "Create the execution plan for the current task. Call this exactly once "
        "at the start of execution with 3-8 functional steps. Each step must "
        "have a stable id (step-1, step-2, ...), a short title, and a detailed "
        "description. Returns the created plan id and step count."
    )
    description_zh = (
        "为当前任务创建执行计划。开始执行前调用一次，传入 3-8 个功能块步骤。"
        "每个步骤必须有稳定的 id（step-1、step-2、...）、简短标题和详细描述。"
        "返回创建的计划 id 和步骤数量。"
    )

    inputs = {
        "plan_id": {
            "type": "string",
            "description": "Unique plan identifier (UUID)",
            "description_zh": "计划唯一标识（UUID）",
        },
        "title": {
            "type": "string",
            "description": "Short plan title",
            "description_zh": "简短的计划标题",
        },
        "steps": {
            "type": "array",
            "description": (
                "List of 3-8 steps. Each step is a dict with keys: "
                "id (str, e.g. 'step-1'), title (str, short), description (str)."
            ),
            "description_zh": (
                "3-8 个步骤的列表，每个步骤是字典，包含 id（字符串，如 step-1）、"
                "title（字符串，简短）、description（字符串，详细描述）三个键。"
            ),
        },
    }
    output_type = "object"

    category = ToolCategory.PLANNING.value
    tool_sign = ToolSign.PLAN_OPERATION.value

    def __init__(
        self,
        observer: MessageObserver = Field(
            description="Message observer", default=None, exclude=True
        ),
        plan_repo: "object" = Field(
            description="PlanRepo for persisting plan state", default=None, exclude=True
        ),
        on_plan_created: Callable = Field(
            description="Hook invoked after a plan is created", default=None, exclude=True
        ),
        get_conversation_id: Callable = Field(
            description="Returns the current conversation ID", default=None, exclude=True
        ),
        get_user_id: Callable = Field(
            description="Returns the current user ID", default=None, exclude=True
        ),
    ) -> None:
        super().__init__()
        self.observer = observer
        self.plan_repo = plan_repo
        self._on_plan_created = on_plan_created
        self._get_conversation_id = get_conversation_id
        self._get_user_id = get_user_id

    def forward(self, plan_id: str, title: str, steps: list) -> dict:
        # Local import avoids pulling agent_model into the tool module's
        # import graph; agent_model imports from us via __init__.
        from ..agents.agent_model import AgentPlan, PlanStep

        if not isinstance(steps, list) or len(steps) < 3:
            raise ValueError(
                f"create_plan requires at least 3 steps, got "
                f"{len(steps) if isinstance(steps, list) else 'N/A'}"
            )
        if len(steps) > 8:
            logger.warning(
                f"create_plan received {len(steps)} steps; recommended max is 8"
            )

        seen_ids: set[str] = set()
        plan_steps: List[PlanStep] = []
        for raw in steps:
            if not isinstance(raw, dict):
                raise ValueError(
                    f"each step must be a dict, got {type(raw).__name__}"
                )
            sid = str(raw.get("id", "")).strip()
            if not sid:
                raise ValueError("step.id is required")
            if sid in seen_ids:
                raise ValueError(f"duplicate step id: {sid}")
            seen_ids.add(sid)
            plan_steps.append(PlanStep(
                id=sid,
                title=str(raw.get("title", "")).strip() or sid,
                description=str(raw.get("description", "")).strip(),
                status="pending",
            ))

        plan = AgentPlan(
            plan_id=str(plan_id).strip() or str(uuid.uuid4()),
            title=str(title).strip(),
            steps=plan_steps,
            current_step_index=0,
        )
        plan.steps[0].status = PlanStatus.IN_PROGRESS.value

        # Persist
        if self.plan_repo is not None:
            try:
                conv_id = self._get_conversation_id() if self._get_conversation_id else 0
                user_id = str(self._get_user_id() if self._get_user_id else "anonymous")
                self.plan_repo.save(
                    plan.model_dump(),
                    conversation_id=conv_id,
                    user_id=user_id,
                )
            except Exception as e:
                logger.warning(f"PlanRepo.save failed in create_plan: {e}")

        # Emit SSE event
        if self.observer is not None:
            try:
                self.observer.add_message(
                    "",
                    ProcessType.PLAN,
                    json.dumps({
                        "plan_id": plan.plan_id,
                        "title": plan.title,
                        "steps": [s.model_dump() for s in plan.steps],
                    }, ensure_ascii=False),
                )
            except Exception as e:
                logger.warning(f"observer.add_message(PLAN) failed: {e}")

        # Notify CoreAgent
        if self._on_plan_created is not None:
            try:
                self._on_plan_created(plan)
            except Exception as e:
                logger.warning(f"on_plan_created callback raised: {e}")

        return {"plan_id": plan.plan_id, "step_count": len(plan.steps)}


class UpdatePlanStepTool(Tool):
    """Tool the LLM calls to update a plan step's status during execution."""

    name = "update_plan_step"
    description = (
        "Update the status of a single plan step. Call this with "
        "status='completed' after finishing a step, or status='skipped' if the "
        "step is no longer needed. You may also call this with "
        "status='in_progress' at the start of a step to mark it active. "
        "Returns the updated step id and status."
    )
    description_zh = (
        "更新单个计划步骤的状态。完成后调用 status='completed'，不再需要时调用"
        " status='skipped'，开始执行时调用 status='in_progress'。"
        "返回被更新的步骤 id 和状态。"
    )

    inputs = {
        "step_id": {
            "type": "string",
            "description": "Step id to update, e.g. 'step-2'",
            "description_zh": "要更新的步骤 id，如 'step-2'",
        },
        "status": {
            "type": "string",
            "enum": [s.value for s in PlanStatus],
            "description": "New status for the step",
            "description_zh": "步骤的新状态",
        },
    }
    output_type = "object"

    category = ToolCategory.PLANNING.value
    tool_sign = ToolSign.PLAN_OPERATION.value

    def __init__(
        self,
        observer: MessageObserver = Field(
            description="Message observer", default=None, exclude=True
        ),
        plan_repo: "object" = Field(
            description="PlanRepo for persisting plan state", default=None, exclude=True
        ),
        on_step_updated: Callable = Field(
            description="Hook invoked after a step's status changes", default=None, exclude=True
        ),
        get_conversation_id: Callable = Field(
            description="Returns the current conversation ID", default=None, exclude=True
        ),
        get_user_id: Callable = Field(
            description="Returns the current user ID", default=None, exclude=True
        ),
    ) -> None:
        super().__init__()
        self.observer = observer
        self.plan_repo = plan_repo
        self._on_step_updated = on_step_updated
        self._get_conversation_id = get_conversation_id
        self._get_user_id = get_user_id

    def forward(self, step_id: str, status: str) -> dict:
        try:
            new_status = PlanStatus(status).value
        except ValueError:
            raise ValueError(
                f"status must be one of {[s.value for s in PlanStatus]}, "
                f"got {status!r}"
            )

        # Resolve current plan from the bound callback's owner
        owner = getattr(self._on_step_updated, "__self__", None)
        plan = getattr(owner, "current_plan", None) if owner else None
        if plan is None:
            raise RuntimeError("no active plan; call create_plan first")

        target = next((s for s in plan.steps if s.id == step_id), None)
        if target is None:
            raise ValueError(
                f"unknown step_id {step_id!r}; available: "
                f"{[s.id for s in plan.steps]}"
            )

        old_status = target.status
        target.status = new_status

        # Persist
        if self.plan_repo is not None:
            try:
                conv_id = self._get_conversation_id() if self._get_conversation_id else 0
                user_id = str(self._get_user_id() if self._get_user_id else "anonymous")
                self.plan_repo.save(
                    plan.model_dump(),
                    conversation_id=conv_id,
                    user_id=user_id,
                )
            except Exception as e:
                logger.warning(f"PlanRepo.save failed in update_plan_step: {e}")

        # Emit SSE event
        if self.observer is not None:
            try:
                self.observer.add_message(
                    "",
                    ProcessType.PLAN_STEP_UPDATE,
                    json.dumps({"step_id": step_id, "status": new_status}, ensure_ascii=False),
                )
            except Exception as e:
                logger.warning(f"observer.add_message(PLAN_STEP_UPDATE) failed: {e}")

        # Notify CoreAgent to advance current_step_index
        if self._on_step_updated is not None:
            try:
                self._on_step_updated(plan, step_id, new_status)
            except Exception as e:
                logger.warning(f"on_step_updated callback raised: {e}")

        return {
            "step_id": step_id,
            "status": new_status,
            "previous_status": old_status,
        }


__all__ = [
    "PlanStatus",
    "CreatePlanTool",
    "UpdatePlanStepTool",
]
