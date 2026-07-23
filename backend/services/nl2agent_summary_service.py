"""Pure model and resource projections for NL2AGENT session summaries."""

from typing import Any, Callable, Dict, List, Optional, Set

from consts.exceptions import AgentRunException, Nl2AgentValidationError
from consts.model import ModelConnectStatusEnum
from services.nl2agent_resource_service import (
    redact_tool_parameter_defaults,
    tool_parameter_is_secret,
)
from services.nl2agent_seed_service import is_llm_model_type, normalize_model_ids


def validate_available_llm_ids(
    records: List[Dict[str, Any]],
    model_ids: List[int],
    *,
    finalizing: bool = False,
) -> Dict[int, Dict[str, Any]]:
    """Validate selected IDs against a previously loaded tenant inventory."""
    records_by_id = {int(record["model_id"]): record for record in records}
    validated_models: Dict[int, Dict[str, Any]] = {}
    for model_id in model_ids:
        record = records_by_id.get(int(model_id))
        if record is None:
            reason = f"Model {model_id} does not exist in this tenant."
        elif not is_llm_model_type(record.get("model_type")):
            reason = f"Model {model_id} is not an LLM."
        elif (
            ModelConnectStatusEnum.get_value(record.get("connect_status"))
            != ModelConnectStatusEnum.AVAILABLE.value
        ):
            reason = f"Model {model_id} is currently unavailable."
        else:
            display_name = str(
                record.get("display_name") or record.get("model_name") or ""
            ).strip()
            if display_name:
                validated_models[int(model_id)] = {
                    **record,
                    "display_name": display_name,
                }
                continue
            reason = f"Model {model_id} has no display name."
        if finalizing:
            reason += " Reopen the model-selection card and choose an available LLM."
        raise Nl2AgentValidationError(reason)
    return validated_models


def resolve_model_summaries(
    draft: Dict[str, Any], records: List[Dict[str, Any]]
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Resolve persisted model IDs into display-ready summaries without raising."""
    primary_model_id = draft.get("business_logic_model_id")
    model_ids = normalize_model_ids(draft.get("model_ids"))
    ordered_ids = list(model_ids)
    if primary_model_id:
        primary_model_id = int(primary_model_id)
        if primary_model_id not in ordered_ids:
            ordered_ids.insert(0, primary_model_id)

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
            display_name = (
                str(
                    record.get("display_name") or record.get("model_name") or ""
                ).strip()
                or None
            )
            if not is_llm_model_type(record.get("model_type")):
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


def resolve_resource_summaries(
    tool_instances: List[Dict[str, Any]],
    skill_instances: List[Dict[str, Any]],
    tool_records: List[Dict[str, Any]],
    skill_records: List[Dict[str, Any]],
    *,
    online_tool_ids: Optional[Set[int]] = None,
    online_skill_ids: Optional[Set[int]] = None,
    online_skill_names: Optional[Set[str]] = None,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Enrich persisted resource instances and report dangling references."""
    tools, invalid_tools = _resolve_resource_type(
        tool_instances,
        tool_records,
        id_key="tool_id",
        resource_type="tool",
        name_resolver=lambda info: info.get("origin_name") or info.get("name"),
        online_ids=online_tool_ids or set(),
    )
    tool_instances_by_id = {
        int(instance["tool_id"]): instance for instance in tool_instances
    }
    tool_records_by_id = {int(record["tool_id"]): record for record in tool_records}
    for summary in tools:
        tool_id = int(summary["tool_id"])
        instance_params = tool_instances_by_id[tool_id].get("params")
        values = instance_params if isinstance(instance_params, dict) else {}
        parameter_schema = redact_tool_parameter_defaults(
            tool_records_by_id[tool_id].get("params")
        )
        summary["parameter_schema"] = parameter_schema
        summary["configuration"] = {
            str(field["name"]): {
                "value": None
                if tool_parameter_is_secret(field)
                else values.get(str(field["name"])),
                "configured": (
                    str(field["name"]) in values
                    and values.get(str(field["name"])) not in (None, "")
                ),
                "secret": tool_parameter_is_secret(field),
            }
            for field in parameter_schema
            if isinstance(field, dict) and field.get("name")
        }
    skills, invalid_skills = _resolve_resource_type(
        skill_instances,
        skill_records,
        id_key="skill_id",
        resource_type="skill",
        name_resolver=lambda info: info.get("name"),
        online_ids=online_skill_ids or set(),
        online_names=online_skill_names or set(),
    )
    return tools, skills, invalid_tools + invalid_skills


def _resolve_resource_type(
    instances: List[Dict[str, Any]],
    records: List[Dict[str, Any]],
    *,
    id_key: str,
    resource_type: str,
    name_resolver: Callable[[Dict[str, Any]], Any],
    online_ids: Set[int],
    online_names: Optional[Set[str]] = None,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    records_by_id = {int(row[id_key]): row for row in records}
    summaries: List[Dict[str, Any]] = []
    invalid_references: List[Dict[str, Any]] = []
    for instance in instances:
        resource_id = int(instance[id_key])
        info = records_by_id.get(resource_id)
        name = str(name_resolver(info or {}) or "").strip()
        if not info or not name:
            invalid_references.append(
                {
                    "reference_type": resource_type,
                    "reference_id": resource_id,
                    "reason": "not_found" if not info else "name_missing",
                }
            )
            continue
        source = str(info.get("source") or "").lower()
        normalized_name = name.casefold().strip()
        summaries.append(
            {
                id_key: resource_id,
                "name": name,
                "source": source,
                "origin": (
                    "online"
                    if resource_id in online_ids
                    or normalized_name in (online_names or set())
                    else "local"
                ),
            }
        )
    return summaries, invalid_references


def resolve_online_resource_provenance(
    workflow_state: Dict[str, Any],
    *,
    skill_installations: Optional[List[Dict[str, Any]]] = None,
) -> tuple[Set[int], Set[int], Set[str]]:
    """Resolve resources bound through this session's online workflows."""
    online_tool_ids = {
        int(tool_id)
        for workflow in workflow_state.get("mcp_workflows", {}).values()
        if workflow.get("status") == "tools_bound"
        for tool_id in workflow.get("bound_tool_ids", [])
    }
    online_skill_ids: Set[int] = set()
    online_skill_names: Set[str] = set()
    for installation in skill_installations or []:
        if installation.get("status") != "completed":
            continue
        result = installation.get("result") or {}
        for value in (result.get("skill_id"), *(result.get("installed_ids") or [])):
            try:
                if value is not None:
                    online_skill_ids.add(int(value))
            except (TypeError, ValueError):
                continue
        for value in (
            result.get("skill_name"),
            result.get("_source_skill_name"),
            *(result.get("installed_names") or []),
        ):
            normalized = str(value or "").casefold().strip()
            if normalized:
                online_skill_names.add(normalized)
    return online_tool_ids, online_skill_ids, online_skill_names


def raise_for_invalid_resource_references(
    invalid_references: List[Dict[str, Any]],
) -> None:
    """Block publication when a persisted resource no longer resolves."""
    if not invalid_references:
        return
    references = ", ".join(
        f"{item['reference_type']} {item['reference_id']} ({item['reason']})"
        for item in invalid_references
    )
    raise AgentRunException(
        f"One or more selected resources are no longer valid: {references}. "
        "Reconfigure the draft before finalizing."
    )
