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

import hashlib
import json
import logging
import re
import unicodedata
import uuid
from copy import deepcopy
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from nexent.core.tools.nl2agent.search_web_mcps_tool import normalize_mcp_candidate

from agents.nl2agent_session_catalog import (
    acquire_mcp_installation_lock,
    apply_requirements_revision_text,
    assert_requirements_confirmed,
    assert_identity_confirmed,
    assert_mcp_workflows_resolved,
    assert_online_configuration_complete,
    assert_resource_review_complete,
    complete_online_configuration as complete_online_configuration_state,
    confirm_requirements_summary,
    confirm_agent_identity,
    delete_nl2agent_session_catalogs,
    find_mcp_workflow_by_id,
    get_nl2agent_session_catalogs,
    get_nl2agent_session_state,
    get_workflow_summary,
    initialize_nl2agent_session_state,
    mutate_nl2agent_session_catalogs,
    register_recommendation_batch,
    register_online_recommendation_batch,
    register_requirements_summary,
    record_card_delivery,
    release_mcp_installation_lock,
    resolve_recommendation_batch,
    set_nl2agent_session_catalogs,
    set_model_selection_confirmed,
    update_mcp_workflow,
)
from consts.const import LANGUAGE
from consts.const import DEFAULT_TENANT_ID, DEFAULT_USER_ID
from consts.exceptions import AgentRunException
from consts.model import (
    AgentInfoRequest,
    MCPConfigRequest,
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
from database.conversation_db import (
    create_conversation,
    get_latest_assistant_message_id,
    get_message,
)
from database.client import get_db_session
from database.model_management_db import get_model_records
from database.skill_db import (
    create_or_update_skill_by_skill_info,
    get_skill_by_id as get_tenant_skill_by_id,
    list_skills as list_tenant_skills,
    query_enabled_skill_instances,
    query_skills_by_ids,
)
from database.tool_db import (
    create_or_update_tool_by_tool_info,
    query_all_enabled_tool_instances,
    query_tools_by_ids,
    seed_nl2agent_builtin_tools,
    upsert_discovered_mcp_tools,
)
from database.remote_mcp_db import (
    get_mcp_record_by_id_and_tenant,
    get_mcp_records_by_tenant,
)
from services.mcp_management_service import (
    list_community_mcp_services,
    list_registry_mcp_services,
)
from services.remote_mcp_service import (
    add_container_mcp_service,
    add_mcp_service,
)
from services.tool_configuration_service import get_tool_from_remote_mcp_server
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

NL2AGENT_CHAT_INJECTION_TEXT = (
    "[[NL2AGENT_AUTO_CONTINUE]]\n"
    "The previous card action completed successfully. Re-read the authoritative "
    "Current Session state and continue naturally from the next incomplete stage. "
    "Do not ask the user to type continue."
)
NL2AGENT_CARD_RETRY_INJECTION_TEXT = (
    "[[NL2AGENT_CARD_RETRY]]\n"
    "The previous card output could not be rendered. Re-read the authoritative "
    "Current Session state and generate only the card required by the first "
    "incomplete stage. Do not claim the previous card is still valid."
)

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


def _generate_internal_agent_name(display_name: str, agent_id: int, tenant_id: str) -> str:
    """Generate a valid, tenant-unique internal identifier from a display title."""
    ascii_name = unicodedata.normalize("NFKD", display_name).encode("ascii", "ignore").decode()
    candidate = re.sub(r"[^A-Za-z0-9]+", "_", ascii_name).strip("_").lower()
    if not candidate or not re.match(r"^[A-Za-z_]", candidate):
        candidate = f"agent_{agent_id}"
    candidate = candidate[:50].rstrip("_") or f"agent_{agent_id}"
    try:
        existing_id = search_agent_id_by_agent_name(candidate, tenant_id)
    except ValueError as exc:
        if str(exc) != "agent not found":
            raise
        existing_id = None
    if existing_id not in (None, agent_id):
        suffix = f"_{agent_id}"
        candidate = f"{candidate[: 50 - len(suffix)].rstrip('_')}{suffix}"
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,49}", candidate):
        candidate = f"agent_{agent_id}"[:50]
    return candidate


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
        logger.warning(f"Failed to list models for NL2AGENT seed in tenant {tenant_id}: {exc}")
        return []

    model_ids: List[int] = []
    for record in records:
        model_type = record.get("model_type")
        if model_type not in {"llm", "chat"}:
            continue

        connect_status = ModelConnectStatusEnum.get_value(record.get("connect_status"))
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


def _ensure_nl2agent_seed_defaults(agent: Dict[str, Any], user_id: str, tenant_id: str) -> None:
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
    if desired_model_ids and _normalize_model_ids(agent.get("model_ids")) != desired_model_ids:
        update_values["model_ids"] = desired_model_ids

    if desired_model_ids and agent.get("business_logic_model_id") not in desired_model_ids:
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
        logger.warning(f"Failed to backfill NL2AGENT seed defaults for agent_id={agent_id}: {exc}")


async def _load_session_catalogs(
    tenant_id: str,
) -> tuple[Dict[str, List[Dict[str, Any]]], List[str]]:
    """Load every required catalog, distinguishing valid emptiness from failures."""
    try:
        all_tools = list_all_tools(tenant_id=tenant_id, labels=None) or []
        tool_catalog = [
            {
                "tool_id": tool.get("tool_id"),
                "name": tool.get("name") or tool.get("origin_name") or "",
                "description": (tool.get("description") or "")[:400],
                "labels": tool.get("labels") or [],
                "source": str(tool.get("source") or "").lower(),
                "category": tool.get("category") or "",
                "usage": tool.get("usage") or "",
                "params": tool.get("params") or [],
            }
            for tool in all_tools
            if str(tool.get("source") or "").lower()
            in {"local", "mcp", "langchain"}
        ]
    except Exception as exc:
        raise AgentRunException("NL2AGENT local Tool catalog is unavailable.") from exc

    try:
        tenant_skills = list_tenant_skills(tenant_id=tenant_id) or []
        skill_catalog = [
            {
                "skill_id": skill.get("skill_id"),
                "name": skill.get("name") or skill.get("skill_name") or "",
                "description": (skill.get("description") or "")[:400],
                "tags": skill.get("tags") or [],
                "config_schema": skill.get("config_schema") or {},
            }
            for skill in tenant_skills
        ]
    except Exception as exc:
        raise AgentRunException("NL2AGENT local Skill catalog is unavailable.") from exc

    try:
        registry_data = await list_registry_mcp_services(search=None, limit=30)
        registry_results = _redact_mcp_marketplace_metadata(
            registry_data.get("servers", registry_data) or []
        ) if isinstance(registry_data, dict) else []
    except Exception as exc:
        raise AgentRunException("NL2AGENT Registry MCP catalog is unavailable.") from exc

    try:
        community_data = list_community_mcp_services(search=None, limit=30)
        community_results = _redact_mcp_marketplace_metadata(
            community_data.get("items", community_data) or []
        ) if isinstance(community_data, dict) else []
    except Exception as exc:
        raise AgentRunException("NL2AGENT community MCP catalog is unavailable.") from exc

    try:
        official_skill_catalog = get_official_skills_with_status(tenant_id=tenant_id) or []
    except Exception as exc:
        raise AgentRunException("NL2AGENT official Skill catalog is unavailable.") from exc
    resource_missing_names = [
        str(item.get("skill_name") or item.get("name") or "")
        for item in official_skill_catalog
        if item.get("status") == "resource_missing"
    ]
    official_skills = [
        item for item in official_skill_catalog if item.get("status") == "installable"
    ]
    return {
        "tool_catalog": tool_catalog,
        "skill_catalog": skill_catalog,
        "registry_results": registry_results,
        "community_results": community_results,
        "official_skills": official_skills,
    }, resource_missing_names


