"""Local-resource binding operations for NL2AGENT drafts."""

import hashlib
import json
import logging
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Dict, List

from consts.exceptions import (
    AgentRunException,
    Nl2AgentOperationError,
    Nl2AgentValidationError,
)
from consts.model import SkillInstanceInfoRequest, ToolInstanceInfoRequest


logger = logging.getLogger(__name__)


def tool_parameter_is_secret(field: Dict[str, Any]) -> bool:
    """Return whether a Tool parameter must never be echoed to the browser."""
    name = str(field.get("name") or "")
    return bool(
        field.get("isSecret")
        or field.get("is_secret")
        or re.search(r"password|authorization|api[_-]?key|secret|token", name, re.I)
    )


_TOOL_VALUE_TYPE_CHECKS: Dict[str, Callable[[Any], bool]] = {
    "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
    "number": lambda item: (
        isinstance(item, (int, float)) and not isinstance(item, bool)
    ),
    "boolean": lambda item: isinstance(item, bool),
    "string": lambda item: isinstance(item, str),
    "array": lambda item: isinstance(item, list),
    "object": lambda item: isinstance(item, dict),
}


def redact_tool_parameter_defaults(params: Any) -> List[Dict[str, Any]]:
    """Remove credential defaults before Tool schemas are sent to the browser."""
    if not isinstance(params, list):
        return []
    sanitized = deepcopy(params)
    for field in sanitized:
        if not isinstance(field, dict):
            continue
        if tool_parameter_is_secret(field):
            field["default"] = None
    return sanitized


def _resolve_tool_config_values(
    tool_id: int,
    schema: Any,
    submitted: Dict[str, Any],
) -> Dict[str, Any]:
    """Validate submitted ToolInstance values against a ToolInfo parameter schema."""
    if isinstance(schema, dict):
        if submitted:
            raise Nl2AgentValidationError(
                f"Tool {tool_id} does not accept user configuration values."
            )
        return dict(schema)
    if not isinstance(schema, list):
        if submitted:
            raise Nl2AgentValidationError(
                f"Tool {tool_id} does not accept configuration values."
            )
        return {}

    fields = {
        str(field.get("name")): field
        for field in schema
        if isinstance(field, dict) and field.get("name")
    }
    unknown = sorted(set(submitted) - set(fields))
    if unknown:
        raise Nl2AgentValidationError(
            f"Tool {tool_id} received unknown configuration fields: {', '.join(unknown)}."
        )

    resolved: Dict[str, Any] = {}
    for name, field in fields.items():
        value = submitted.get(name, field.get("default"))
        resolved_value = _validate_tool_config_value(tool_id, name, field, value)
        if resolved_value is not None:
            resolved[name] = resolved_value
    return resolved


def _validate_tool_config_value(
    tool_id: int,
    name: str,
    field: Dict[str, Any],
    value: Any,
) -> Any:
    required = field.get("required") is True or field.get("optional") is False
    if value is None or value == "":
        if required:
            raise Nl2AgentValidationError(
                f"Tool {tool_id} requires configuration field: {name}."
            )
        return None

    expected_type = str(field.get("type") or "").lower()
    type_matches = _TOOL_VALUE_TYPE_CHECKS.get(expected_type)
    if type_matches and not type_matches(value):
        raise Nl2AgentValidationError(
            f"Tool {tool_id} configuration field {name} must be {expected_type}."
        )
    choices = field.get("choices")
    if isinstance(choices, list) and choices and value not in choices:
        raise Nl2AgentValidationError(
            f"Tool {tool_id} configuration field {name} must use a declared choice."
        )
    return value


@dataclass(frozen=True)
class LocalResourceDependencies:
    """Persistence and workflow operations used by local-resource actions."""

    get_owned_draft: Callable[[int, str], Dict[str, Any]]
    get_session_state: Callable[[str, int], Dict[str, Any]]
    get_session_catalogs: Callable[[str, int], Dict[str, List[Dict[str, Any]]]]
    query_tools_by_ids: Callable[[List[int], str], List[Dict[str, Any]]]
    query_skills_by_ids: Callable[[List[int], str], List[Dict[str, Any]]]
    get_db_session: Callable[[], Any]
    bind_tool: Callable[..., Any]
    bind_skill: Callable[..., Any]
    assert_trusted_batch: Callable[..., None]
    register_batch: Callable[..., Dict[str, Any]]
    resolve_batch: Callable[..., Dict[str, Any]]
    reserve_batch_apply: Callable[..., Dict[str, Any]]
    complete_batch_apply: Callable[..., Dict[str, Any]]
    release_batch_apply: Callable[..., Dict[str, Any]]
    continuation_text: str


