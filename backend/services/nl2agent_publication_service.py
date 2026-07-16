"""Publication orchestration for an NL2AGENT draft."""

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from consts.exceptions import AgentRunException
from consts.model import AgentInfoRequest


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PublicationDependencies:
    """Persistence and workflow operations required to publish a draft."""

    validate_draft_agent_id: Callable[[int], None]
    get_owned_draft: Callable[[int, str], Dict[str, Any]]
    normalize_model_ids: Callable[[Any], List[int]]
    validate_available_llm_ids: Callable[..., Dict[int, Dict[str, Any]]]
    assert_requirements_confirmed: Callable[[str, int], None]
    assert_resource_review_complete: Callable[[str, int], None]
    assert_mcp_workflows_resolved: Callable[[str, int], None]
    assert_online_configuration_complete: Callable[[str, int], None]
    assert_identity_confirmed: Callable[[str, int], None]
    query_enabled_tools: Callable[..., List[Dict[str, Any]]]
    query_enabled_skills: Callable[..., List[Dict[str, Any]]]
    resolve_resource_summaries: Callable[..., Any]
    raise_for_invalid_references: Callable[[List[Dict[str, Any]]], None]
    generate_internal_name: Callable[[str, int, str], str]
    update_agent: Callable[..., Any]


async def publish_agent(
    dependencies: PublicationDependencies,
    *,
    agent_id: int,
    user_id: str,
    tenant_id: str,
    description: Optional[str] = None,
    business_description: Optional[str] = None,
    prompt_template_id: Optional[int] = None,
    duty_prompt: Optional[str] = None,
    constraint_prompt: Optional[str] = None,
    few_shots_prompt: Optional[str] = None,
    greeting_message: Optional[str] = None,
    example_questions: Optional[List[str]] = None,
    max_steps: Optional[int] = None,
    requested_output_tokens: Optional[int] = None,
    provide_run_summary: bool = False,
    verification_config: Optional[Dict[str, Any]] = None,
    enable_context_manager: bool = True,
) -> Dict[str, Any]:
    """Publish a draft using proposal text and authoritative persisted state."""
    dependencies.validate_draft_agent_id(agent_id)
    current_draft = dependencies.get_owned_draft(agent_id, tenant_id)
    stored_primary_model_id = current_draft.get("business_logic_model_id")
    stored_model_ids = dependencies.normalize_model_ids(current_draft.get("model_ids"))
    if not stored_primary_model_id or stored_primary_model_id not in stored_model_ids:
        raise AgentRunException("Select a primary LLM before finalizing the agent.")
    dependencies.validate_available_llm_ids(
        tenant_id,
        stored_model_ids,
        finalizing=True,
    )

    workflow_checks = (
        dependencies.assert_requirements_confirmed,
        dependencies.assert_resource_review_complete,
        dependencies.assert_mcp_workflows_resolved,
        dependencies.assert_online_configuration_complete,
        dependencies.assert_identity_confirmed,
    )
    for check in workflow_checks:
        try:
            check(tenant_id, agent_id)
        except Exception as exc:
            raise AgentRunException(str(exc)) from exc

    missing_proposal_fields = [
        field_name
        for field_name, field_value in (
            ("business_description", business_description),
            ("duty_prompt", duty_prompt),
            ("greeting_message", greeting_message),
        )
        if not isinstance(field_value, str) or not field_value.strip()
    ]
    if missing_proposal_fields:
        raise AgentRunException(
            "The final proposal is incomplete: " + ", ".join(missing_proposal_fields)
        )

    persisted_tools = (
        dependencies.query_enabled_tools(agent_id, tenant_id, version_no=0) or []
    )
    persisted_skills = (
        dependencies.query_enabled_skills(agent_id, tenant_id, version_no=0) or []
    )
    _, _, invalid_references = dependencies.resolve_resource_summaries(
        persisted_tools,
        persisted_skills,
        tenant_id,
    )
    dependencies.raise_for_invalid_references(invalid_references)

    final_display_name = str(current_draft.get("display_name") or "").strip()[:50]
    if not final_display_name:
        raise AgentRunException("The persisted agent display name is missing.")

    agent_update: Dict[str, Any] = {
        "display_name": final_display_name,
        "name": dependencies.generate_internal_name(
            final_display_name,
            agent_id,
            tenant_id,
        ),
        "business_logic_model_id": int(stored_primary_model_id),
        "model_ids": stored_model_ids[:5],
    }
    optional_values = (
        ("description", description, 500),
        ("business_description", business_description, 2000),
        ("duty_prompt", duty_prompt, 8000),
        ("constraint_prompt", constraint_prompt, 4000),
        ("few_shots_prompt", few_shots_prompt, 8000),
        ("greeting_message", greeting_message, 500),
    )
    for field_name, value, max_length in optional_values:
        if value is not None:
            agent_update[field_name] = str(value)[:max_length]
    if prompt_template_id is not None:
        agent_update["prompt_template_id"] = prompt_template_id
    if example_questions is not None:
        agent_update["example_questions"] = example_questions[:6]
    if max_steps is not None:
        agent_update["max_steps"] = max(1, min(30, int(max_steps)))
    if requested_output_tokens is not None:
        agent_update["requested_output_tokens"] = max(1, int(requested_output_tokens))
    agent_update["provide_run_summary"] = bool(provide_run_summary)
    if verification_config is not None and isinstance(verification_config, dict):
        agent_update["verification_config"] = verification_config
    agent_update["enable_context_manager"] = bool(enable_context_manager)

    try:
        dependencies.update_agent(
            agent_id=agent_id,
            agent_info=AgentInfoRequest(**agent_update),
            user_id=user_id,
            version_no=0,
        )
    except Exception as exc:
        logger.error(
            "Failed to update NL2AGENT draft during publication: "
            "tenant_id=%s draft_agent_id=%s",
            tenant_id,
            agent_id,
            exc_info=True,
        )
        raise AgentRunException("Failed to finalize agent.") from exc

    return {
        "agent_id": agent_id,
        "status": "draft_ready",
        "name": agent_update["name"],
        "display_name": final_display_name,
        "tool_ids": [row["tool_id"] for row in persisted_tools],
        "skill_ids": [row["skill_id"] for row in persisted_skills],
    }
