"""NL2AGENT workflow actions backed by authoritative PostgreSQL state."""

import logging
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from consts.exceptions import (
    AgentRunException,
    Nl2AgentOperationError,
    Nl2AgentValidationError,
)
from consts.model import AgentInfoRequest

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkflowDependencies:
    """Persistence and evaluator operations consumed by workflow actions."""

    get_owned_draft: Callable[..., Dict[str, Any]]
    get_readable_draft: Callable[..., tuple[Dict[str, Any], str]]
    get_session_state: Callable[..., Dict[str, Any]]
    summarize_workflow_state: Callable[[Dict[str, Any]], Dict[str, Any]]
    complete_online_configuration: Callable[..., List[str]]
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
    resolve_online_resource_provenance: Callable[..., Any]
    query_tools_by_ids: Callable[..., List[Dict[str, Any]]]
    sanitize_tool_parameter_schema: Callable[[Any], List[Dict[str, Any]]]
    normalize_model_ids: Callable[[Any], List[int]]
    generate_internal_agent_name: Callable[..., str]
    get_db_session: Callable[[], Any]
    update_agent: Callable[..., Any]
    confirm_agent_identity: Callable[..., Any]
    runner_agent_name: str


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


async def get_session_state(
    dependencies: WorkflowDependencies,
    *,
    agent_id: int,
    tenant_id: str,
) -> Dict[str, Any]:
    """Return authoritative draft models, resources, and workflow state."""
    draft, session_status = dependencies.get_readable_draft(agent_id, tenant_id)
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
    workflow_state = deepcopy(dependencies.get_session_state(tenant_id, agent_id))
    online_tool_ids, online_skill_ids, online_skill_names = (
        dependencies.resolve_online_resource_provenance(
            workflow_state,
            tenant_id=tenant_id,
            draft_agent_id=agent_id,
        )
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
            online_tool_ids=online_tool_ids,
            online_skill_ids=online_skill_ids,
            online_skill_names=online_skill_names,
        )
    )
    workflow_summary = dependencies.summarize_workflow_state(workflow_state)
    for batch in workflow_state.get("recommendations", {}).values():
        batch.pop("operation_id", None)
    for workflow in workflow_state.get("mcp_workflows", {}).values():
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
    local_batches = {
        batch_id: batch
        for batch_id, batch in workflow_state.get("recommendations", {}).items()
        if batch.get("resource_type") == "local"
    }
    recommended_ids_by_batch = {
        batch_id: [int(tool_id) for tool_id in batch.get("tool_ids", [])]
        for batch_id, batch in local_batches.items()
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
        "session_status": session_status,
        "schema_version": workflow_state["schema_version"],
        "revision": workflow_state["revision"],
        "current_stage": workflow_summary["current_stage"],
        "expected_card_types": (
            workflow_summary["expected_card_types"]
            if session_status == "active"
            else []
        ),
        "allowed_actions": (
            workflow_summary["allowed_actions"] if session_status == "active" else []
        ),
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
    }
