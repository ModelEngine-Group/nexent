"""NL2AGENT conversational agent generator service.

Provides the business logic for the NL2AGENT default agent: a conversational agent
that helps users build custom agents via multi-turn chat.

This service is intentionally thin: it orchestrates existing services
(tool_configuration_service, skill_service, mcp_management_service)
rather than reimplementing them.

After the SDK decoupling refactor:
- The 3 search tools are pure SDK with keyword scoring and backend-injected catalogs.
- The finalize skill synthesizes the full agent spec; this service writes it to the
  draft agent row and upserts tool/skill instances with per-agent config overrides.
"""

import logging
import re
import uuid
from typing import Any, Dict, List, Optional

from agents.nl2agent_session_catalog import set_nl2agent_session_catalogs
from consts.const import LANGUAGE
from consts.const import DEFAULT_TENANT_ID, DEFAULT_USER_ID
from consts.exceptions import AgentRunException
from consts.model import (
    AgentInfoRequest,
    ModelConnectStatusEnum,
    SkillInstanceInfoRequest,
    ToolInstanceInfoRequest,
)
from database.agent_db import (
    create_agent,
    query_all_agent_info_by_tenant_id,
    search_agent_id_by_agent_name,
    search_agent_info_by_agent_id,
    update_agent,
)
from database.conversation_db import create_conversation
from database.model_management_db import get_model_records
from database.skill_db import (
    create_or_update_skill_by_skill_info,
    get_skill_by_id as get_tenant_skill_by_id,
    list_skills as list_tenant_skills,
)
from database.tool_db import (
    create_or_update_tool_by_tool_info,
    query_tools_by_ids,
    seed_nl2agent_builtin_tools,
)
from services.mcp_management_service import (
    list_community_mcp_services,
    list_registry_mcp_services,
)
from services.skill_service import (
    get_official_skills_with_status,
    install_skills_for_tenant,
    install_skills_from_zip_for_tenant,
)
from services.tool_configuration_service import list_all_tools
from utils.prompt_template_utils import get_nl2agent_seed_config

logger = logging.getLogger(__name__)

# Reserved name of the NL2AGENT default agent shipped with the product.
NL2AGENT_AGENT_NAME = "nl2agent"

# Prefix for draft agent names created during NL2AGENT sessions.
DRAFT_AGENT_NAME_PREFIX = "draft_"

_NL2AGENT_SEED_PROMPT_FALLBACK = (
    "You are NL2AGENT, the Agent Builder. Help the user design and build "
    "a custom agent through multi-turn natural-language dialogue."
)
_NL2AGENT_AGENT_INFO_FALLBACK = {
    "name": NL2AGENT_AGENT_NAME,
    "display_name": "Agent Builder",
    "description": (
        "Conversational assistant that helps you design and build your own "
        "custom agent through multi-turn natural-language dialogue."
    ),
    "business_description": (
        "Conversational agent generator. Guides users through multi-turn "
        "dialogue to define a custom agent, recommends local and web "
        "resources, and finalizes a draft agent."
    ),
}
_NL2AGENT_PROMPT_SEGMENTS_FALLBACK = {
    "duty_prompt": _NL2AGENT_SEED_PROMPT_FALLBACK,
    "constraint_prompt": (
        "Always wait for explicit user confirmation before applying local "
        "resources or finalizing the agent. Never make up tool or skill names. "
        "Use the user's language."
    ),
    "few_shots_prompt": "",
}

_NL2AGENT_VERIFICATION_CONFIG = {
    "enabled": True,
    "step_verification_enabled": True,
    "final_verification_enabled": True,
    "llm_verification_enabled": False,
    "max_final_rounds": 2,
    "strictness": "balanced",
    "fail_policy": "repair_then_controlled_summary",
    "pass_score": 0.75,
    "critical_events": [
        "tool_precheck",
        "tool_result",
        "retrieval",
        "code_execution",
        "handoff",
        "final_answer",
    ],
}


def _is_draft_agent_name(name: Optional[str]) -> bool:
    return bool(name) and name.startswith(DRAFT_AGENT_NAME_PREFIX)