def _load_selected_records(
    selected_ids: List[int],
    query_records: Callable[[List[int], str], List[Dict[str, Any]]],
    *,
    id_key: str,
    tenant_id: str,
    missing_message: str,
) -> Dict[int, Dict[str, Any]]:
    records = query_records(selected_ids, tenant_id) if selected_ids else []
    records_by_id = {int(item[id_key]): item for item in records}
    missing_ids = [
        resource_id for resource_id in selected_ids if resource_id not in records_by_id
    ]
    if missing_ids:
        raise AgentRunException(missing_message + ", ".join(map(str, missing_ids)))
    return records_by_id


async def apply_local_resources(
    dependencies: LocalResourceDependencies,
    *,
    agent_id: int,
    recommendation_batch_id: str,
    tool_ids: List[int],
    skill_ids: List[int],
    tenant_id: str,
    user_id: str,
    tool_config_values: Dict[int, Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Atomically bind every selected local resource to a draft."""
    dependencies.get_owned_draft(agent_id, tenant_id)
    state = dependencies.get_session_state(tenant_id, agent_id)
    batch = state["recommendation_batches"].get(recommendation_batch_id)
    if batch is None:
        raise AgentRunException(
            "The local resource recommendation card was not registered."
        )

    requested_tool_ids = set(map(int, tool_ids or []))
    requested_skill_ids = set(map(int, skill_ids or []))
    if not requested_tool_ids.issubset(set(batch.get("tool_ids", []))) or not (
        requested_skill_ids.issubset(set(batch.get("skill_ids", [])))
    ):
        raise Nl2AgentValidationError(
            "Selected resources do not belong to this recommendation batch."
        )

    selected_tool_ids = list(dict.fromkeys(map(int, tool_ids or [])))
    selected_skill_ids = list(dict.fromkeys(map(int, skill_ids or [])))
    submitted_config = {
        int(tool_id): values for tool_id, values in (tool_config_values or {}).items()
    }
    unexpected_config_ids = sorted(set(submitted_config) - set(selected_tool_ids))
    if unexpected_config_ids:
        raise Nl2AgentValidationError(
            "Tool configuration was submitted for an unselected tool."
        )
    tools_by_id = _load_selected_records(
        selected_tool_ids,
        dependencies.query_tools_by_ids,
        id_key="tool_id",
        tenant_id=tenant_id,
        missing_message="Local resource binding failed because tools no longer exist: ",
    )
    _load_selected_records(
        selected_skill_ids,
        dependencies.query_skills_by_ids,
        id_key="skill_id",
        tenant_id=tenant_id,
        missing_message=(
            "Local resource binding failed because tenant skills no longer exist: "
        ),
    )

    resolved_tool_params = {
        tool_id: _resolve_tool_config_values(
            tool_id,
            tools_by_id[tool_id].get("params"),
            submitted_config.get(tool_id, {}),
        )
        for tool_id in selected_tool_ids
    }
    operation_payload = {
        "recommendation_batch_id": recommendation_batch_id,
        "tool_ids": sorted(selected_tool_ids),
        "skill_ids": sorted(selected_skill_ids),
        "tool_params": {
            str(tool_id): resolved_tool_params[tool_id]
            for tool_id in sorted(resolved_tool_params)
        },
    }
    operation_id = hashlib.sha256(
        json.dumps(
            operation_payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    dependencies.reserve_batch_apply(
        tenant_id,
        agent_id,
        recommendation_batch_id,
        operation_id,
        selected_tool_ids,
        selected_skill_ids,
    )

    try:
        with dependencies.get_db_session() as db_session:
            for tool_id in selected_tool_ids:
                dependencies.bind_tool(
                    tool_info=ToolInstanceInfoRequest(
                        tool_id=tool_id,
                        agent_id=agent_id,
                        params=resolved_tool_params[tool_id],
                        enabled=True,
                        version_no=0,
                    ),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    version_no=0,
                    db_session=db_session,
                )
            for skill_id in selected_skill_ids:
                dependencies.bind_skill(
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
        try:
            dependencies.release_batch_apply(
                tenant_id,
                agent_id,
                recommendation_batch_id,
                operation_id,
            )
        except Exception:
            logger.exception("Failed to release local-resource apply reservation")
        logger.exception(
            "Failed to atomically bind local resources: "
            "tenant_id=%s draft_agent_id=%s batch_id=%s",
            tenant_id,
            agent_id,
            recommendation_batch_id,
        )
        raise Nl2AgentOperationError(
            "Local resource binding failed; no resources were applied."
        ) from exc

    try:
        dependencies.complete_batch_apply(
            tenant_id,
            agent_id,
            recommendation_batch_id,
            operation_id,
        )
    except Exception as exc:
        logger.exception(
            "Local resources were committed but workflow reconciliation failed: "
            "tenant_id=%s draft_agent_id=%s batch_id=%s",
            tenant_id,
            agent_id,
            recommendation_batch_id,
        )
        raise Nl2AgentOperationError(
            "Local resources were saved, but workflow state could not be reconciled. "
            "Retry Apply All."
        ) from exc

    return {
        "recommendation_batch_id": recommendation_batch_id,
        "status": "applied",
        "bound_tool_count": len(selected_tool_ids),
        "bound_skill_count": len(selected_skill_ids),
        "tool_ids": selected_tool_ids,
        "skill_ids": selected_skill_ids,
        "chat_injection_text": dependencies.continuation_text,
    }

async def register_local_recommendations(
    dependencies: LocalResourceDependencies,
    *,
    agent_id: int,
    recommendation_batch_id: str,
    tool_ids: List[int],
    skill_ids: List[int],
    tenant_id: str,
) -> Dict[str, Any]:
    """Register a local-resource card after it is rendered."""
    dependencies.get_owned_draft(agent_id, tenant_id)
    catalogs = dependencies.get_session_catalogs(tenant_id, agent_id)
    catalog_tool_ids = {
        int(item["tool_id"])
        for item in catalogs["tool_catalog"]
        if item.get("tool_id") is not None
    }
    catalog_skill_ids = {
        int(item["skill_id"])
        for item in catalogs["skill_catalog"]
        if item.get("skill_id") is not None
    }
    unknown_tool_ids = sorted(set(map(int, tool_ids)) - catalog_tool_ids)
    unknown_skill_ids = sorted(set(map(int, skill_ids)) - catalog_skill_ids)
    if unknown_tool_ids or unknown_skill_ids:
        raise Nl2AgentValidationError(
            "Local recommendations contain resources outside this session catalog."
        )
    dependencies.assert_trusted_batch(
        tenant_id,
        agent_id,
        recommendation_batch_id,
        tool_ids,
        skill_ids,
    )
    selected_tool_ids = list(dict.fromkeys(map(int, tool_ids)))
    selected_skill_ids = list(dict.fromkeys(map(int, skill_ids)))
    tool_records = (
        dependencies.query_tools_by_ids(selected_tool_ids, tenant_id)
        if selected_tool_ids
        else []
    )
    tools_by_id = {int(item["tool_id"]): item for item in tool_records}
    missing_tool_ids = [
        tool_id for tool_id in selected_tool_ids if tool_id not in tools_by_id
    ]
    if missing_tool_ids:
        raise AgentRunException(
            "Local recommendations contain tools that no longer exist: "
            + ", ".join(map(str, missing_tool_ids))
        )
    skill_records = (
        dependencies.query_skills_by_ids(selected_skill_ids, tenant_id)
        if selected_skill_ids
        else []
    )
    existing_skill_ids = {int(item["skill_id"]) for item in skill_records}
    missing_skill_ids = sorted(set(selected_skill_ids) - existing_skill_ids)
    if missing_skill_ids:
        raise AgentRunException(
            "Local recommendations contain tenant skills that no longer exist: "
            + ", ".join(map(str, missing_skill_ids))
        )
    batch = dependencies.register_batch(
        tenant_id,
        agent_id,
        recommendation_batch_id,
        selected_tool_ids,
        selected_skill_ids,
    )
    return {
        "recommendation_batch_id": recommendation_batch_id,
        **batch,
        "tool_parameter_schemas": {
            str(tool_id): redact_tool_parameter_defaults(
                tools_by_id[tool_id].get("params") or []
            )
            for tool_id in selected_tool_ids
        },
    }


async def skip_local_recommendations(
    dependencies: LocalResourceDependencies,
    *,
    agent_id: int,
    recommendation_batch_id: str,
    tenant_id: str,
) -> Dict[str, Any]:
    """Resolve a rendered local-resource batch without applying it."""
    dependencies.get_owned_draft(agent_id, tenant_id)
    batch = dependencies.resolve_batch(
        tenant_id,
        agent_id,
        recommendation_batch_id,
        "skipped",
    )
    return {
        "recommendation_batch_id": recommendation_batch_id,
        **batch,
        "chat_injection_text": dependencies.continuation_text,
    }
