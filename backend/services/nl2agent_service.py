"""NL2AGENT conversational agent generator service.

Provides the business logic for the NL2AGENT default agent: a conversational agent
that helps users build custom agents via multi-turn chat. This service backs the
NL2AGENT builtin tools (search/recommend/apply/install/finalize).

The service is intentionally thin: it orchestrates existing services
(prompt_service, tool_configuration_service, skill_service, mcp_management_service)
rather than reimplementing them.
"""

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from consts.const import LANGUAGE
from consts.const import DEFAULT_TENANT_ID, DEFAULT_USER_ID
from consts.exceptions import AgentRunException, AppException
from consts.error_code import ErrorCode
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
from services.prompt_service import generate_and_save_system_prompt_impl
from services.prompt_template_service import (
    SYSTEM_PROMPT_TEMPLATE_ID,
    SYSTEM_PROMPT_TEMPLATE_NAME,
)
from services.skill_service import (
    get_official_skills_with_status,
    install_skills_for_tenant,
    install_skills_from_zip_for_tenant,
)
from services.tool_configuration_service import list_all_tools
from utils.llm_utils import call_llm_for_system_prompt
from utils.prompt_template_utils import get_nl2agent_seed_config

logger = logging.getLogger(__name__)

# Reserved name of the NL2AGENT default agent shipped with the product.
NL2AGENT_AGENT_NAME = "nl2agent"

# Prefix for draft agent names created during NL2AGENT sessions.
DRAFT_AGENT_NAME_PREFIX = "draft_"

# Maximum number of items to send to the LLM scorer per category.
_SCORER_MAX_CANDIDATES = 60

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
        "prompt_template_id": SYSTEM_PROMPT_TEMPLATE_ID,
        "prompt_template_name": SYSTEM_PROMPT_TEMPLATE_NAME,
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
    `draft_<uuid8>` convention so it can be hidden from the main agent list.

    Returns explicit IDs:
        - ``nl2agent_agent_id``: the seeded default NL2AGENT agent that runs the chat.
        - ``draft_agent_id``: the target draft agent being built.
        - ``conversation_id``: the conversation created for this session.
        - ``draft_name``: the draft agent's name (for display/debug).
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

    return {
        "nl2agent_agent_id": nl2agent_agent_id,
        "draft_agent_id": draft_agent_id,
        "conversation_id": conversation.get("conversation_id"),
        "draft_name": draft_name,
    }


def _compact_tool_for_scoring(tool: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "tool_id": tool.get("tool_id"),
        "name": tool.get("name") or tool.get("origin_name") or "",
        "description": (tool.get("description") or "")[:400],
        "labels": tool.get("labels") or [],
        "source": tool.get("source") or "",
        "category": tool.get("category") or "",
    }


def _compact_skill_for_scoring(skill: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "skill_id": skill.get("skill_id"),
        "name": skill.get("name") or skill.get("skill_name") or "",
        "description": (skill.get("description") or skill.get("skill_description") or "")[:400],
        "tags": skill.get("tags") or skill.get("skill_tags") or [],
    }


def _strip_internal_scoring_fields(candidate: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in candidate.items()
        if not key.startswith("_")
    }


def _unranked_candidates(
    candidates: List[Dict[str, Any]],
    top_n: int,
    kind: str,
) -> List[Dict[str, Any]]:
    return [
        {
            **_strip_internal_scoring_fields(candidate),
            "score": 0,
            "reason": (
                f"LLM scoring unavailable; shown as an unranked {kind} candidate."
            ),
        }
        for candidate in candidates[:top_n]
    ]


def _validate_draft_agent_id(agent_id: int) -> None:
    if not isinstance(agent_id, int) or agent_id <= 0:
        raise AgentRunException("Invalid NL2AGENT draft agent_id.")


def _normalize_tool_instance_params(params: Any) -> Dict[str, Any]:
    """Return persisted tool-instance params, not catalog parameter schemas."""
    if isinstance(params, dict):
        return params
    return {}


