"""Startup seed policy for the built-in NL2AGENT builder."""

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from consts.model import (
    AgentInfoRequest,
    ModelConnectStatusEnum,
    ToolInstanceInfoRequest,
)

logger = logging.getLogger(__name__)


LLM_MODEL_TYPES = frozenset({"llm", "chat"})


NL2AGENT_VERIFICATION_CONFIG = {
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

_SEED_PROMPT_FALLBACK = (
    "You are NL2AGENT, the Agent Builder. Help the user design and build "
    "a custom agent through multi-turn natural-language dialogue."
)
_AGENT_INFO_FALLBACK = {
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
_PROMPT_SEGMENTS_FALLBACK = {
    "duty_prompt": _SEED_PROMPT_FALLBACK,
    "constraint_prompt": (
        "Always wait for explicit user confirmation before applying local "
        "resources or finalizing the agent. Never make up tool or skill names. "
        "Use the user's language."
    ),
    "few_shots_prompt": "",
}


@dataclass(frozen=True)
class SeedDependencies:
    """Database and configuration operations used by startup seeding."""

    get_seed_config: Callable[[str], Dict[str, Any]]
    get_model_records: Callable[..., List[Dict[str, Any]]]
    update_agent: Callable[..., Any]
    seed_builtin_tools: Callable[..., List[int]]
    query_all_agents: Callable[[str], List[Dict[str, Any]]]
    create_agent: Callable[..., Dict[str, Any]]
    bind_tool: Callable[..., Any]
    agent_name: str
    language: str


def normalize_model_ids(value: Any) -> List[int]:
    """Normalize persisted model IDs while preserving their order."""
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


def is_llm_model_type(value: Any) -> bool:
    """Return whether a persisted model type represents a platform LLM."""
    return str(value or "").strip().lower() in LLM_MODEL_TYPES


def _load_seed_fields(dependencies: SeedDependencies) -> Dict[str, str]:
    seed_fields = {
        "name": dependencies.agent_name,
        **_AGENT_INFO_FALLBACK,
        **_PROMPT_SEGMENTS_FALLBACK,
    }
    try:
        seed_config = dependencies.get_seed_config(dependencies.language)
        seed_fields.update(seed_config.get("agent_info") or {})
        seed_fields.update(seed_config.get("prompt_segments") or {})
    except Exception as exc:
        logger.warning("Failed to load NL2AGENT seed config: %s", exc)
    seed_fields["name"] = dependencies.agent_name
    return seed_fields


def _available_llm_model_ids(
    dependencies: SeedDependencies, tenant_id: str
) -> List[int]:
    try:
        records = dependencies.get_model_records(None, tenant_id) or []
    except Exception as exc:
        logger.warning(
            "Failed to list models for NL2AGENT seed in tenant %s: %s",
            tenant_id,
            exc,
        )
        return []
    model_ids: List[int] = []
    for record in records:
        if not is_llm_model_type(record.get("model_type")):
            continue
        if (
            ModelConnectStatusEnum.get_value(record.get("connect_status"))
            != ModelConnectStatusEnum.AVAILABLE.value
        ):
            continue
        try:
            model_id = int(record["model_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if model_id not in model_ids:
            model_ids.append(model_id)
    return model_ids


def build_seed_defaults(
    dependencies: SeedDependencies, tenant_id: str
) -> Dict[str, Any]:
    """Build canonical builder fields and the available model order."""
    model_ids = _available_llm_model_ids(dependencies, tenant_id)
    defaults: Dict[str, Any] = {
        **_load_seed_fields(dependencies),
        "prompt_template_id": None,
        "prompt_template_name": None,
        "verification_config": NL2AGENT_VERIFICATION_CONFIG,
    }
    if model_ids:
        defaults["model_ids"] = model_ids
        defaults["business_logic_model_id"] = model_ids[0]
    return defaults


def ensure_seed_defaults(
    dependencies: SeedDependencies,
    agent: Dict[str, Any],
    user_id: str,
    tenant_id: str,
) -> None:
    """Backfill canonical seed fields on an existing builder agent."""
    agent_id = agent.get("agent_id")
    if not agent_id:
        return
    defaults = build_seed_defaults(dependencies, tenant_id)
    update_values = {
        field: defaults[field]
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
        )
        if agent.get(field) != defaults[field]
    }
    desired_model_ids = defaults.get("model_ids") or []
    if (
        desired_model_ids
        and normalize_model_ids(agent.get("model_ids")) != desired_model_ids
    ):
        update_values["model_ids"] = desired_model_ids
    if (
        desired_model_ids
        and agent.get("business_logic_model_id") not in desired_model_ids
    ):
        update_values["business_logic_model_id"] = desired_model_ids[0]
    if not update_values:
        return
    dependencies.update_agent(
        agent_id=agent_id,
        agent_info=AgentInfoRequest(**update_values),
        user_id=user_id,
        version_no=0,
    )


def _bind_builtin_tools(
    dependencies: SeedDependencies,
    *,
    agent_id: int,
    tool_ids: List[int],
    tenant_id: str,
    user_id: str,
) -> None:
    """Idempotently bind every required builder tool or fail readiness."""
    if not tool_ids:
        raise RuntimeError("NL2AGENT builtin tool seeding returned no tools.")
    for tool_id in tool_ids:
        dependencies.bind_tool(
            tool_info=ToolInstanceInfoRequest(
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


def ensure_builder_ready(
    dependencies: SeedDependencies,
    agent: Dict[str, Any],
    user_id: str,
    tenant_id: str,
) -> None:
    """Repair builder fields and required bindings, failing on partial repair."""
    agent_id = agent.get("agent_id")
    if not isinstance(agent_id, int) or agent_id <= 0:
        raise RuntimeError("NL2AGENT builder has no valid agent_id.")
    tool_ids = dependencies.seed_builtin_tools(
        tenant_id=tenant_id,
        user_id=user_id,
    )
    ensure_seed_defaults(dependencies, agent, user_id, tenant_id)
    _bind_builtin_tools(
        dependencies,
        agent_id=agent_id,
        tool_ids=tool_ids,
        tenant_id=tenant_id,
        user_id=user_id,
    )


def seed_default_agent(
    dependencies: SeedDependencies,
    tenant_id: str,
    user_id: str,
) -> Optional[int]:
    """Create or repair the built-in builder and bind its built-in tools."""
    try:
        tool_ids = dependencies.seed_builtin_tools(tenant_id=tenant_id, user_id=user_id)
    except Exception as exc:
        logger.error("Failed to seed NL2AGENT builtin tools: %s", exc)
        return None
    try:
        all_agents = dependencies.query_all_agents(tenant_id) or []
    except Exception as exc:
        logger.error("Failed to query agents for NL2AGENT seeding: %s", exc)
        return None
    for agent in all_agents:
        if (agent.get("name") or "") == dependencies.agent_name:
            existing_id = agent.get("agent_id")
            try:
                ensure_seed_defaults(dependencies, agent, user_id, tenant_id)
                _bind_builtin_tools(
                    dependencies,
                    agent_id=existing_id,
                    tool_ids=tool_ids,
                    tenant_id=tenant_id,
                    user_id=user_id,
                )
            except Exception as exc:
                logger.error(
                    "Failed to repair NL2AGENT default agent %s: %s",
                    existing_id,
                    exc,
                )
                return None
            logger.info(
                "NL2AGENT default agent already exists (agent_id=%s)", existing_id
            )
            return existing_id

    payload = {"max_steps": 20, "enabled": True, "is_new": False}
    payload.update(build_seed_defaults(dependencies, tenant_id))
    try:
        created = dependencies.create_agent(
            payload, tenant_id=tenant_id, user_id=user_id
        )
    except Exception as exc:
        logger.warning(
            "NL2AGENT builder creation raced or failed; checking the tenant winner: %s",
            exc,
        )
        try:
            concurrent = next(
                (
                    agent
                    for agent in (dependencies.query_all_agents(tenant_id) or [])
                    if (agent.get("name") or "") == dependencies.agent_name
                ),
                None,
            )
            if concurrent is None:
                raise RuntimeError("No concurrent NL2AGENT builder was committed")
            ensure_seed_defaults(dependencies, concurrent, user_id, tenant_id)
            _bind_builtin_tools(
                dependencies,
                agent_id=concurrent["agent_id"],
                tool_ids=tool_ids,
                tenant_id=tenant_id,
                user_id=user_id,
            )
            return int(concurrent["agent_id"])
        except Exception:
            logger.error("Failed to create NL2AGENT default agent", exc_info=True)
            return None
    agent_id = created.get("agent_id")
    if not agent_id:
        logger.error("NL2AGENT default agent creation returned no agent_id.")
        return None
    try:
        _bind_builtin_tools(
            dependencies,
            agent_id=agent_id,
            tool_ids=tool_ids,
            tenant_id=tenant_id,
            user_id=user_id,
        )
    except Exception as exc:
        logger.error(
            "Failed to bind all builtin tools to NL2AGENT agent %s: %s",
            agent_id,
            exc,
        )
        return None
    logger.info(
        "Seeded NL2AGENT default agent (agent_id=%s) with %s builtin tools for tenant %s",
        agent_id,
        len(tool_ids),
        tenant_id,
    )
    return agent_id