def _load_nl2agent_seed_fields() -> Dict[str, str]:
    """Load user-facing NL2AGENT seed fields from the English YAML config."""
    seed_fields = {
        **_NL2AGENT_AGENT_INFO_FALLBACK,
        **_NL2AGENT_PROMPT_SEGMENTS_FALLBACK,
    }
    try:
        seed_config = get_nl2agent_seed_config(LANGUAGE["EN"])
        seed_fields.update(seed_config.get("agent_info") or {})
        seed_fields.update(seed_config.get("prompt_segments") or {})
    except Exception as exc:
        logger.warning(f"Failed to load NL2AGENT seed config: {exc}")

    seed_fields["name"] = NL2AGENT_AGENT_NAME
    return seed_fields


def _normalize_model_ids(value: Any) -> List[int]:
    if not value:
        return []
    if isinstance(value, (str, int)):
        value = [value]

    normalized: List[int] = []
    for item in value:
        try:
            model_id = int(item)
        except (TypeError, ValueError):
            continue
        if model_id not in normalized:
            normalized.append(model_id)
    return normalized


def _get_available_llm_model_ids(tenant_id: str) -> List[int]:
    """Return all connected LLM-style models the builder agent can offer."""
    try:
        records = get_model_records(None, tenant_id) or []
    except Exception as exc:
        logger.warning(
            f"Failed to list models for NL2AGENT seed in tenant {tenant_id}: {exc}"
        )
        return []

    model_ids: List[int] = []
    for record in records:
        model_type = record.get("model_type")
        if model_type not in {"llm", "chat"}:
            continue

        connect_status = ModelConnectStatusEnum.get_value(
            record.get("connect_status")
        )
        if connect_status != ModelConnectStatusEnum.AVAILABLE.value:
            continue

        try:
            model_id = int(record["model_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if model_id not in model_ids:
            model_ids.append(model_id)

    return model_ids


def _build_nl2agent_seed_defaults(tenant_id: str) -> Dict[str, Any]:
    model_ids = _get_available_llm_model_ids(tenant_id)
    defaults: Dict[str, Any] = {
        **_load_nl2agent_seed_fields(),
        "prompt_template_id": None,
        "prompt_template_name": None,
        "verification_config": _NL2AGENT_VERIFICATION_CONFIG,
    }
    if model_ids:
        defaults["model_ids"] = model_ids
        defaults["business_logic_model_id"] = model_ids[0]
    return defaults


def _ensure_nl2agent_seed_defaults(
    agent: Dict[str, Any], user_id: str, tenant_id: str
) -> None:
    """Backfill intended prompt/template/model defaults on existing NL2AGENT rows."""
    agent_id = agent.get("agent_id")
    if not agent_id:
        return

    defaults = _build_nl2agent_seed_defaults(tenant_id)
    update_values: Dict[str, Any] = {}

    for field in (
        "name",
        "display_name",
        "description",
        "business_description",
        "prompt_template_id",
        "prompt_template_name",
        "duty_prompt",
        "constraint_prompt",
        "few_shots_prompt",
        "verification_config",
    ):
        if agent.get(field) != defaults[field]:
            update_values[field] = defaults[field]

    desired_model_ids = defaults.get("model_ids") or []
    if (
        desired_model_ids
        and _normalize_model_ids(agent.get("model_ids")) != desired_model_ids
    ):
        update_values["model_ids"] = desired_model_ids

    if (
        desired_model_ids
        and agent.get("business_logic_model_id") not in desired_model_ids
    ):
        update_values["business_logic_model_id"] = desired_model_ids[0]

    if not update_values:
        return

    try:
        update_agent(
            agent_id=agent_id,
            agent_info=AgentInfoRequest(**update_values),
            user_id=user_id,
            version_no=0,
        )
    except Exception as exc:
        logger.warning(
            f"Failed to backfill NL2AGENT seed defaults for "
            f"agent_id={agent_id}: {exc}"
        )


async def start_session(
    user_id: str, tenant_id: str, language: str
) -> Dict[str, Any]:
    """Create a draft agent and a conversation for a new NL2AGENT session.

    The draft agent is created with version_no=0 (draft). Its name uses the
    ``draft_<uuid8>`` convention so it can be hidden from the main agent list.

    Pre-fetches all catalogs needed by the 3 pure-SDK search tools and returns
    them alongside the session IDs so the caller can inject them into tool metadata.

    Returns:
        - ``nl2agent_agent_id``: the seeded default NL2AGENT agent that runs the chat.
        - ``draft_agent_id``: the target draft agent being built.
        - ``conversation_id``: the conversation created for this session.
        - ``draft_name``: the draft agent's name (for display/debug).
        - ``tool_catalog``: compact list of LOCAL/MCP/LANGCHAIN tool rows.
        - ``skill_catalog``: compact list of tenant skill rows.
        - ``registry_results``: raw registry MCP servers.
        - ``community_results``: community MCP servers.
        - ``official_skills``: official skill definitions with status.
    """
    # Resolve the seeded NL2AGENT default agent. It is created at config_app
    # startup via seed_nl2agent_default_agent(); querying by name keeps the
    # contract explicit so callers never confuse the builder agent with the
    # draft target.
    try:
        nl2agent_agent_id = search_agent_id_by_agent_name(
            NL2AGENT_AGENT_NAME, tenant_id
        )
    except Exception as exc:
        logger.warning(
            f"NL2AGENT default agent missing for tenant {tenant_id}; "
            f"attempting tenant seed: {exc}"
        )
        nl2agent_agent_id = seed_nl2agent_default_agent(
            tenant_id=tenant_id, user_id=user_id
        )

    if not nl2agent_agent_id:
        raise AgentRunException(
            f"Failed to seed NL2AGENT default agent for tenant {tenant_id}."
        )

    try:
        nl2agent_agent = search_agent_info_by_agent_id(
            agent_id=nl2agent_agent_id, tenant_id=tenant_id
        )
        if nl2agent_agent:
            _ensure_nl2agent_seed_defaults(
                nl2agent_agent, user_id=user_id, tenant_id=tenant_id
            )
    except Exception as exc:
        logger.warning(
            f"Failed to verify NL2AGENT prompt template link for "
            f"tenant {tenant_id}: {exc}"
        )

    draft_name = f"{DRAFT_AGENT_NAME_PREFIX}{uuid.uuid4().hex[:8]}"
    draft_display_name = "Draft Agent (NL2AGENT)"

    agent_payload = {
        "name": draft_name,
        "display_name": draft_display_name,
        "description": "Draft agent generated by NL2AGENT session",
        "max_steps": 15,
        "enabled": True,
        "is_new": False,
    }

    try:
        created = create_agent(agent_payload, tenant_id=tenant_id, user_id=user_id)
    except Exception as exc:
        logger.error(f"Failed to create draft agent for NL2AGENT session: {exc}")
        raise AgentRunException("Failed to create draft agent.") from exc

    draft_agent_id = created.get("agent_id")
    if not draft_agent_id:
        raise AgentRunException("Draft agent creation returned no agent_id.")

    conversation_title = f"NL2AGENT - {draft_name}"
    try:
        conversation = create_conversation(
            conversation_title=conversation_title, user_id=user_id
        )
    except Exception as exc:
        logger.error(f"Failed to create conversation for NL2AGENT session: {exc}")
        raise AgentRunException("Failed to create conversation.") from exc

    # Pre-fetch catalogs for the 3 pure-SDK search tools.
    tool_catalog: List[Dict[str, Any]] = []
    try:
        all_tools = list_all_tools(tenant_id=tenant_id, labels=None) or []
        for t in all_tools:
            src = str(t.get("source") or "").lower()
            if src not in ("local", "mcp", "langchain"):
                continue
            tool_catalog.append({
                "tool_id": t.get("tool_id"),
                "name": t.get("name") or t.get("origin_name") or "",
                "description": (t.get("description") or "")[:400],
                "labels": t.get("labels") or [],
                "source": src,
                "category": t.get("category") or "",
                "usage": t.get("usage") or "",
                "params": t.get("params") or [],
            })
    except Exception as exc:
        logger.warning(f"Failed to pre-fetch tool catalog for NL2AGENT session: {exc}")

    skill_catalog: List[Dict[str, Any]] = []
    try:
        tenant_skills = list_tenant_skills(tenant_id=tenant_id) or []
        for s in tenant_skills:
            skill_catalog.append({
                "skill_id": s.get("skill_id"),
                "name": s.get("name") or s.get("skill_name") or "",
                "description": (s.get("description") or "")[:400],
                "tags": s.get("tags") or [],
                "config_schema": s.get("config_schema") or {},
            })
    except Exception as exc:
        logger.warning(f"Failed to pre-fetch skill catalog for NL2AGENT session: {exc}")

    registry_results: List[Dict[str, Any]] = []
    try:
        registry_data = await list_registry_mcp_services(search=None, limit=30)
        if isinstance(registry_data, dict):
            registry_results = registry_data.get("servers", registry_data) or []
    except Exception as exc:
        logger.warning(f"Failed to pre-fetch registry MCP results: {exc}")

    community_results: List[Dict[str, Any]] = []
    try:
        community_data = list_community_mcp_services(search=None, limit=30)
        if isinstance(community_data, dict):
            community_results = community_data.get("items", community_data) or []
    except Exception as exc:
        logger.warning(f"Failed to pre-fetch community MCP results: {exc}")

    official_skills: List[Dict[str, Any]] = []
    try:
        official_skills = get_official_skills_with_status(tenant_id=tenant_id) or []
    except Exception as exc:
        logger.warning(f"Failed to pre-fetch official skills: {exc}")

    session_catalogs = {
        "tool_catalog": tool_catalog,
        "skill_catalog": skill_catalog,
        "registry_results": registry_results,
        "community_results": community_results,
        "official_skills": official_skills,
    }
    set_nl2agent_session_catalogs(tenant_id, draft_agent_id, session_catalogs)

    return {
        "nl2agent_agent_id": nl2agent_agent_id,
        "draft_agent_id": draft_agent_id,
        "conversation_id": conversation.get("conversation_id"),
        "draft_name": draft_name,
        # Catalogs for SDK tools
        **session_catalogs,
    }


def _validate_draft_agent_id(agent_id: int) -> None:
    if not isinstance(agent_id, int) or agent_id <= 0:
        raise AgentRunException("Invalid NL2AGENT draft agent_id.")


async def apply_local_resources_batch(
    agent_id: int,
    tool_ids: List[int],
    skill_ids: List[int],
    tenant_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Bulk-bind local tools and skills to the draft agent.

    Tools: creates/updates ToolInstance rows with enabled=True.
    Skills: installs official skills for the tenant if not yet installed, then
    binds them as SkillInstances to the agent.

    Returns counts of bound items.
    """
    _validate_draft_agent_id(agent_id)

    bound_tools = 0
    bound_skills = 0
    bound_tool_ids: List[int] = []
    bound_skill_ids: List[int] = []

    # Bind tools.
    for tool_id in tool_ids or []:
        try:
            tool_info = query_tools_by_ids([tool_id])
            if not tool_info:
                logger.warning(f"Tool id {tool_id} not found, skipping.")
                continue
            ti = tool_info[0]
            params = ti.get("params") or {}
            if not isinstance(params, dict):
                params = {}
            instance_req = ToolInstanceInfoRequest(
                tool_id=tool_id,
                agent_id=agent_id,
                params=params,
                enabled=True,
                version_no=0,
            )
            create_or_update_tool_by_tool_info(
                tool_info=instance_req,
                tenant_id=tenant_id,
                user_id=user_id,
                version_no=0,
            )
            bound_tools += 1
            bound_tool_ids.append(tool_id)
        except Exception as exc:
            logger.error(f"Failed to bind tool {tool_id} to agent {agent_id}: {exc}")

    # Bind skills. Local tenant skills already have ag_skill_info_t rows; web
    # official skills may arrive as global template IDs and must be installed
    # into the tenant before creating the per-agent SkillInstance row.
    for skill_id in skill_ids or []:
        try:
            tenant_skill = get_tenant_skill_by_id(skill_id, tenant_id)
            target_skill_id = skill_id
            if not tenant_skill:
                installed_ids = install_skills_for_tenant(
                    skill_ids=[skill_id], tenant_id=tenant_id, user_id=user_id
                )
                if not installed_ids:
                    logger.warning(f"Skill id {skill_id} not found or installable, skipping.")
                    continue
                target_skill_id = installed_ids[0]

            instance_req = SkillInstanceInfoRequest(
                skill_id=target_skill_id,
                agent_id=agent_id,
                enabled=True,
                version_no=0,
            )
            create_or_update_skill_by_skill_info(
                skill_info=instance_req,
                tenant_id=tenant_id,
                user_id=user_id,
                version_no=0,
            )
            bound_skills += 1
            bound_skill_ids.append(target_skill_id)
        except Exception as exc:
            logger.error(f"Failed to bind skill {skill_id} to agent {agent_id}: {exc}")

    return {
        "bound_tool_count": bound_tools,
        "bound_skill_count": bound_skills,
        "tool_ids": bound_tool_ids,
        "skill_ids": bound_skill_ids,
    }


async def install_web_skill(
    skill_id: Optional[int],
    tenant_id: str,
    user_id: str,
    skill_name: Optional[str] = None,
    locale: Optional[str] = None,
) -> Dict[str, Any]:
    """Install a single official/web skill into the tenant."""
    if skill_name:
        try:
            installed_names = install_skills_from_zip_for_tenant(
                skill_names=[skill_name],
                tenant_id=tenant_id,
                user_id=user_id,
                locale=locale,
            )
        except Exception as exc:
            logger.error(f"Failed to install web skill {skill_name}: {exc}")
            raise AgentRunException(f"Failed to install skill {skill_name}.") from exc

        return {
            "skill_id": skill_id or 0,
            "skill_name": skill_name,
            "installed": bool(installed_names),
            "installed_ids": [],
            "installed_names": installed_names,
        }

    if not skill_id or skill_id <= 0:
        raise AgentRunException("Either skill_name or a positive skill_id is required.")

    try:
        installed = install_skills_for_tenant(
            skill_ids=[skill_id], tenant_id=tenant_id, user_id=user_id
        )
    except Exception as exc:
        logger.error(f"Failed to install web skill {skill_id}: {exc}")
        raise AgentRunException(f"Failed to install skill {skill_id}.") from exc

    return {
        "skill_id": skill_id,
        "installed": bool(installed),
        "installed_ids": installed,
    }


async def finalize_agent(
    agent_id: int,
    user_id: str,
    tenant_id: str,
    # Identity
    name: Optional[str] = None,
    display_name: Optional[str] = None,
    description: Optional[str] = None,
    # LLM models
    business_logic_model_id: Optional[int] = None,
    model_ids: Optional[List[int]] = None,
    # Task & template
    business_description: Optional[str] = None,
    prompt_template_id: Optional[int] = None,
    # Prompts (from finalize skill output)
    duty_prompt: Optional[str] = None,
    constraint_prompt: Optional[str] = None,
    few_shots_prompt: Optional[str] = None,
    # UI
    greeting_message: Optional[str] = None,
    example_questions: Optional[List[str]] = None,
    # Runtime
    max_steps: Optional[int] = None,
    requested_output_tokens: Optional[int] = None,
    provide_run_summary: bool = False,
    verification_config: Optional[Dict[str, Any]] = None,
    enable_context_manager: bool = True,
    # Resources
    tool_ids: Optional[List[int]] = None,
    skill_ids: Optional[List[int]] = None,
    sub_agent_ids: Optional[List[int]] = None,
    # Per-agent config overrides (tool_id -> {param: value})
    tool_configs: Optional[Dict[str, Dict[str, Any]]] = None,
    # Per-skill config overrides (skill_id -> {config_key: value})
    skill_configs: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Finalize the draft agent with the full spec produced by the nl2agent_finalize_proposal skill.

    Writes all fields from the skill output to the draft agent row and upserts
    tool/skill instances with per-agent config overrides.

    Args:
        agent_id: Draft agent ID to finalize.
        user_id: Acting user ID for audit fields.
        tenant_id: Tenant scope.
        name: Programmatic snake_case name (optional; generated if absent).
        display_name: User-facing name.
        description: Agent description.
        business_logic_model_id: LLM model used for generation/routing.
        model_ids: Runtime LLM models.
        business_description: Task description from the skill output.
        prompt_template_id: Prompt template to apply.
        duty_prompt: Role description prompt section.
        constraint_prompt: Constraints prompt section.
        few_shots_prompt: Few-shot examples prompt section.
        greeting_message: Welcome message.
        example_questions: Starter questions shown to the user.
        max_steps: Maximum agent steps.
        requested_output_tokens: Output token budget.
        provide_run_summary: Whether to provide a run summary.
        verification_config: Verification behaviour dict.
        enable_context_manager: Whether to enable context management.
        tool_ids: IDs of tools to bind.
        skill_ids: IDs of skills to bind.
        sub_agent_ids: IDs of sub-agents to bind.
        tool_configs: Per-tool param overrides, keyed by tool_id (str or int).
        skill_configs: Per-skill config overrides, keyed by skill_id (str or int).
    """
    _validate_draft_agent_id(agent_id)

    # Build the agent update payload from whatever the skill provided.
    agent_update: Dict[str, Any] = {}
    if display_name is not None:
        agent_update["display_name"] = str(display_name)[:50]
    if name is not None:
        agent_update["name"] = str(name)[:50]
    elif display_name is not None:
        # Fallback programmatic name: snake_case of display_name.
        s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", display_name)
        snake = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()
        agent_update["name"] = re.sub(r"[^a-zA-Z0-9_]", "_", snake)[:50]
    if description is not None:
        agent_update["description"] = str(description)[:500]
    if business_description is not None:
        agent_update["business_description"] = str(business_description)[:2000]
    if business_logic_model_id is not None:
        agent_update["business_logic_model_id"] = business_logic_model_id
    if model_ids is not None:
        agent_update["model_ids"] = model_ids[:5]
    if prompt_template_id is not None:
        agent_update["prompt_template_id"] = prompt_template_id
    if duty_prompt is not None:
        agent_update["duty_prompt"] = str(duty_prompt)[:8000]
    if constraint_prompt is not None:
        agent_update["constraint_prompt"] = str(constraint_prompt)[:4000]
    if few_shots_prompt is not None:
        agent_update["few_shots_prompt"] = str(few_shots_prompt)[:8000]
    if greeting_message is not None:
        agent_update["greeting_message"] = str(greeting_message)[:500]
    if example_questions is not None:
        agent_update["example_questions"] = example_questions[:6]
    if max_steps is not None:
        agent_update["max_steps"] = max(1, min(30, int(max_steps)))
    if requested_output_tokens is not None:
        agent_update["requested_output_tokens"] = max(1, int(requested_output_tokens))
    if provide_run_summary is not None:
        agent_update["provide_run_summary"] = bool(provide_run_summary)
    if verification_config is not None and isinstance(verification_config, dict):
        agent_update["verification_config"] = verification_config
    if enable_context_manager is not None:
        agent_update["enable_context_manager"] = bool(enable_context_manager)

    # Write agent fields.
    if agent_update:
        try:
            update_agent(
                agent_id=agent_id,
                agent_info=AgentInfoRequest(**agent_update),
                user_id=user_id,
                version_no=0,
            )
        except Exception as exc:
            logger.error(f"Failed to update draft agent {agent_id}: {exc}")
            raise AgentRunException("Failed to finalize agent.") from exc

    # Upsert tool instances with per-agent param overrides.
    tool_configs = tool_configs or {}
    for tool_id in tool_ids or []:
        tid = int(tool_id)
        # Per-agent overrides from skill output; merge with catalog defaults.
        override_params: Dict[str, Any] = {}
        key = str(tid)
        if key in tool_configs:
            override_params = tool_configs[key]
        else:
            # Fall back: fetch catalog defaults for merge.
            try:
                rows = query_tools_by_ids([tid])
                if rows:
                    override_params = rows[0].get("params") or {}
            except Exception:
                pass

        try:
            instance_req = ToolInstanceInfoRequest(
                tool_id=tid,
                agent_id=agent_id,
                params=override_params,
                enabled=True,
                version_no=0,
            )
            create_or_update_tool_by_tool_info(
                tool_info=instance_req,
                tenant_id=tenant_id,
                user_id=user_id,
                version_no=0,
            )
        except Exception as exc:
            logger.error(f"Failed to upsert tool instance {tid} on agent {agent_id}: {exc}")

    # Upsert skill instances with per-skill config overrides.
    skill_configs = skill_configs or {}
    for skill_id in skill_ids or []:
        sid = int(skill_id)
        override_config: Optional[Dict[str, Any]] = None
        key = str(sid)
        if key in skill_configs:
            override_config = skill_configs[key]

        try:
            instance_req = SkillInstanceInfoRequest(
                skill_id=sid,
                agent_id=agent_id,
                enabled=True,
                version_no=0,
                config_values=override_config,
            )
            create_or_update_skill_by_skill_info(
                skill_info=instance_req,
                tenant_id=tenant_id,
                user_id=user_id,
                version_no=0,
            )
        except Exception as exc:
            logger.error(f"Failed to upsert skill instance {sid} on agent {agent_id}: {exc}")

    # Rename the draft agent away from the draft_ prefix so it appears in the main list.
    try:
        current = search_agent_info_by_agent_id(
            agent_id=agent_id, tenant_id=tenant_id
        )
        current_name = (current or {}).get("name") or ""
        if _is_draft_agent_name(current_name):
            final_name = current_name.replace(DRAFT_AGENT_NAME_PREFIX, "agent_")
            update_agent(
                agent_id=agent_id,
                agent_info={"name": final_name},
                user_id=user_id,
                version_no=0,
            )
    except Exception as exc:
        logger.warning(f"Failed to rename draft agent {agent_id}: {exc}")

    return {"agent_id": agent_id, "status": "draft_ready"}


# ---------------------------------------------------------------------------
# Startup seeding
# ---------------------------------------------------------------------------


def seed_nl2agent_default_agent(
    tenant_id: str = DEFAULT_TENANT_ID,
    user_id: str = DEFAULT_USER_ID,
) -> Optional[int]:
    """Seed the NL2AGENT default agent for a tenant if it does not yet exist.

    This is called once on application startup. It:
    1. Inserts the 3 NL2AGENT builtin tool catalog rows (idempotent).
    2. Creates the NL2AGENT default agent (name="nl2agent") if absent, with
       the 3 builtin tools bound as ToolInstances.

    Returns the agent_id of the NL2AGENT default agent, or None on failure.
    """
    # 1. Seed the builtin tool catalog rows.
    try:
        tool_ids = seed_nl2agent_builtin_tools(tenant_id=tenant_id, user_id=user_id)
    except Exception as exc:
        logger.error(f"Failed to seed NL2AGENT builtin tools: {exc}")
        return None

    # 2. Check if the NL2AGENT default agent already exists for this tenant.
    try:
        all_agents = query_all_agent_info_by_tenant_id(tenant_id) or []
    except Exception as exc:
        logger.error(f"Failed to query agents for NL2AGENT seeding: {exc}")
        return None

    for agent in all_agents:
        if (agent.get("name") or "") == NL2AGENT_AGENT_NAME:
            existing_id = agent.get("agent_id")
            _ensure_nl2agent_seed_defaults(
                agent, user_id=user_id, tenant_id=tenant_id
            )
            logger.info(
                f"NL2AGENT default agent already exists (agent_id={existing_id})"
            )
            return existing_id

    # 3. Create the NL2AGENT default agent.
    agent_payload = {
        "max_steps": 20,
        "enabled": True,
        "is_new": False,
    }
    agent_payload.update(_build_nl2agent_seed_defaults(tenant_id))

    try:
        created = create_agent(agent_payload, tenant_id=tenant_id, user_id=user_id)
    except Exception as exc:
        logger.error(f"Failed to create NL2AGENT default agent: {exc}")
        return None

    agent_id = created.get("agent_id")
    if not agent_id:
        logger.error("NL2AGENT default agent creation returned no agent_id.")
        return None

    # 4. Bind the 3 builtin tools to the NL2AGENT agent as ToolInstances.
    for tool_id in tool_ids:
        try:
            instance_req = ToolInstanceInfoRequest(
                tool_id=tool_id,
                agent_id=agent_id,
                params={},
                enabled=True,
                version_no=0,
            )
            create_or_update_tool_by_tool_info(
                tool_info=instance_req,
                tenant_id=tenant_id,
                user_id=user_id,
                version_no=0,
            )
        except Exception as exc:
            logger.error(
                f"Failed to bind builtin tool {tool_id} to NL2AGENT agent: {exc}"
            )

    logger.info(
        f"Seeded NL2AGENT default agent (agent_id={agent_id}) with "
        f"{len(tool_ids)} builtin tools for tenant {tenant_id}"
    )
    return agent_id
