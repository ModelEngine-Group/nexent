"""Publication orchestration for an NL2AGENT draft."""

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from consts.exceptions import AgentRunException
from consts.model import AgentInfoRequest


logger = logging.getLogger(__name__)


def _validate_requested_output_tokens(
    requested_output_tokens: Optional[int],
    primary_model: Dict[str, Any],
) -> None:
    """Keep publication output-token validation aligned with normal Agent saves."""
    if requested_output_tokens is None:
        return
    max_output_tokens = primary_model.get("max_output_tokens")
    if max_output_tokens is not None and requested_output_tokens > max_output_tokens:
        raise AgentRunException(
            "requested_output_tokens cannot exceed the selected model "
            f"max_output_tokens ({max_output_tokens})"
        )


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


@dataclass(frozen=True)
class PublicationProposal:
    """Validated user-facing fields proposed for the persisted draft."""

    description: Optional[str]
    business_description: Optional[str]
    duty_prompt: Optional[str]
    constraint_prompt: Optional[str]
    few_shots_prompt: Optional[str]
    greeting_message: Optional[str]
    example_questions: Optional[List[str]]
    max_steps: Optional[int]
    requested_output_tokens: Optional[int]
    provide_run_summary: bool
    verification_config: Optional[Dict[str, Any]]
    enable_context_manager: bool


async def publish_agent(
    dependencies: PublicationDependencies,
    *,
    agent_id: int,
    user_id: str,
    tenant_id: str,
    description: Optional[str] = None,
    business_description: Optional[str] = None,
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
    proposal = PublicationProposal(
        description=description,
        business_description=business_description,
        duty_prompt=duty_prompt,
        constraint_prompt=constraint_prompt,
        few_shots_prompt=few_shots_prompt,
        greeting_message=greeting_message,
        example_questions=example_questions,
        max_steps=max_steps,
        requested_output_tokens=requested_output_tokens,
        provide_run_summary=provide_run_summary,
        verification_config=verification_config,
        enable_context_manager=enable_context_manager,
    )
    primary_model_id, model_ids = _validate_publication_models(
        dependencies,
        current_draft=current_draft,
        tenant_id=tenant_id,
        requested_output_tokens=requested_output_tokens,
    )
    _assert_publication_workflow(dependencies, tenant_id, agent_id)
    _validate_proposal(proposal)
    persisted_tools, persisted_skills = _validate_persisted_resources(
        dependencies,
        agent_id=agent_id,
        tenant_id=tenant_id,
    )
    agent_update = _build_agent_update(
        dependencies,
        current_draft=current_draft,
        proposal=proposal,
        agent_id=agent_id,
        tenant_id=tenant_id,
        primary_model_id=primary_model_id,
        model_ids=model_ids,
    )
    _persist_agent_update(
        dependencies,
        agent_id=agent_id,
        tenant_id=tenant_id,
        user_id=user_id,
        agent_update=agent_update,
    )
    return {
        "agent_id": agent_id,
        "status": "draft_ready",
        "name": agent_update["name"],
        "display_name": agent_update["display_name"],
        "tool_ids": [row["tool_id"] for row in persisted_tools],
        "skill_ids": [row["skill_id"] for row in persisted_skills],
    }


def _validate_publication_models(
    dependencies: PublicationDependencies,
    *,
    current_draft: Dict[str, Any],
    tenant_id: str,
    requested_output_tokens: Optional[int],
) -> tuple[int, List[int]]:
    primary_model_id = current_draft.get("business_logic_model_id")
    model_ids = dependencies.normalize_model_ids(current_draft.get("model_ids"))
    if not primary_model_id or primary_model_id not in model_ids:
        raise AgentRunException("Select a primary LLM before finalizing the agent.")
    validated_models = dependencies.validate_available_llm_ids(
        tenant_id,
        model_ids,
        finalizing=True,
    )
    _validate_requested_output_tokens(
        requested_output_tokens,
        validated_models[int(primary_model_id)],
    )
    return int(primary_model_id), model_ids


def _assert_publication_workflow(
    dependencies: PublicationDependencies,
    tenant_id: str,
    agent_id: int,
) -> None:
    checks = (
        dependencies.assert_requirements_confirmed,
        dependencies.assert_resource_review_complete,
        dependencies.assert_mcp_workflows_resolved,
        dependencies.assert_online_configuration_complete,
        dependencies.assert_identity_confirmed,
    )
    for check in checks:
        try:
            check(tenant_id, agent_id)
        except Exception as exc:
            raise AgentRunException(str(exc)) from exc


def _validate_proposal(proposal: PublicationProposal) -> None:
    missing_fields = [
        field_name
        for field_name in (
            "business_description",
            "duty_prompt",
            "greeting_message",
        )
        if not isinstance(getattr(proposal, field_name), str)
        or not getattr(proposal, field_name).strip()
    ]
    if missing_fields:
        raise AgentRunException(
            "The final proposal is incomplete: " + ", ".join(missing_fields)
        )


def _validate_persisted_resources(
    dependencies: PublicationDependencies,
    *,
    agent_id: int,
    tenant_id: str,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    tools = dependencies.query_enabled_tools(agent_id, tenant_id, version_no=0) or []
    skills = dependencies.query_enabled_skills(agent_id, tenant_id, version_no=0) or []
    _, _, invalid_references = dependencies.resolve_resource_summaries(
        tools,
        skills,
        tenant_id,
    )
    dependencies.raise_for_invalid_references(invalid_references)
    return tools, skills


def _build_agent_update(
    dependencies: PublicationDependencies,
    *,
    current_draft: Dict[str, Any],
    proposal: PublicationProposal,
    agent_id: int,
    tenant_id: str,
    primary_model_id: int,
    model_ids: List[int],
) -> Dict[str, Any]:
    display_name = str(current_draft.get("display_name") or "").strip()[:50]
    if not display_name:
        raise AgentRunException("The persisted agent display name is missing.")
    agent_update: Dict[str, Any] = {
        "display_name": display_name,
        "name": dependencies.generate_internal_name(
            display_name,
            agent_id,
            tenant_id,
        ),
        "business_logic_model_id": primary_model_id,
        "model_ids": model_ids[:5],
    }
    optional_values = (
        ("description", proposal.description, 500),
        ("business_description", proposal.business_description, 2000),
        ("duty_prompt", proposal.duty_prompt, 8000),
        ("constraint_prompt", proposal.constraint_prompt, 4000),
        ("few_shots_prompt", proposal.few_shots_prompt, 8000),
        ("greeting_message", proposal.greeting_message, 500),
    )
    for field_name, value, max_length in optional_values:
        if value is not None:
            agent_update[field_name] = str(value)[:max_length]
    if proposal.example_questions is not None:
        agent_update["example_questions"] = proposal.example_questions[:6]
    if proposal.max_steps is not None:
        agent_update["max_steps"] = max(1, min(30, int(proposal.max_steps)))
    if proposal.requested_output_tokens is not None:
        agent_update["requested_output_tokens"] = max(
            1,
            int(proposal.requested_output_tokens),
        )
    agent_update["provide_run_summary"] = bool(proposal.provide_run_summary)
    if isinstance(proposal.verification_config, dict):
        agent_update["verification_config"] = proposal.verification_config
    agent_update["enable_context_manager"] = bool(proposal.enable_context_manager)
    return agent_update


def _persist_agent_update(
    dependencies: PublicationDependencies,
    *,
    agent_id: int,
    tenant_id: str,
    user_id: str,
    agent_update: Dict[str, Any],
) -> None:
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