async def start_session(user_id: str, tenant_id: str, language: str) -> Dict[str, Any]:
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
        nl2agent_agent_id = search_agent_id_by_agent_name(NL2AGENT_AGENT_NAME, tenant_id)
    except ValueError as exc:
        if str(exc) != "agent not found":
            raise
        raise AgentRunException(
            "NL2AGENT default agent is not initialized. Restart the config service first."
        ) from exc

    try:
        nl2agent_agent = search_agent_info_by_agent_id(agent_id=nl2agent_agent_id, tenant_id=tenant_id)
        if nl2agent_agent:
            _ensure_nl2agent_seed_defaults(nl2agent_agent, user_id=user_id, tenant_id=tenant_id)
    except Exception as exc:
        logger.warning(f"Failed to verify NL2AGENT prompt template link for tenant {tenant_id}: {exc}")

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
    session_catalogs, resource_missing_names = await _load_session_catalogs(tenant_id)
    draft_agent_id: Optional[int] = None
    conversation_id: Optional[int] = None
    try:
        with get_db_session() as db_session:
            created = create_agent(
                agent_payload,
                tenant_id=tenant_id,
                user_id=user_id,
                db_session=db_session,
            )
            draft_agent_id = created.get("agent_id")
            if not isinstance(draft_agent_id, int) or draft_agent_id <= 0:
                raise AgentRunException("Draft agent creation returned no agent_id.")

            conversation = create_conversation(
                conversation_title=f"NL2AGENT - {draft_name}",
                user_id=user_id,
                db_session=db_session,
            )
            conversation_id = conversation.get("conversation_id")
            if not isinstance(conversation_id, int) or conversation_id <= 0:
                raise AgentRunException("Conversation creation returned no conversation_id.")

            initialize_nl2agent_session_state(
                tenant_id,
                draft_agent_id,
                conversation_id=conversation_id,
            )
            set_nl2agent_session_catalogs(
                tenant_id,
                draft_agent_id,
                session_catalogs,
            )
    except Exception as exc:
        if draft_agent_id:
            try:
                delete_nl2agent_session_catalogs(tenant_id, draft_agent_id)
            except Exception:
                logger.exception(
                    "Failed to compensate NL2AGENT Redis initialization: tenant_id=%s draft_agent_id=%s",
                    tenant_id,
                    draft_agent_id,
                )
        if isinstance(exc, AgentRunException):
            raise
        logger.exception("Failed to initialize NL2AGENT session for tenant_id=%s", tenant_id)
        raise AgentRunException("Failed to initialize NL2AGENT session.") from exc

    if resource_missing_names:
        logger.warning(
            "Excluded resource-missing official Skills from NL2AGENT search: "
            "tenant_id=%s draft_agent_id=%s skills=%s",
            tenant_id,
            draft_agent_id,
            resource_missing_names,
        )

    return {
        "nl2agent_agent_id": nl2agent_agent_id,
        "draft_agent_id": draft_agent_id,
        "conversation_id": conversation_id,
        "draft_name": draft_name,
        # Catalogs for SDK tools
        **session_catalogs,
    }


def _validate_draft_agent_id(agent_id: int) -> None:
    if not isinstance(agent_id, int) or agent_id <= 0:
        raise AgentRunException("Invalid NL2AGENT draft agent_id.")


def _get_owned_draft(agent_id: int, tenant_id: str) -> Dict[str, Any]:
    _validate_draft_agent_id(agent_id)
    try:
        agent = search_agent_info_by_agent_id(agent_id=agent_id, tenant_id=tenant_id)
    except ValueError as exc:
        if str(exc) != "agent not found":
            raise
        raise AgentRunException("NL2AGENT draft agent not found.") from exc
    if not agent or not _is_draft_agent_name(agent.get("name") or ""):
        raise AgentRunException("NL2AGENT draft agent not found.")
    return agent


