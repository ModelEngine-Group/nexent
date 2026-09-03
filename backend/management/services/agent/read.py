"""Shared Agent read projections and availability rules."""

from dataclasses import dataclass

from typing import Dict, Optional

from consts.agent_unavailable_reasons import AgentUnavailableReason
from database.agent_db import search_agent_info_by_agent_id
from database.model_management_db import get_model_by_model_id_ignore_delete, get_valid_model_ids
from database.tool_db import check_tool_is_available, search_tools_for_sub_agent
from management.services.model.resolver import is_model_available, resolve_model_record


@dataclass(frozen=True)
class AgentModelProjection:
    """Public model fields plus private availability metadata."""

    fields: dict
    deleted_model_ids: frozenset[int]


def project_agent_models(
    agent: dict,
    tenant_id: str,
    model_cache: dict | None = None,
    *,
    detail: bool = False,
) -> AgentModelProjection:
    """Project model fields while preserving detail/list legacy-name semantics."""
    configured_model_ids = agent.get("model_ids") or []
    model_ids = get_valid_model_ids(configured_model_ids, tenant_id)
    records = [
        resolve_model_record(mid, None if detail else tenant_id, model_cache)
        for mid in model_ids
    ]
    names = [record["display_name"] for record in records if record and record.get("display_name")]
    legacy_name = names[0] if names else None
    if detail:
        legacy_name = records[0].get("display_name") if records and records[0] is not None else None
    return AgentModelProjection(
        fields={"model_ids": model_ids, "model_names": names, "model_name": legacy_name},
        deleted_model_ids=frozenset(configured_model_ids) - frozenset(model_ids),
    )


def apply_deleted_model_reason(
    is_available: bool,
    unavailable_reasons: list[str],
    deleted_model_ids: frozenset[int],
) -> tuple[bool, list[str]]:
    """Merge the configured-model deletion reason without duplicates."""
    if deleted_model_ids and AgentUnavailableReason.MODEL_DELETED not in unavailable_reasons:
        unavailable_reasons.append(AgentUnavailableReason.MODEL_DELETED)
    return not unavailable_reasons and is_available, unavailable_reasons


def tool_has_deleted_model(tool: dict, tenant_id: str) -> bool:
    """Check the first selected_model_id parameter using the legacy deletion rule."""
    params = tool.get("params") or []
    if isinstance(params, list):
        for param in params:
            if isinstance(param, dict) and param.get("name") == "selected_model_id":
                model_id = param.get("default")
                record = get_model_by_model_id_ignore_delete(model_id, tenant_id) if model_id is not None else None
                return record is not None and record.get("delete_flag") == "Y"
    return False


def check_agent_availability(
    agent_id: int,
    tenant_id: str,
    agent_info: dict | None = None,
    model_cache: Dict[int, Optional[dict]] | None = None,
) -> tuple[bool, list[str]]:
    """Evaluate tools and configured models using request-local model caching."""
    cache = model_cache if model_cache is not None else {}
    if agent_info is None:
        agent_info = search_agent_info_by_agent_id(agent_id, tenant_id)
    if not agent_info:
        return False, [AgentUnavailableReason.AGENT_NOT_FOUND]
    tools = search_tools_for_sub_agent(agent_id=agent_id, tenant_id=tenant_id)
    reasons = []
    tool_ids = [tool["tool_id"] for tool in tools if tool.get("tool_id") is not None]
    if tool_ids and not all(check_tool_is_available(tool_ids)):
        reasons.append(AgentUnavailableReason.TOOL_UNAVAILABLE)
    reasons.extend(
        AgentUnavailableReason.TOOL_UNAVAILABLE for tool in tools if tool_has_deleted_model(tool, tenant_id)
    )
    model_ids = agent_info.get("model_ids") or []
    if not model_ids:
        reasons.append(AgentUnavailableReason.MODEL_NOT_CONFIGURED)
    else:
        reasons.extend(
            AgentUnavailableReason.MODEL_UNAVAILABLE
            for mid in model_ids if mid and not is_model_available(resolve_model_record(mid, tenant_id, cache))
        )
    return not reasons, reasons


def apply_duplicate_name_availability_rules(enriched_agents: list[dict]) -> None:
    """
    For agents that share the same name or display_name, only the earliest created
    agent should remain available (if it has no other unavailable reasons).
    All later-created agents in the same group become unavailable due to duplication.
    """
    # Group by name and display_name
    name_groups: dict[str, list[dict]] = {}
    display_name_groups: dict[str, list[dict]] = {}

    for entry in enriched_agents:
        agent = entry["raw_agent"]
        name = agent.get("name")
        if name:
            name_groups.setdefault(name, []).append(entry)

        display_name = agent.get("display_name")
        if display_name:
            display_name_groups.setdefault(display_name, []).append(entry)

    def _mark_duplicates(groups: dict[str, list[dict]], reason_key: str) -> None:
        for entries in groups.values():
            if len(entries) <= 1:
                continue

            # Sort by create_time ascending so the earliest created agent comes first
            sorted_entries = sorted(
                entries,
                key=lambda e: e["raw_agent"].get("create_time"),
            )

            # The first (earliest) agent keeps its current availability;
            # subsequent agents are marked as duplicates.
            for duplicate_entry in sorted_entries[1:]:
                duplicate_entry["unavailable_reasons"].append(reason_key)

    _mark_duplicates(name_groups, AgentUnavailableReason.DUPLICATE_NAME)
    _mark_duplicates(display_name_groups,
                     AgentUnavailableReason.DUPLICATE_DISPLAY_NAME)
