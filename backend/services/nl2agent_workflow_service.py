"""NL2AGENT workflow actions backed by authoritative database and Redis state."""

import logging
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from consts.exceptions import (
    AgentRunException,
    Nl2AgentOperationError,
    Nl2AgentStaleCardError,
    Nl2AgentValidationError,
)
from consts.model import AgentInfoRequest

logger = logging.getLogger(__name__)


def _matches_registered_online_card(
    state: Dict[str, Any], card_type: str, card_key: Optional[str]
) -> bool:
    """Allow either card from one dual-card message to acknowledge after registration."""
    if card_type not in {"web_mcp", "web_skill"} or not card_key:
        return False
    batch = state.get("online_recommendation_batches", {}).get(card_key) or {}
    expected_resource_type = "mcp" if card_type == "web_mcp" else "skill"
    return batch.get("resource_type") == expected_resource_type


def _raise_stale_card(
    *,
    reason: str,
    agent_id: int,
    message_id: int,
    card_type: str,
    status: str,
    card_key: Optional[str],
    message: Optional[Dict[str, Any]] = None,
    latest_message_id: Optional[int] = None,
    expected_card_types: Optional[List[str]] = None,
    error_message: Optional[str] = None,
) -> None:
    """Log a safe rejection reason while preserving the public stale-card error."""
    logger.warning(
        "Rejected NL2AGENT card delivery: stale_reason=%s agent_id=%s "
        "message_id=%s card_type=%s status=%s has_card_key=%s "
        "latest_message_id=%s message_status=%s message_conversation_id=%s "
        "expected_card_types=%s",
        reason,
        agent_id,
        message_id,
        card_type,
        status,
        bool(card_key),
        latest_message_id,
        message.get("status") if message else None,
        message.get("conversation_id") if message else None,
        expected_card_types,
    )
    raise Nl2AgentStaleCardError(error_message or "The NL2AGENT card delivery receipt is stale.")


@dataclass(frozen=True)
class WorkflowDependencies:
    """Persistence and evaluator operations consumed by workflow actions."""

    get_owned_draft: Callable[..., Dict[str, Any]]
    register_online_batch: Callable[..., Dict[str, Any]]
    get_session_state: Callable[..., Dict[str, Any]]
    summarize_workflow_state: Callable[[Dict[str, Any]], Dict[str, Any]]
    get_message: Callable[..., Optional[Dict[str, Any]]]
    get_completed_final_answer: Callable[[int], str]
    get_latest_assistant_message_id: Callable[..., Optional[int]]
    message_contains_valid_card: Callable[..., bool]
    record_card_delivery: Callable[..., Dict[str, Any]]
    complete_online_configuration: Callable[..., List[str]]
    register_requirements_summary: Callable[..., Dict[str, Any]]
    confirm_requirements_summary: Callable[..., Dict[str, Any]]
    apply_requirements_revision_text: Callable[..., Dict[str, Any]]
    find_agent_info_by_agent_id: Callable[..., Optional[Dict[str, Any]]]
    query_enabled_tool_instances: Callable[..., List[Dict[str, Any]]]
    query_enabled_skill_instances: Callable[..., List[Dict[str, Any]]]
    resolve_model_summaries: Callable[
        ..., tuple[List[Dict[str, Any]], List[Dict[str, Any]]]
    ]
    resolve_resource_summaries: Callable[
        ...,
        tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]],
    ]
    query_tools_by_ids: Callable[..., List[Dict[str, Any]]]
    sanitize_tool_parameter_schema: Callable[[Any], List[Dict[str, Any]]]
    normalize_model_ids: Callable[[Any], List[int]]
    generate_internal_agent_name: Callable[..., str]
    get_db_session: Callable[[], Any]
    update_agent: Callable[..., Any]
    confirm_agent_identity: Callable[..., Any]
    runner_agent_name: str
    continuation_text: str
    card_retry_text: str