async def select_models(
    agent_id: int,
    primary_model_id: int,
    fallback_model_ids: List[int],
    tenant_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Validate and persist an ordered model selection on a draft agent."""
    _get_owned_draft(agent_id, tenant_id)
    try:
        assert_requirements_confirmed(tenant_id, agent_id)
    except Exception as exc:
        raise AgentRunException(str(exc)) from exc
    ordered_ids = [int(primary_model_id), *[int(x) for x in fallback_model_ids]]
    if len(ordered_ids) > 5 or len(set(ordered_ids)) != len(ordered_ids):
        raise AgentRunException("Select one primary model and up to four distinct fallbacks.")

    display_names = _validate_available_llm_ids(tenant_id, ordered_ids)

    update_agent(
        agent_id=agent_id,
        agent_info=AgentInfoRequest(
            business_logic_model_id=ordered_ids[0],
            model_ids=ordered_ids,
        ),
        user_id=user_id,
        version_no=0,
    )
    set_model_selection_confirmed(tenant_id, agent_id, True)
    return {
        "agent_id": agent_id,
        "primary_model_id": ordered_ids[0],
        "fallback_model_ids": ordered_ids[1:],
        "models": [{"model_id": model_id, "display_name": display_names[model_id]} for model_id in ordered_ids],
        "chat_injection_text": NL2AGENT_CHAT_INJECTION_TEXT,
    }


def _validate_available_llm_ids(
    tenant_id: str,
    model_ids: List[int],
    *,
    finalizing: bool = False,
) -> Dict[int, str]:
    """Validate IDs against the tenant's platform LLM inventory."""
    records = get_model_records(None, tenant_id) or []
    records_by_id = {int(record["model_id"]): record for record in records}
    display_names: Dict[int, str] = {}
    for model_id in model_ids:
        record = records_by_id.get(int(model_id))
        if record is None:
            reason = f"Model {model_id} does not exist in this tenant."
        elif str(record.get("model_type") or "").lower() != "llm":
            reason = f"Model {model_id} is not an LLM."
        elif ModelConnectStatusEnum.get_value(record.get("connect_status")) != ModelConnectStatusEnum.AVAILABLE.value:
            reason = f"Model {model_id} is currently unavailable."
        else:
            display_name = str(record.get("display_name") or record.get("model_name") or "").strip()
            if display_name:
                display_names[int(model_id)] = display_name
                continue
            reason = f"Model {model_id} has no display name."
        if finalizing:
            reason += " Reopen the model-selection card and choose an available LLM."
        raise AgentRunException(reason)
    return display_names


def _resolve_model_summaries(
    draft: Dict[str, Any], tenant_id: str
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Resolve persisted model IDs into display-ready summaries without raising."""
    primary_model_id = draft.get("business_logic_model_id")
    model_ids = _normalize_model_ids(draft.get("model_ids"))
    ordered_ids = list(model_ids)
    if primary_model_id:
        primary_model_id = int(primary_model_id)
        if primary_model_id not in ordered_ids:
            ordered_ids.insert(0, primary_model_id)

    records = get_model_records(None, tenant_id) or []
    records_by_id = {int(record["model_id"]): record for record in records}
    summaries: List[Dict[str, Any]] = []
    invalid_references: List[Dict[str, Any]] = []
    for model_id in ordered_ids:
        record = records_by_id.get(model_id)
        reason: Optional[str] = None
        display_name: Optional[str] = None
        if record is None:
            reason = "not_found"
        else:
            display_name = str(record.get("display_name") or record.get("model_name") or "").strip() or None
            if str(record.get("model_type") or "").lower() != "llm":
                reason = "not_llm"
            elif (
                ModelConnectStatusEnum.get_value(record.get("connect_status"))
                != ModelConnectStatusEnum.AVAILABLE.value
            ):
                reason = "unavailable"
            elif not display_name:
                reason = "name_missing"

        is_primary = model_id == primary_model_id
        summaries.append(
            {
                "model_id": model_id,
                "display_name": display_name,
                "role": "primary" if is_primary else "fallback",
                "valid": reason is None,
            }
        )
        if reason:
            invalid_references.append(
                {
                    "reference_type": "model",
                    "reference_id": model_id,
                    "reason": reason,
                }
            )

    if primary_model_id and primary_model_id not in model_ids:
        invalid_references.append(
            {
                "reference_type": "model",
                "reference_id": primary_model_id,
                "reason": "primary_not_in_runtime_models",
            }
        )
    return summaries, invalid_references


def _resolve_resource_summaries(
    tool_instances: List[Dict[str, Any]],
    skill_instances: List[Dict[str, Any]],
    tenant_id: str,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Enrich persisted resource instances and report dangling references."""
    tool_ids = [int(row["tool_id"]) for row in tool_instances]
    skill_ids = [int(row["skill_id"]) for row in skill_instances]
    tool_info_by_id = {int(row["tool_id"]): row for row in (query_tools_by_ids(tool_ids) if tool_ids else [])}
    skill_info_by_id = {
        int(row["skill_id"]): row for row in (query_skills_by_ids(skill_ids, tenant_id) if skill_ids else [])
    }

    tools: List[Dict[str, Any]] = []
    skills: List[Dict[str, Any]] = []
    invalid_references: List[Dict[str, Any]] = []
    for instance in tool_instances:
        tool_id = int(instance["tool_id"])
        info = tool_info_by_id.get(tool_id)
        name = str((info or {}).get("origin_name") or (info or {}).get("name") or "").strip()
        if not info or not name:
            invalid_references.append(
                {
                    "reference_type": "tool",
                    "reference_id": tool_id,
                    "reason": "not_found" if not info else "name_missing",
                }
            )
            continue
        source = str(info.get("source") or "").lower()
        tools.append(
            {
                **instance,
                "name": name,
                "source": source,
                "origin": "online" if source == "mcp" else "local",
            }
        )

    for instance in skill_instances:
        skill_id = int(instance["skill_id"])
        info = skill_info_by_id.get(skill_id)
        name = str((info or {}).get("name") or "").strip()
        if not info or not name:
            invalid_references.append(
                {
                    "reference_type": "skill",
                    "reference_id": skill_id,
                    "reason": "not_found" if not info else "name_missing",
                }
            )
            continue
        source = str(info.get("source") or "").lower()
        skills.append(
            {
                **instance,
                "name": name,
                "source": source,
                "origin": "online" if source == "official" else "local",
            }
        )

    return tools, skills, invalid_references


def _raise_for_invalid_resource_references(
    invalid_references: List[Dict[str, Any]],
) -> None:
    """Block publication when a persisted resource no longer resolves."""
    if not invalid_references:
        return
    references = ", ".join(
        f"{item['reference_type']} {item['reference_id']} ({item['reason']})" for item in invalid_references
    )
    raise AgentRunException(
        f"One or more selected resources are no longer valid: {references}. Reconfigure the draft before finalizing."
    )


def _recommendation_id(source: str, item: Dict[str, Any]) -> str:
    if source == "registry":
        server = item.get("server") if isinstance(item.get("server"), dict) else item
        identity = server.get("name") or server.get("id")
    else:
        identity = item.get("communityId") or item.get("community_id") or item.get("name")
    return f"{source}:{identity}"


def _redact_mcp_marketplace_metadata(value: Any, parent_key: str = "") -> Any:
    """Remove credential defaults before marketplace metadata enters Redis or API responses."""
    if isinstance(value, list):
        return [_redact_mcp_marketplace_metadata(item, parent_key) for item in value]
    if not isinstance(value, dict):
        return deepcopy(value)

    declared_secret = bool(value.get("isSecret"))
    sanitized: Dict[str, Any] = {}
    for key, item in value.items():
        key_text = str(key)
        secret_container_value = parent_key.lower() in {
            "env",
            "headers",
            "customheaders",
        } and bool(re.search(r"token|secret|password|api[_-]?key|authorization", key_text, re.I))
        if (declared_secret and key_text in {"value", "default"}) or secret_container_value:
            sanitized[key_text] = None
        else:
            sanitized[key_text] = _redact_mcp_marketplace_metadata(item, key_text)
    return sanitized


def _resolve_mcp_recommendation(
    catalogs: Dict[str, List[Dict[str, Any]]], recommendation_id: str
) -> tuple[str, Dict[str, Any]]:
    for source, key in (
        ("registry", "registry_results"),
        ("community", "community_results"),
    ):
        for item in catalogs.get(key, []):
            if _recommendation_id(source, item) == recommendation_id:
                return source, item
    raise AgentRunException("MCP recommendation is not part of this NL2AGENT session.")


def _mcp_installation_key(
    draft_agent_id: int, recommendation_id: str, option_id: str
) -> str:
    payload = f"{draft_agent_id}:{recommendation_id}:{option_id}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _mcp_record_installation_key(record: Dict[str, Any]) -> Optional[str]:
    registry_json = record.get("registry_json")
    if isinstance(registry_json, str):
        try:
            registry_json = json.loads(registry_json)
        except json.JSONDecodeError:
            return None
    if not isinstance(registry_json, dict):
        return None
    value = registry_json.get("nl2agent_installation_key")
    return str(value) if value else None


async def _install_recommended_mcp(
    agent_id: int,
    recommendation_id: str,
    option_id: str,
    config_values: Dict[str, Any],
    tenant_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Serialize one stable MCP installation across runtime workers."""
    installation_key = _mcp_installation_key(
        agent_id, recommendation_id, option_id
    )
    lock_token = acquire_mcp_installation_lock(
        tenant_id, agent_id, installation_key
    )
    if not lock_token:
        raise AgentRunException(
            "This MCP installation is already in progress. Retry after it completes."
        )
    try:
        return await _perform_recommended_mcp_install(
            agent_id,
            recommendation_id,
            option_id,
            config_values,
            tenant_id,
            user_id,
            installation_key,
        )
    finally:
        release_mcp_installation_lock(
            tenant_id,
            agent_id,
            installation_key,
            lock_token,
        )


async def _perform_recommended_mcp_install(
    agent_id: int,
    recommendation_id: str,
    option_id: str,
    config_values: Dict[str, Any],
    tenant_id: str,
    user_id: str,
    installation_key: str,
) -> Dict[str, Any]:
    """Install a server-side resolved MCP recommendation and discover its tools."""
    _get_owned_draft(agent_id, tenant_id)
    catalogs = get_nl2agent_session_catalogs(tenant_id, agent_id)
    source, raw = _resolve_mcp_recommendation(catalogs, recommendation_id)
    normalized = normalize_mcp_candidate(source, raw)
    option = next(
        (candidate for candidate in normalized.get("install_options", []) if candidate.get("option_id") == option_id),
        None,
    )
    if not option:
        raise AgentRunException("Invalid MCP installation option.")
    if not option.get("supported", True):
        raise AgentRunException(option.get("unsupported_reason") or "This MCP installation option is unsupported.")
    update_mcp_workflow(
        tenant_id,
        agent_id,
        recommendation_id,
        option_id=option_id,
        status="installing",
        installation_key=installation_key,
    )

    registry_json = raw.get("registryJson") or raw.get("registry_json")
    registry_root = registry_json if isinstance(registry_json, dict) else raw
    server = registry_root.get("server") if isinstance(registry_root.get("server"), dict) else registry_root
    name = str(server.get("name") or raw.get("name") or "recommended-mcp")[:100]
    description = str(server.get("description") or raw.get("description") or "")
    field_values = config_values.get("fields") or {}
    if not isinstance(field_values, dict):
        raise AgentRunException("MCP configuration fields must be an object.")
    resolved_values: Dict[str, Any] = {}
    for field in option.get("fields", []):
        value = field_values.get(field.get("key"))
        if value in (None, ""):
            value = field.get("default")
        if field.get("required") and value in (None, ""):
            raise AgentRunException(f"Missing required MCP configuration: {field.get('label') or field.get('name')}")
        if value not in (None, ""):
            field_type = field.get("type")
            if field_type == "json" and isinstance(value, str):
                try:
                    json.loads(value)
                except json.JSONDecodeError as exc:
                    raise AgentRunException(
                        f"Invalid JSON for MCP configuration: {field.get('label') or field.get('name')}"
                    ) from exc
            if field_type == "number":
                try:
                    float(value)
                except (TypeError, ValueError) as exc:
                    raise AgentRunException(
                        f"Invalid number for MCP configuration: {field.get('label') or field.get('name')}"
                    ) from exc
            if field_type == "url":
                parsed_field_url = urlparse(str(value))
                if (
                    parsed_field_url.scheme not in {"http", "https"}
                    or not parsed_field_url.netloc
                    or re.search(r"\{[^{}]+\}", str(value))
                ):
                    raise AgentRunException(
                        f"Invalid URL for MCP configuration: {field.get('label') or field.get('name')}"
                    )
            choices = field.get("choices") or []
            if choices and str(value) not in set(map(str, choices)):
                raise AgentRunException(
                    f"Invalid choice for MCP configuration: {field.get('label') or field.get('name')}"
                )
            resolved_values[field.get("key")] = value

    authorization_token = None
    custom_headers: Dict[str, str] = {}
    persisted_source = "mcp_registry" if source == "registry" else source
    for field in option.get("fields", []):
        value = resolved_values.get(field.get("key"))
        if value in (None, ""):
            continue
        if field.get("category") == "header":
            if str(field.get("name") or "").lower() == "authorization":
                authorization_token = str(value)
            else:
                custom_headers[str(field.get("name"))] = str(value)

    persisted_registry_json = deepcopy(raw)
    persisted_registry_json["nl2agent_installation_key"] = installation_key
    record = next(
        (
            item
            for item in get_mcp_records_by_tenant(tenant_id)
            if _mcp_record_installation_key(item) == installation_key
        ),
        None,
    )
    mcp_id = int(record["mcp_id"]) if record else None

    if option.get("type") == "remote":
        server_url = option.get("server_url_template")
        if not server_url:
            url_field = next(
                (field for field in option.get("fields", []) if field.get("name") == "server_url"),
                None,
            )
            server_url = resolved_values.get(url_field.get("key")) if url_field else None
        for field in option.get("fields", []):
            if field.get("category") == "variable":
                value = resolved_values.get(field.get("key"))
                if value not in (None, ""):
                    variable_name = str(field.get("name"))
                    server_url = str(server_url).replace("${" + variable_name + "}", str(value))
                    server_url = str(server_url).replace("{" + variable_name + "}", str(value))
        if not server_url or re.search(r"\{[^{}]+\}", str(server_url)):
            raise AgentRunException("MCP server URL contains unresolved configuration variables.")
        parsed_url = urlparse(str(server_url))
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise AgentRunException("MCP server URL must be a valid HTTP or HTTPS URL.")
        if mcp_id is None:
            mcp_id = await add_mcp_service(
                tenant_id=tenant_id,
                user_id=user_id,
                name=name,
                description=description,
                source=persisted_source,
                server_url=server_url,
                tags=raw.get("tags") or [],
                authorization_token=authorization_token,
                custom_headers=custom_headers or None,
                container_config=None,
                registry_json=persisted_registry_json,
                enabled=True,
            )
    else:
        config_json = deepcopy(raw.get("configJson") or raw.get("config_json"))
        if option_id.startswith("package-"):
            identifier = option.get("package_identifier")
            runtime = str(option.get("runtime_hint") or option.get("registry_type") or "npx").lower()
            command_map = {"npm": "npx", "npx": "npx", "pypi": "uvx", "uvx": "uvx"}
            command = command_map.get(runtime, runtime)
            if not identifier or command not in {"npx", "uvx"}:
                raise AgentRunException("Unsupported MCP package runtime.")
            env = {}
            runtime_args = []
            package_args = []
            for field in option.get("fields", []):
                value = resolved_values.get(field.get("key"))
                if value in (None, ""):
                    continue
                category = field.get("category")
                if category == "environment":
                    env[str(field.get("name"))] = str(value)
                elif category in {"runtime_argument", "package_argument"}:
                    rendered = str(value)
                    if field.get("argument_type") == "named" and field.get("argument_name"):
                        rendered = f"{field.get('argument_name')}={rendered}"
                    (runtime_args if category == "runtime_argument" else package_args).append(rendered)
            args = runtime_args
            args.append(identifier)
            args.extend(package_args)
            config_json = {"mcpServers": {name: {"command": command, "args": args, "env": env}}}
        elif isinstance(config_json, dict):
            server_configs = config_json.get("mcpServers")
            target_config = (
                next(
                    (server_config for server_config in server_configs.values() if isinstance(server_config, dict)),
                    None,
                )
                if isinstance(server_configs, dict)
                else None
            )
            if target_config is not None:
                environment = target_config.setdefault("env", {})
                if not isinstance(environment, dict):
                    raise AgentRunException("MCP container environment configuration must be an object.")
                for field in option.get("fields", []):
                    if field.get("category") != "environment":
                        continue
                    value = resolved_values.get(field.get("key"))
                    if value not in (None, ""):
                        environment[str(field.get("name"))] = str(value)
        config_field = next(
            (field for field in option.get("fields", []) if field.get("name") == "config_json"),
            None,
        )
        if not isinstance(config_json, dict) and config_field:
            submitted_config = resolved_values.get(config_field.get("key"))
            try:
                config_json = json.loads(submitted_config) if isinstance(submitted_config, str) else submitted_config
            except json.JSONDecodeError as exc:
                raise AgentRunException("MCP container configuration must be valid JSON.") from exc
        port_field = next(
            (field for field in option.get("fields", []) if field.get("name") == "port"),
            None,
        )
        port = resolved_values.get(port_field.get("key")) if port_field else None
        try:
            port_number = int(port)
        except (TypeError, ValueError) as exc:
            raise AgentRunException("MCP container port must be an integer.") from exc
        if not 1 <= port_number <= 65535:
            raise AgentRunException("MCP container port must be between 1 and 65535.")
        if not isinstance(config_json, dict):
            raise AgentRunException("This MCP requires container configuration and a port.")
        if mcp_id is None:
            container_result = await add_container_mcp_service(
                tenant_id=tenant_id,
                user_id=user_id,
                name=name,
                description=description,
                source=persisted_source,
                tags=raw.get("tags") or [],
                authorization_token=authorization_token,
                registry_json=persisted_registry_json,
                port=port_number,
                mcp_config=MCPConfigRequest(**config_json),
            )
            mcp_id = int(container_result["mcp_id"])

    record = get_mcp_record_by_id_and_tenant(
        mcp_id=int(mcp_id), tenant_id=tenant_id
    ) if mcp_id is not None else None
    if not record:
        raise AgentRunException("Installed MCP record could not be resolved.")
    mcp_id = int(record["mcp_id"])
    try:
        discovered = await get_tool_from_remote_mcp_server(
            mcp_server_name=name,
            remote_mcp_server=record.get("mcp_server"),
            tenant_id=tenant_id,
            authorization_token=authorization_token,
            custom_headers=custom_headers or None,
        )
        tools = upsert_discovered_mcp_tools(tenant_id, user_id, discovered)
    except Exception as exc:
        update_mcp_workflow(
            tenant_id,
            agent_id,
            recommendation_id,
            option_id=option_id,
            status="failed",
            installation_key=installation_key,
            mcp_id=mcp_id,
            error="MCP tool discovery failed. Retry to resume discovery.",
        )
        raise AgentRunException("MCP tool discovery failed. Retry installation.") from exc
    update_mcp_workflow(
        tenant_id,
        agent_id,
        recommendation_id,
        option_id=option_id,
        status="connected",
        installation_key=installation_key,
        mcp_id=mcp_id,
        discovered_tool_ids=[int(tool["tool_id"]) for tool in tools],
        bound_tool_ids=[],
        error=None,
    )
    catalog_key = "registry_results" if source == "registry" else "community_results"

    def remove_installed_recommendation(
        current: Dict[str, List[Dict[str, Any]]],
    ) -> None:
        current[catalog_key] = [
            item for item in current.get(catalog_key, []) if _recommendation_id(source, item) != recommendation_id
        ]

    mutate_nl2agent_session_catalogs(tenant_id, agent_id, remove_installed_recommendation)
    return {
        "agent_id": agent_id,
        "mcp_id": mcp_id,
        "status": "connected",
        "tools": [
            {
                "tool_id": t["tool_id"],
                "name": t["name"],
                "description": t.get("description"),
            }
            for t in tools
        ],
    }


async def install_recommended_mcp(
    agent_id: int,
    recommendation_id: str,
    option_id: str,
    config_values: Dict[str, Any],
    tenant_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Install an MCP and persist redacted success or failure state."""
    try:
        return await _install_recommended_mcp(
            agent_id,
            recommendation_id,
            option_id,
            config_values,
            tenant_id,
            user_id,
        )
    except Exception as exc:
        try:
            update_mcp_workflow(
                tenant_id,
                agent_id,
                recommendation_id,
                option_id=option_id,
                status="failed",
                installation_key=_mcp_installation_key(
                    agent_id, recommendation_id, option_id
                ),
                error="MCP installation failed. Review the option configuration and retry.",
            )
        except Exception:
            logger.exception("Failed to persist NL2AGENT MCP failure state")
        if isinstance(exc, AgentRunException):
            raise
        raise AgentRunException("MCP installation failed during connection or tool discovery.") from exc


async def bind_mcp_tools(
    agent_id: int,
    mcp_id: int,
    tool_ids: List[int],
    tenant_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Bind user-selected tools belonging to an installed MCP."""
    _get_owned_draft(agent_id, tenant_id)
    if not tool_ids:
        raise AgentRunException("Select at least one discovered MCP tool to bind.")
    record = get_mcp_record_by_id_and_tenant(mcp_id=mcp_id, tenant_id=tenant_id)
    if not record:
        raise AgentRunException("Installed MCP not found.")
    rows = query_tools_by_ids(tool_ids) if tool_ids else []
    valid = {
        int(row["tool_id"]): row
        for row in rows
        if row.get("author") == tenant_id and row.get("source") == "mcp" and row.get("usage") == record.get("mcp_name")
    }
    if set(map(int, tool_ids)) != set(valid):
        raise AgentRunException("One or more tools do not belong to the selected MCP.")
    for tool_id in valid:
        create_or_update_tool_by_tool_info(
            ToolInstanceInfoRequest(
                tool_id=tool_id,
                agent_id=agent_id,
                params={},
                enabled=True,
                version_no=0,
            ),
            tenant_id=tenant_id,
            user_id=user_id,
            version_no=0,
        )
    recommendation_id, _ = find_mcp_workflow_by_id(tenant_id, agent_id, mcp_id)
    update_mcp_workflow(
        tenant_id,
        agent_id,
        recommendation_id,
        status="tools_bound",
        bound_tool_ids=sorted(valid),
    )
    return {"agent_id": agent_id, "mcp_id": mcp_id, "bound_tool_ids": sorted(valid)}


async def skip_mcp_tool_binding(
    agent_id: int,
    mcp_id: int,
    tenant_id: str,
) -> Dict[str, Any]:
    """Explicitly resolve an installed MCP without binding discovered tools."""
    _get_owned_draft(agent_id, tenant_id)
    if not get_mcp_record_by_id_and_tenant(mcp_id=mcp_id, tenant_id=tenant_id):
        raise AgentRunException("Installed MCP not found.")
    recommendation_id, workflow = find_mcp_workflow_by_id(tenant_id, agent_id, mcp_id)
    if workflow.get("status") != "connected":
        raise AgentRunException("MCP tool binding is already resolved.")
    update_mcp_workflow(
        tenant_id,
        agent_id,
        recommendation_id,
        status="binding_skipped",
        bound_tool_ids=[],
    )
    return {"agent_id": agent_id, "mcp_id": mcp_id, "status": "binding_skipped"}


async def apply_local_resources_batch(
    agent_id: int,
    recommendation_batch_id: str,
    tool_ids: List[int],
    skill_ids: List[int],
    tenant_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Bulk-bind local tools and skills to the draft agent.

    Tools: creates/updates ToolInstance rows with enabled=True.
    Skills: binds existing tenant skills as SkillInstances. Official online
    skills are installed through the separate web-skill workflow.

    Returns counts of bound items.
    """
    _get_owned_draft(agent_id, tenant_id)

    # Validate the selection against the card that the frontend actually rendered.
    session_state = get_nl2agent_session_state(tenant_id, agent_id)
    batch = session_state["recommendation_batches"].get(recommendation_batch_id)
    if batch is None:
        raise AgentRunException("The local resource recommendation card was not registered.")
    if not set(map(int, tool_ids or [])).issubset(set(batch.get("tool_ids", []))) or not set(
        map(int, skill_ids or [])
    ).issubset(set(batch.get("skill_ids", []))):
        raise AgentRunException("Selected resources do not belong to this recommendation batch.")

    selected_tool_ids = list(dict.fromkeys(map(int, tool_ids or [])))
    selected_skill_ids = list(dict.fromkeys(map(int, skill_ids or [])))

    tool_records = query_tools_by_ids(selected_tool_ids) if selected_tool_ids else []
    tools_by_id = {int(item["tool_id"]): item for item in tool_records}
    missing_tool_ids = [tool_id for tool_id in selected_tool_ids if tool_id not in tools_by_id]
    if missing_tool_ids:
        raise AgentRunException(
            "Local resource binding failed because tools no longer exist: "
            + ", ".join(map(str, missing_tool_ids))
        )

    missing_skill_ids = [
        skill_id
        for skill_id in selected_skill_ids
        if not get_tenant_skill_by_id(skill_id, tenant_id)
    ]
    if missing_skill_ids:
        raise AgentRunException(
            "Local resource binding failed because tenant skills no longer exist: "
            + ", ".join(map(str, missing_skill_ids))
        )

    try:
        with get_db_session() as db_session:
            for tool_id in selected_tool_ids:
                params = tools_by_id[tool_id].get("params") or {}
                if not isinstance(params, dict):
                    params = {}
                create_or_update_tool_by_tool_info(
                    tool_info=ToolInstanceInfoRequest(
                        tool_id=tool_id,
                        agent_id=agent_id,
                        params=params,
                        enabled=True,
                        version_no=0,
                    ),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    version_no=0,
                    db_session=db_session,
                )
            for skill_id in selected_skill_ids:
                create_or_update_skill_by_skill_info(
                    skill_info=SkillInstanceInfoRequest(
                        skill_id=skill_id,
                        agent_id=agent_id,
                        enabled=True,
                        version_no=0,
                    ),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    version_no=0,
                    db_session=db_session,
                )
    except Exception as exc:
        logger.exception(
            "Failed to atomically bind local resources: tenant_id=%s draft_agent_id=%s batch_id=%s",
            tenant_id,
            agent_id,
            recommendation_batch_id,
        )
        raise AgentRunException("Local resource binding failed; no resources were applied.") from exc

    try:
        resolve_recommendation_batch(
            tenant_id,
            agent_id,
            recommendation_batch_id,
            "applied",
            selected_tool_ids,
            selected_skill_ids,
        )
    except Exception as exc:
        logger.exception(
            "Local resources were committed but workflow reconciliation failed: tenant_id=%s "
            "draft_agent_id=%s batch_id=%s",
            tenant_id,
            agent_id,
            recommendation_batch_id,
        )
        raise AgentRunException(
            "Local resources were saved, but workflow state could not be reconciled. Retry Apply All."
        ) from exc
    return {
        "recommendation_batch_id": recommendation_batch_id,
        "status": "applied",
        "bound_tool_count": len(selected_tool_ids),
        "bound_skill_count": len(selected_skill_ids),
        "tool_ids": selected_tool_ids,
        "skill_ids": selected_skill_ids,
        "chat_injection_text": NL2AGENT_CHAT_INJECTION_TEXT,
    }


async def register_local_resource_recommendations(
    agent_id: int,
    recommendation_batch_id: str,
    tool_ids: List[int],
    skill_ids: List[int],
    tenant_id: str,
) -> Dict[str, Any]:
    """Record that the frontend rendered a local-resource card."""
    _get_owned_draft(agent_id, tenant_id)
    batch = register_recommendation_batch(tenant_id, agent_id, recommendation_batch_id, tool_ids, skill_ids)
    return {"recommendation_batch_id": recommendation_batch_id, **batch}


async def skip_local_resource_recommendations(
    agent_id: int,
    recommendation_batch_id: str,
    tenant_id: str,
) -> Dict[str, Any]:
    """Record the user's explicit decision to continue without a shown batch."""
    _get_owned_draft(agent_id, tenant_id)
    batch = resolve_recommendation_batch(tenant_id, agent_id, recommendation_batch_id, "skipped")
    return {
        "recommendation_batch_id": recommendation_batch_id,
        **batch,
        "chat_injection_text": NL2AGENT_CHAT_INJECTION_TEXT,
    }


async def register_online_resource_recommendations(
    agent_id: int,
    recommendation_batch_id: str,
    resource_type: str,
    item_keys: List[str],
    tenant_id: str,
) -> Dict[str, Any]:
    """Record one MCP or web-Skill result batch rendered by the frontend."""
    _get_owned_draft(agent_id, tenant_id)
    batch = register_online_recommendation_batch(
        tenant_id,
        agent_id,
        recommendation_batch_id,
        resource_type,
        item_keys,
    )
    return {"recommendation_batch_id": recommendation_batch_id, **batch}


async def report_card_delivery(
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
    _get_owned_draft(agent_id, tenant_id)
    state = get_nl2agent_session_state(tenant_id, agent_id)
    conversation_id = int(state["conversation_id"])
    message = get_message(message_id, user_id=user_id)
    latest_message_id = get_latest_assistant_message_id(conversation_id, user_id=user_id)
    if (
        not message
        or int(message.get("conversation_id") or 0) != conversation_id
        or message.get("message_role") != "assistant"
        or message.get("status") != "completed"
        or latest_message_id != message_id
    ):
        raise AgentRunException("The card delivery receipt is stale for the current NL2AGENT workflow stage.")
    summary = get_workflow_summary(tenant_id, agent_id)
    if card_type not in summary["expected_card_types"]:
        existing = state.get("card_delivery", {}).get(card_type) or {}
        if not (
            existing.get("message_id") == message_id
            and existing.get("status") == status
            and existing.get("card_key") == card_key
        ):
            raise AgentRunException("The card delivery receipt is stale for the current NL2AGENT workflow stage.")
    delivery = record_card_delivery(
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
        response["chat_injection_text"] = NL2AGENT_CARD_RETRY_INJECTION_TEXT
    return response


async def confirm_online_resource_configuration(agent_id: int, tenant_id: str) -> Dict[str, Any]:
    """Persist the user's global decision to finish online configuration."""
    _get_owned_draft(agent_id, tenant_id)
    completed_batch_ids = complete_online_configuration_state(tenant_id, agent_id)
    return {
        "agent_id": agent_id,
        "online_configuration_confirmed": True,
        "completed_batch_ids": completed_batch_ids,
        "chat_injection_text": NL2AGENT_CHAT_INJECTION_TEXT,
    }


async def register_requirements_review(agent_id: int, summary: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
    """Register the rendered five-field requirements summary for one draft."""
    _get_owned_draft(agent_id, tenant_id)
    review = register_requirements_summary(tenant_id, agent_id, summary)
    return {
        "agent_id": agent_id,
        "status": review["status"],
        "summary": review["summary"],
        "fingerprint": review["fingerprint"],
        "is_current": review["is_current"],
    }


def process_requirements_revision_text(
    runner_agent_id: Optional[int],
    draft_agent_id: int,
    tenant_id: str,
    text: str,
) -> Dict[str, Any]:
    """Process textual requirement revisions only for the seeded NL2AGENT runner."""
    runner = search_agent_info_by_agent_id(agent_id=runner_agent_id, tenant_id=tenant_id)
    if not runner or runner.get("name") != NL2AGENT_AGENT_NAME:
        return {"intent": "not_applicable"}
    _get_owned_draft(draft_agent_id, tenant_id)
    return apply_requirements_revision_text(tenant_id, draft_agent_id, text)


async def confirm_requirements_review(agent_id: int, fingerprint: str, tenant_id: str) -> Dict[str, Any]:
    """Confirm the current registered requirements revision."""
    _get_owned_draft(agent_id, tenant_id)
    review = confirm_requirements_summary(tenant_id, agent_id, fingerprint)
    return {
        "agent_id": agent_id,
        "status": review["status"],
        "fingerprint": review["fingerprint"],
        "chat_injection_text": NL2AGENT_CHAT_INJECTION_TEXT,
    }


async def get_session_state(agent_id: int, tenant_id: str) -> Dict[str, Any]:
    """Return authoritative draft models, resource bindings, and review state."""
    draft = _get_owned_draft(agent_id, tenant_id)
    tool_instances = query_all_enabled_tool_instances(agent_id, tenant_id, version_no=0) or []
    skill_instances = query_enabled_skill_instances(agent_id, tenant_id, version_no=0) or []
    models, invalid_model_references = _resolve_model_summaries(draft, tenant_id)
    tools, skills, invalid_resource_references = _resolve_resource_summaries(
        tool_instances, skill_instances, tenant_id
    )
    workflow_state = get_nl2agent_session_state(tenant_id, agent_id)
    workflow_summary = get_workflow_summary(tenant_id, agent_id)
    for workflow in workflow_state.get("mcp_workflows", {}).values():
        discovered_ids = [int(tool_id) for tool_id in workflow.get("discovered_tool_ids", [])]
        discovered_rows = query_tools_by_ids(discovered_ids) if discovered_ids else []
        discovered_by_id = {int(row["tool_id"]): row for row in discovered_rows}
        workflow["discovered_tools"] = [
            {
                "tool_id": tool_id,
                "name": discovered_by_id.get(tool_id, {}).get("name") or str(tool_id),
                "description": discovered_by_id.get(tool_id, {}).get("description") or "",
            }
            for tool_id in discovered_ids
        ]
    return {
        "agent_id": agent_id,
        "schema_version": workflow_state["schema_version"],
        "revision": workflow_state["revision"],
        "current_stage": workflow_summary["current_stage"],
        "expected_card_types": workflow_summary["expected_card_types"],
        "allowed_actions": workflow_summary["allowed_actions"],
        "display_name": draft.get("display_name"),
        "internal_name": _generate_internal_agent_name(draft.get("display_name") or "", agent_id, tenant_id),
        "business_logic_model_id": draft.get("business_logic_model_id"),
        "model_ids": _normalize_model_ids(draft.get("model_ids")),
        "models": models,
        "tools": tools,
        "skills": skills,
        "invalid_references": invalid_model_references + invalid_resource_references,
        "identity_confirmed": workflow_state.get("identity_confirmed", False),
        "resource_review": workflow_state,
    }


async def save_agent_identity(
    agent_id: int,
    display_name: str,
    tenant_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Persist an explicitly confirmed display name without publishing the draft."""
    _get_owned_draft(agent_id, tenant_id)
    normalized_display_name = display_name.strip()
    if not normalized_display_name:
        raise AgentRunException("Agent display name cannot be empty.")
    try:
        update_agent(
            agent_id=agent_id,
            agent_info=AgentInfoRequest(display_name=normalized_display_name),
            user_id=user_id,
            version_no=0,
        )
        confirm_agent_identity(tenant_id, agent_id)
    except AgentRunException:
        raise
    except Exception as exc:
        logger.error(
            "Failed to save NL2AGENT identity: tenant_id=%s draft_agent_id=%s",
            tenant_id,
            agent_id,
            exc_info=True,
        )
        raise AgentRunException("Failed to save the agent display name.") from exc
    return {
        "agent_id": agent_id,
        "display_name": normalized_display_name,
        "internal_name": _generate_internal_agent_name(normalized_display_name, agent_id, tenant_id),
        "identity_confirmed": True,
        "chat_injection_text": NL2AGENT_CHAT_INJECTION_TEXT,
    }


def _refresh_official_skill_catalog_after_install(
    agent_id: int,
    tenant_id: str,
    *,
    skill_id: Optional[int],
    skill_name: Optional[str],
    installed_ids: Optional[List[int]] = None,
) -> None:
    """Remove an installed Skill from one draft's Redis recommendation catalog."""
    removed_ids = {int(value) for value in [skill_id, *(installed_ids or [])] if value}
    normalized_name = unicodedata.normalize("NFKC", str(skill_name or "")).casefold().strip()

    def is_installed_recommendation(item: Dict[str, Any]) -> bool:
        item_id = item.get("skill_id")
        try:
            matches_id = item_id is not None and int(item_id) in removed_ids
        except (TypeError, ValueError):
            matches_id = False
        item_name = (
            unicodedata.normalize("NFKC", str(item.get("skill_name") or item.get("name") or "")).casefold().strip()
        )
        return matches_id or bool(normalized_name and item_name == normalized_name)

    def remove_installed_skill(
        catalogs: Dict[str, List[Dict[str, Any]]],
    ) -> None:
        catalogs["official_skills"] = [
            item for item in catalogs.get("official_skills", []) if not is_installed_recommendation(item)
        ]

    mutate_nl2agent_session_catalogs(tenant_id, agent_id, remove_installed_skill)


def _require_installable_official_skill_recommendation(
    agent_id: int,
    tenant_id: str,
    *,
    skill_id: Optional[int],
    skill_name: Optional[str],
) -> Dict[str, Any]:
    """Resolve an install request from the draft's trusted Skill catalog."""
    catalogs = get_nl2agent_session_catalogs(tenant_id, agent_id)
    normalized_name = unicodedata.normalize("NFKC", str(skill_name or "")).casefold().strip()
    for item in catalogs.get("official_skills", []):
        item_name = (
            unicodedata.normalize("NFKC", str(item.get("skill_name") or item.get("name") or "")).casefold().strip()
        )
        try:
            matches_id = bool(skill_id and int(item.get("skill_id")) == int(skill_id))
        except (TypeError, ValueError):
            matches_id = False
        if not matches_id and not (normalized_name and item_name == normalized_name):
            continue
        if item.get("status") != "installable":
            break
        return item
    raise AgentRunException("The requested Skill is not available for installation in this NL2AGENT session.")


async def install_web_skill(
    agent_id: int,
    skill_id: Optional[int],
    tenant_id: str,
    user_id: str,
    skill_name: Optional[str] = None,
    locale: Optional[str] = None,
) -> Dict[str, Any]:
    """Install a single official/web skill into the tenant."""
    _get_owned_draft(agent_id, tenant_id)
    _require_installable_official_skill_recommendation(
        agent_id,
        tenant_id,
        skill_id=skill_id,
        skill_name=skill_name,
    )
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

        result = {
            "skill_id": skill_id or 0,
            "skill_name": skill_name,
            "installed": bool(installed_names),
            "installed_ids": [],
            "installed_names": installed_names,
        }
        if installed_names:
            try:
                _refresh_official_skill_catalog_after_install(
                    agent_id,
                    tenant_id,
                    skill_id=skill_id,
                    skill_name=skill_name,
                )
            except Exception:
                logger.exception(
                    "Failed to refresh NL2AGENT Skill catalog after installation: "
                    "tenant_id=%s draft_agent_id=%s skill_name=%s",
                    tenant_id,
                    agent_id,
                    skill_name,
                )
        return result

    if not skill_id or skill_id <= 0:
        raise AgentRunException("Either skill_name or a positive skill_id is required.")

    try:
        installed = install_skills_for_tenant(skill_ids=[skill_id], tenant_id=tenant_id, user_id=user_id)
    except Exception as exc:
        logger.error(f"Failed to install web skill {skill_id}: {exc}")
        raise AgentRunException(f"Failed to install skill {skill_id}.") from exc

    result = {
        "skill_id": skill_id,
        "installed": bool(installed),
        "installed_ids": installed,
    }
    if installed:
        try:
            _refresh_official_skill_catalog_after_install(
                agent_id,
                tenant_id,
                skill_id=skill_id,
                skill_name=None,
                installed_ids=installed,
            )
        except Exception:
            logger.exception(
                "Failed to refresh NL2AGENT Skill catalog after installation: "
                "tenant_id=%s draft_agent_id=%s skill_id=%s",
                tenant_id,
                agent_id,
                skill_id,
            )
    return result


async def finalize_agent(
    agent_id: int,
    user_id: str,
    tenant_id: str,
    description: Optional[str] = None,
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
) -> Dict[str, Any]:
    """Publish a draft using proposal text and authoritative persisted configuration."""
    _validate_draft_agent_id(agent_id)

    # Persisted model selection is authoritative. The LLM-generated proposal
    # must never invent or replace model IDs during publication.
    current_draft = _get_owned_draft(agent_id, tenant_id)
    stored_primary_model_id = current_draft.get("business_logic_model_id")
    stored_model_ids = _normalize_model_ids(current_draft.get("model_ids"))
    if not stored_primary_model_id or stored_primary_model_id not in stored_model_ids:
        raise AgentRunException("Select a primary LLM before finalizing the agent.")
    _validate_available_llm_ids(
        tenant_id,
        stored_model_ids,
        finalizing=True,
    )
    try:
        assert_requirements_confirmed(tenant_id, agent_id)
    except Exception as exc:
        raise AgentRunException(str(exc)) from exc
    try:
        assert_resource_review_complete(tenant_id, agent_id)
    except Exception as exc:
        raise AgentRunException(str(exc)) from exc
    try:
        assert_mcp_workflows_resolved(tenant_id, agent_id)
    except Exception as exc:
        raise AgentRunException(str(exc)) from exc
    try:
        assert_online_configuration_complete(tenant_id, agent_id)
    except Exception as exc:
        raise AgentRunException(str(exc)) from exc
    try:
        assert_identity_confirmed(tenant_id, agent_id)
    except Exception as exc:
        raise AgentRunException(str(exc)) from exc
    business_logic_model_id = int(stored_primary_model_id)
    model_ids = stored_model_ids

    # Build the agent update payload from whatever the skill provided.
    agent_update: Dict[str, Any] = {}
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
        raise AgentRunException("The final proposal is incomplete: " + ", ".join(missing_proposal_fields))

    # Resolve persisted resources before mutating the draft so dangling catalog
    # references cannot leave a partially finalized agent.
    persisted_tools = query_all_enabled_tool_instances(agent_id, tenant_id, version_no=0) or []
    persisted_skills = query_enabled_skill_instances(agent_id, tenant_id, version_no=0) or []
    _, _, invalid_resource_references = _resolve_resource_summaries(persisted_tools, persisted_skills, tenant_id)
    _raise_for_invalid_resource_references(invalid_resource_references)

    final_display_name = str(current_draft.get("display_name") or "").strip()[:50]
    if not final_display_name:
        raise AgentRunException("The persisted agent display name is missing.")
    agent_update["display_name"] = final_display_name
    # The LLM is never authoritative for the internal variable identifier.
    agent_update["name"] = _generate_internal_agent_name(final_display_name, agent_id, tenant_id)
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

    return {
        "agent_id": agent_id,
        "status": "draft_ready",
        "name": agent_update["name"],
        "display_name": final_display_name,
        "tool_ids": [row["tool_id"] for row in persisted_tools],
        "skill_ids": [row["skill_id"] for row in persisted_skills],
    }


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
            _ensure_nl2agent_seed_defaults(agent, user_id=user_id, tenant_id=tenant_id)
            logger.info(f"NL2AGENT default agent already exists (agent_id={existing_id})")
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
            logger.error(f"Failed to bind builtin tool {tool_id} to NL2AGENT agent: {exc}")

    logger.info(
        f"Seeded NL2AGENT default agent (agent_id={agent_id}) with "
        f"{len(tool_ids)} builtin tools for tenant {tenant_id}"
    )
    return agent_id
    (find_mcp_workflow_by_id,)