def _score_candidates_with_llm(
    model_id: int,
    query: str,
    candidates: List[Dict[str, Any]],
    id_field: str,
    tenant_id: Optional[str],
    top_n: int,
    kind: str,
) -> List[Dict[str, Any]]:
    """Score a list of candidates against the user query using an LLM.

    Returns the top-N candidates with their score and a one-line reason.
    """
    if not candidates:
        return []

    # Cap the number of candidates to keep the prompt bounded.
    pruned = candidates[:_SCORER_MAX_CANDIDATES]

    system_prompt = (
        "You are a tool/skill recommender for an agent-building assistant. "
        f"Given the user's intent and a list of {kind}s, score each {kind}'s "
        "relevance from 0 to 10 and give a one-line reason. "
        "Respond with STRICT JSON: an array of objects with fields "
        f"`{id_field}`, `score` (integer 0-10), and `reason` (string). "
        "Do not include any text outside the JSON array."
    )

    user_payload = {
        "user_intent": query,
        kind + "s": pruned,
    }
    user_prompt = json.dumps(user_payload, ensure_ascii=False)

    try:
        raw = call_llm_for_system_prompt(
            model_id=model_id,
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.warning(
            f"LLM scoring call failed for {kind}s; returning unranked candidates: {exc}"
        )
        return _unranked_candidates(pruned, top_n, kind)

    scored = _parse_scored_json(raw, id_field)
    if not scored:
        logger.warning(
            f"LLM scoring returned no usable {kind} rankings; returning unranked candidates."
        )
        return _unranked_candidates(pruned, top_n, kind)

    id_to_candidate = {c.get(id_field): c for c in pruned}
    enriched: List[Dict[str, Any]] = []
    for item in scored:
        cid = item.get(id_field)
        candidate = id_to_candidate.get(cid)
        if not candidate:
            continue
        enriched.append({
            **candidate,
            "score": item.get("score", 0),
            "reason": item.get("reason", ""),
        })

    if not enriched:
        logger.warning(
            f"LLM scoring returned no matching {kind} IDs; returning unranked candidates."
        )
        return _unranked_candidates(pruned, top_n, kind)

    enriched.sort(key=lambda x: x.get("score", 0), reverse=True)
    return enriched[:top_n]


def _parse_scored_json(
    raw: str, id_field: str
) -> List[Dict[str, Any]]:
    """Parse the LLM's JSON scoring response, tolerating code fences."""
    if not raw:
        return []
    text = raw.strip()
    # Strip ```json ... ``` fences if present.
    if text.startswith("```"):
        text = text.split("```", 2)
        if len(text) >= 2:
            text = text[1]
            if text.lower().startswith("json"):
                text = text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to find the first '[' ... ']' span.
        start = raw.find("[")
        end = raw.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                logger.warning("Failed to parse LLM scoring response as JSON.")
                return []
        else:
            logger.warning("LLM scoring response had no JSON array.")
            return []

    if not isinstance(data, list):
        return []

    result = []
    for item in data:
        if isinstance(item, dict) and item.get(id_field) is not None:
            result.append(item)
    return result


async def recommend_local_resources(
    query: str,
    agent_id: int,
    tenant_id: str,
    model_id: int,
    top_n: int = 5,
) -> Dict[str, Any]:
    """Recommend local tools (SDK + locally-installed MCP + LangChain) and local skills.

    Returns ``{"tools": [...], "skills": [...]}`` with each item carrying
    ``score`` and ``reason`` from the LLM.
    """
    if not query:
        return {"tools": [], "skills": []}

    # Local tool catalog: list_all_tools returns LOCAL + MCP + LANGCHAIN + BUILTIN
    # tools already installed/registered for this tenant. Filter to the first three
    # so NL2AGENT builtin tools are not recommended back to the user.
    try:
        all_tools = await list_all_tools(tenant_id=tenant_id, labels=None)
    except Exception as exc:
        logger.error(f"Failed to list tools for NL2AGENT recommendation: {exc}")
        raise AgentRunException("Failed to list local tools.") from exc

    allowed_sources = {"local", "mcp", "langchain"}
    all_tools = [
        t for t in all_tools
        if str(t.get("source") or "").lower() in allowed_sources
    ]

    compact_tools = [_compact_tool_for_scoring(t) for t in all_tools]
    scored_tools = _score_candidates_with_llm(
        model_id=model_id,
        query=query,
        candidates=compact_tools,
        id_field="tool_id",
        tenant_id=tenant_id,
        top_n=top_n,
        kind="tool",
    )

    # Local skills: skills already installed for this tenant.
    try:
        tenant_skills = list_tenant_skills(tenant_id=tenant_id) or []
    except Exception as exc:
        logger.error(f"Failed to list tenant skills for NL2AGENT: {exc}")
        raise AgentRunException("Failed to list local skills.") from exc

    compact_skills = [_compact_skill_for_scoring(s) for s in tenant_skills]
    scored_skills = _score_candidates_with_llm(
        model_id=model_id,
        query=query,
        candidates=compact_skills,
        id_field="skill_id",
        tenant_id=tenant_id,
        top_n=top_n,
        kind="skill",
    )

    return {"tools": scored_tools, "skills": scored_skills}


async def search_web_mcps(
    query: str, tenant_id: str, model_id: int, top_n: int = 5
) -> List[Dict[str, Any]]:
    """Search web MCP marketplaces (registry + community) and LLM-filter top-N."""
    if not query:
        return []

    candidates: List[Dict[str, Any]] = []

    def append_registry_candidates(registry_data: Optional[Dict[str, Any]]) -> int:
        added = 0
        for srv in (registry_data or {}).get("servers", []) or []:
            # The MCP Registry nests the server fields under a "server" object
            # (with provenance under "_meta"). Tolerate a flat shape as a
            # defensive fallback so a proxied/legacy payload still parses.
            server_obj = (
                srv.get("server") if isinstance(srv.get("server"), dict) else srv
            )
            name = server_obj.get("name") or ""
            scoring_id = f"registry:{name or len(candidates)}"
            candidates.append({
                "_scoring_id": scoring_id,
                "name": name,
                "description": (server_obj.get("description") or "")[:400],
                "source": "registry",
                "url": "",  # registry entries are resolved at install time
                "transport": "registry",
                "tools_summary": "",
            })
            added += 1
        return added

    registry_candidates = 0
    try:
        registry_data = await list_registry_mcp_services(
            search=query, limit=30
        )
        registry_candidates = append_registry_candidates(registry_data)
    except Exception as exc:
        logger.warning(f"Registry MCP search failed (continuing with community): {exc}")

    if registry_candidates == 0:
        try:
            registry_data = await list_registry_mcp_services(search=None, limit=30)
            registry_candidates = append_registry_candidates(registry_data)
        except Exception as exc:
            logger.warning(f"Registry MCP fallback listing failed: {exc}")

    try:
        community_data = await list_community_mcp_services(
            search=query, limit=30
        )
        for item in (community_data or {}).get("items", []) or []:
            scoring_id = (
                f"community:{item.get('communityId') or item.get('name') or len(candidates)}"
            )
            candidates.append({
                "_scoring_id": scoring_id,
                "name": item.get("name") or "",
                "description": (item.get("description") or "")[:400],
                "source": "community",
                "url": (
                    item.get("serverUrl")
                    or item.get("url")
                    or item.get("mcp_server")
                    or ""
                ),
                "transport": item.get("transportType") or "",
                "tools_summary": "",
                "community_id": item.get("communityId"),
            })
    except Exception as exc:
        logger.warning(f"Community MCP search failed: {exc}")

    if not candidates:
        return []

    # LLM-filter to top-N
    system_prompt = (
        "You are an MCP marketplace recommender. Given the user's intent and a "
        "list of MCP servers from the registry and community, score each 0-10 "
        "and give a one-line reason. Respond with STRICT JSON: an array of "
        "objects with `mcp_id`, `score` (0-10), and `reason`. No other text."
    )
    scoring_candidates = [
        {
            "mcp_id": candidate["_scoring_id"],
            "name": candidate.get("name") or "",
            "description": candidate.get("description") or "",
            "source": candidate.get("source") or "",
            "transport": candidate.get("transport") or "",
        }
        for candidate in candidates
    ]
    user_payload = {"user_intent": query, "mcps": scoring_candidates}
    try:
        raw = call_llm_for_system_prompt(
            model_id=model_id,
            user_prompt=json.dumps(user_payload, ensure_ascii=False),
            system_prompt=system_prompt,
            tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.warning(
            f"LLM scoring for web MCPs failed; returning unranked candidates: {exc}"
        )
        return _unranked_candidates(candidates, top_n, "MCP")

    scored = _parse_scored_json(raw, "mcp_id")
    if not scored:
        logger.warning(
            "LLM scoring returned no usable MCP rankings; returning unranked candidates."
        )
        return _unranked_candidates(candidates, top_n, "MCP")

    id_to_candidate = {c.get("_scoring_id"): c for c in candidates}
    enriched: List[Dict[str, Any]] = []
    for item in scored:
        cand = id_to_candidate.get(item.get("mcp_id"))
        if not cand:
            continue
        enriched.append({
            **_strip_internal_scoring_fields(cand),
            "score": item.get("score", 0),
            "reason": item.get("reason", ""),
        })

    if not enriched:
        logger.warning(
            "LLM scoring returned no matching MCP IDs; returning unranked candidates."
        )
        return _unranked_candidates(candidates, top_n, "MCP")

    enriched.sort(key=lambda x: x.get("score", 0), reverse=True)
    return enriched[:top_n]


async def search_web_skills(
    query: str, tenant_id: str, model_id: int, top_n: int = 5
) -> List[Dict[str, Any]]:
    """Search official/web skills and LLM-filter top-N."""
    if not query:
        return []

    try:
        official = get_official_skills_with_status(tenant_id=tenant_id) or []
    except Exception as exc:
        logger.error(f"Failed to list official skills for NL2AGENT: {exc}")
        raise AgentRunException("Failed to list official skills.") from exc

    candidates: List[Dict[str, Any]] = []
    for s in official:
        skill_name = s.get("name") or s.get("skill_name") or ""
        if not skill_name:
            continue
        candidates.append({
            "skill_id": s.get("skill_id") or 0,
            "skill_name": skill_name,
            "name": skill_name,
            "description": (s.get("description") or "")[:400],
            "tags": s.get("tags") or [],
            "status": s.get("status") or "installable",
        })

    if not candidates:
        return []

    scored = _score_candidates_with_llm(
        model_id=model_id,
        query=query,
        candidates=candidates,
        id_field="skill_name",
        tenant_id=tenant_id,
        top_n=top_n,
        kind="skill",
    )
    return scored


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
    bound_skill_ids: List[int] = []

    # Bind tools.
    for tool_id in tool_ids or []:
        try:
            tool_info = query_tools_by_ids([tool_id])
            if not tool_info:
                logger.warning(f"Tool id {tool_id} not found, skipping.")
                continue
            ti = tool_info[0]
            instance_req = ToolInstanceInfoRequest(
                tool_id=tool_id,
                agent_id=agent_id,
                params=_normalize_tool_instance_params(ti.get("params")),
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
        "tool_ids": tool_ids or [],
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
    model_id: int,
    task_description: str,
    tool_ids: List[int],
    skill_ids: List[int],
    sub_agent_ids: List[int],
    knowledge_base_display_names: List[str],
    user_id: str,
    tenant_id: str,
    language: str,
) -> Dict[str, Any]:
    """Finalize the draft agent by generating its full prompt set.

    Delegates to ``generate_and_save_system_prompt_impl`` which fills
    duty_prompt, constraint_prompt, few_shots_prompt, name, display_name,
    description, greeting_message, and example_questions.
    """
    _validate_draft_agent_id(agent_id)

    if not task_description:
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR,
            "task_description is required to finalize the agent.",
        )

    # Generate and persist all prompt sections. This call also updates the
    # agent row with name/display_name/description/greeting/example_questions.
    try:
        list(
            generate_and_save_system_prompt_impl(
                agent_id=agent_id,
                model_id=model_id,
                task_description=task_description,
                user_id=user_id,
                tenant_id=tenant_id,
                language=language,
                prompt_template_id=None,
                tool_ids=tool_ids or [],
                sub_agent_ids=sub_agent_ids or [],
                knowledge_base_display_names=knowledge_base_display_names or [],
                has_selected_resources=True,
            )
        )
    except Exception as exc:
        logger.error(f"Failed to finalize agent {agent_id}: {exc}")
        raise AgentRunException("Failed to generate agent prompts.") from exc

    # Rename the draft agent away from the draft_ prefix so it shows up in
    # the main agent list. The generate step may have already set a proper
    # name; if it left the draft_ name, clear it so the agent is visible.
    try:
        current = search_agent_info_by_agent_id(
            agent_id=agent_id, tenant_id=tenant_id
        )
        current_name = (current or {}).get("name") or ""
        if _is_draft_agent_name(current_name):
            # Mark as finalized by removing the draft prefix; the generate
            # step should have populated display_name etc.
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
    1. Inserts the 6 NL2AGENT builtin tool catalog rows (idempotent).
    2. Creates the NL2AGENT default agent (name="nl2agent") if absent, with
       the 6 builtin tools bound as ToolInstances.

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

    # 4. Bind the 6 builtin tools to the NL2AGENT agent as ToolInstances.
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