async def register_online_resource_recommendations(
    dependencies: WorkflowDependencies,
    *,
    agent_id: int,
    recommendation_batch_id: str,
    resource_type: str,
    item_keys: List[str],
    tenant_id: str,
) -> Dict[str, Any]:
    """Record one MCP or web-Skill result batch rendered by the frontend."""
    dependencies.get_owned_draft(agent_id, tenant_id)
    batch = dependencies.register_online_batch(
        tenant_id,
        agent_id,
        recommendation_batch_id,
        resource_type,
        item_keys,
    )
    return {"recommendation_batch_id": recommendation_batch_id, **batch}


async def report_card_delivery(
    dependencies: WorkflowDependencies,
    *,
    agent_id: int,
    message_id: int,
    card_type: str,
    status: str,
    card_key: Optional[str],
    reason: Optional[str],
    tenant_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Record a receipt only for the latest persisted assistant message."""
    dependencies.get_owned_draft(agent_id, tenant_id)
    state = dependencies.get_session_state(tenant_id, agent_id)
    conversation_id = int(state["conversation_id"])
    message = dependencies.get_message(message_id, user_id=user_id)
    latest_message_id = dependencies.get_latest_assistant_message_id(
        conversation_id,
        user_id=user_id,
    )
    stale_reason = None
    if not message:
        stale_reason = "message_missing"
    elif int(message.get("conversation_id") or 0) != conversation_id:
        stale_reason = "conversation_mismatch"
    elif message.get("message_role") != "assistant":
        stale_reason = "role_mismatch"
    elif message.get("status") != "completed":
        stale_reason = "message_not_completed"
    elif latest_message_id != message_id:
        stale_reason = "message_not_latest"
    if stale_reason:
        _raise_stale_card(
            reason=stale_reason,
            agent_id=agent_id,
            message_id=message_id,
            card_type=card_type,
            status=status,
            card_key=card_key,
            message=message,
            latest_message_id=latest_message_id,
        )
    if status == "rendered":
        parent_content = str(message.get("message_content") or "")
        contains_valid_card = dependencies.message_contains_valid_card(
            parent_content, card_type, agent_id, card_key
        )
        if not contains_valid_card:
            recovered_content = dependencies.get_completed_final_answer(message_id)
            contains_valid_card = bool(
                recovered_content
            ) and dependencies.message_contains_valid_card(
                recovered_content, card_type, agent_id, card_key
            )
            if contains_valid_card:
                logger.warning(
                    "Validated NL2AGENT card delivery from completed message units "
                    "after parent content mismatch: agent_id=%s message_id=%s card_type=%s",
                    agent_id,
                    message_id,
                    card_type,
                )
        if not contains_valid_card:
            _raise_stale_card(
                reason="persisted_card_mismatch",
                agent_id=agent_id,
                message_id=message_id,
                card_type=card_type,
                status=status,
                card_key=card_key,
                message=message,
                latest_message_id=latest_message_id,
                error_message=(
                    "The persisted assistant message does not contain the reported valid NL2AGENT card."
                ),
            )

    summary = dependencies.summarize_workflow_state(state)
    if card_type not in summary["expected_card_types"]:
        existing = state.get("card_delivery", {}).get(card_type) or {}
        is_idempotent_receipt = (
            existing.get("message_id") == message_id
            and existing.get("status") == status
            and existing.get("card_key") == card_key
        )
        if not is_idempotent_receipt and not _matches_registered_online_card(
            state, card_type, card_key
        ):
            _raise_stale_card(
                reason="card_not_expected",
                agent_id=agent_id,
                message_id=message_id,
                card_type=card_type,
                status=status,
                card_key=card_key,
                message=message,
                latest_message_id=latest_message_id,
                expected_card_types=list(summary["expected_card_types"]),
            )

    delivery = dependencies.record_card_delivery(
        tenant_id,
        agent_id,
        message_id,
        card_type,
        status,
        card_key,
        reason,
    )
    retry_count = int(delivery.get("retry_count", 0))
    response = {
        "agent_id": agent_id,
        **delivery,
        "auto_retry_allowed": status == "failed" and retry_count <= 2,
    }
    if status == "failed":
        response["chat_injection_text"] = dependencies.card_retry_text
    return response


async def confirm_online_resource_configuration(
    dependencies: WorkflowDependencies,
    *,
    agent_id: int,
    tenant_id: str,
) -> Dict[str, Any]:
    """Persist the user's global decision to finish online configuration."""
    dependencies.get_owned_draft(agent_id, tenant_id)
    completed_batch_ids = dependencies.complete_online_configuration(
        tenant_id,
        agent_id,
    )
    return {
        "agent_id": agent_id,
        "online_configuration_confirmed": True,
        "completed_batch_ids": completed_batch_ids,
        "chat_injection_text": dependencies.continuation_text,
    }


async def register_requirements_review(
    dependencies: WorkflowDependencies,
    *,
    agent_id: int,
    summary: Dict[str, Any],
    tenant_id: str,
) -> Dict[str, Any]:
    """Register the rendered five-field requirements summary for one draft."""
    dependencies.get_owned_draft(agent_id, tenant_id)
    review = dependencies.register_requirements_summary(
        tenant_id,
        agent_id,
        summary,
    )
    return {
        "agent_id": agent_id,
        "status": review["status"],
        "summary": review["summary"],
        "fingerprint": review["fingerprint"],
        "is_current": review["is_current"],
    }


def process_requirements_revision_text(
    dependencies: WorkflowDependencies,
    *,
    runner_agent_id: Optional[int],
    draft_agent_id: int,
    tenant_id: str,
    text: str,
) -> Dict[str, Any]:
    """Process textual requirement revisions only for the seeded runner."""
    runner = dependencies.find_agent_info_by_agent_id(
        agent_id=runner_agent_id,
        tenant_id=tenant_id,
    )
    if not runner or runner.get("name") != dependencies.runner_agent_name:
        return {"intent": "not_applicable"}
    dependencies.get_owned_draft(draft_agent_id, tenant_id)
    return dependencies.apply_requirements_revision_text(
        tenant_id,
        draft_agent_id,
        text,
    )


async def confirm_requirements_review(
    dependencies: WorkflowDependencies,
    *,
    agent_id: int,
    fingerprint: str,
    tenant_id: str,
) -> Dict[str, Any]:
    """Confirm the current registered requirements revision."""
    dependencies.get_owned_draft(agent_id, tenant_id)
    review = dependencies.confirm_requirements_summary(
        tenant_id,
        agent_id,
        fingerprint,
    )
    return {
        "agent_id": agent_id,
        "status": review["status"],
        "fingerprint": review["fingerprint"],
        "chat_injection_text": dependencies.continuation_text,
    }


async def get_session_state(
    dependencies: WorkflowDependencies,
    *,
    agent_id: int,
    tenant_id: str,
) -> Dict[str, Any]:
    """Return authoritative draft models, resources, and workflow state."""
    draft = dependencies.get_owned_draft(agent_id, tenant_id)
    tool_instances = (
        dependencies.query_enabled_tool_instances(
            agent_id,
            tenant_id,
            version_no=0,
        )
        or []
    )
    skill_instances = (
        dependencies.query_enabled_skill_instances(
            agent_id,
            tenant_id,
            version_no=0,
        )
        or []
    )
    models, invalid_model_references = dependencies.resolve_model_summaries(
        draft,
        tenant_id,
    )
    tools, skills, invalid_resource_references = (
        dependencies.resolve_resource_summaries(
            tool_instances,
            skill_instances,
            tenant_id,
        )
    )
    workflow_state = deepcopy(dependencies.get_session_state(tenant_id, agent_id))
    workflow_summary = dependencies.summarize_workflow_state(workflow_state)
    workflow_state.pop("online_installations", None)
    for batch in workflow_state.get("recommendation_batches", {}).values():
        batch.pop("operation_id", None)
        if batch.get("status") == "applying":
            batch["status"] = "recommendations_ready"
            batch["applied_tool_ids"] = []
            batch["applied_skill_ids"] = []
    for workflow in workflow_state.get("mcp_workflows", {}).values():
        workflow.pop("binding_operation_id", None)
        if workflow.get("status") == "binding":
            workflow["status"] = "connected"
            workflow["bound_tool_ids"] = []
        discovered_ids = [
            int(tool_id) for tool_id in workflow.get("discovered_tool_ids", [])
        ]
        discovered_rows = (
            dependencies.query_tools_by_ids(discovered_ids, tenant_id)
            if discovered_ids
            else []
        )
        discovered_by_id = {int(row["tool_id"]): row for row in discovered_rows}
        workflow["discovered_tools"] = [
            {
                "tool_id": tool_id,
                "name": discovered_by_id.get(tool_id, {}).get("name") or str(tool_id),
                "description": discovered_by_id.get(tool_id, {}).get("description")
                or "",
            }
            for tool_id in discovered_ids
        ]
    recommendation_batches = workflow_state.get("recommendation_batches", {})
    recommended_ids_by_batch = {
        batch_id: [int(tool_id) for tool_id in batch.get("tool_ids", [])]
        for batch_id, batch in recommendation_batches.items()
    }
    all_recommended_tool_ids = sorted(
        {
            tool_id
            for tool_ids in recommended_ids_by_batch.values()
            for tool_id in tool_ids
        }
    )
    recommended_rows = (
        dependencies.query_tools_by_ids(all_recommended_tool_ids, tenant_id)
        if all_recommended_tool_ids
        else []
    )
    recommended_rows_by_id = {
        int(row["tool_id"]): row for row in recommended_rows
    }
    local_tool_parameter_schemas = {
        batch_id: {
            str(tool_id): dependencies.sanitize_tool_parameter_schema(
                recommended_rows_by_id[tool_id].get("params")
            )
            for tool_id in tool_ids
            if tool_id in recommended_rows_by_id
        }
        for batch_id, tool_ids in recommended_ids_by_batch.items()
    }
    return {
        "agent_id": agent_id,
        "schema_version": workflow_state["schema_version"],
        "revision": workflow_state["revision"],
        "current_stage": workflow_summary["current_stage"],
        "expected_card_types": workflow_summary["expected_card_types"],
        "allowed_actions": workflow_summary["allowed_actions"],
        "display_name": draft.get("display_name"),
        "internal_name": dependencies.generate_internal_agent_name(
            draft.get("display_name") or "",
            agent_id,
            tenant_id,
        ),
        "business_logic_model_id": draft.get("business_logic_model_id"),
        "model_ids": dependencies.normalize_model_ids(draft.get("model_ids")),
        "models": models,
        "tools": tools,
        "skills": skills,
        "local_tool_parameter_schemas": local_tool_parameter_schemas,
        "invalid_references": invalid_model_references + invalid_resource_references,
        "identity_confirmed": workflow_state.get("identity_confirmed", False),
        "resource_review": workflow_state,
    }


async def save_agent_identity(
    dependencies: WorkflowDependencies,
    *,
    agent_id: int,
    display_name: str,
    tenant_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Persist a confirmed display name without publishing the draft."""
    draft = dependencies.get_owned_draft(agent_id, tenant_id)
    normalized_display_name = display_name.strip()
    if not normalized_display_name:
        raise Nl2AgentValidationError("Agent display name cannot be empty.")
    if draft.get("display_name") != normalized_display_name:
        try:
            with dependencies.get_db_session() as db_session:
                dependencies.update_agent(
                    agent_id=agent_id,
                    agent_info=AgentInfoRequest(display_name=normalized_display_name),
                    user_id=user_id,
                    version_no=0,
                    db_session=db_session,
                )
        except AgentRunException:
            raise
        except Exception as exc:
            logger.error(
                "Failed to save NL2AGENT identity: tenant_id=%s draft_agent_id=%s",
                tenant_id,
                agent_id,
                exc_info=True,
            )
            raise Nl2AgentOperationError(
                "Failed to save the agent display name."
            ) from exc
    try:
        dependencies.confirm_agent_identity(tenant_id, agent_id)
    except Exception as exc:
        logger.error(
            "NL2AGENT identity was committed but confirmation failed: "
            "tenant_id=%s draft_agent_id=%s",
            tenant_id,
            agent_id,
            exc_info=True,
        )
        raise Nl2AgentOperationError(
            "The agent display name was saved, but confirmation could not be "
            "completed. Retry saving the name."
        ) from exc
    return {
        "agent_id": agent_id,
        "display_name": normalized_display_name,
        "internal_name": dependencies.generate_internal_agent_name(
            normalized_display_name,
            agent_id,
            tenant_id,
        ),
        "identity_confirmed": True,
        "chat_injection_text": dependencies.continuation_text,
    }
