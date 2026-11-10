# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Shared Workbench Skill access and configuration policy."""

from copy import deepcopy
from math import isfinite
from typing import Any, Dict

from contracts.constants.constants import CAN_EDIT_ALL_USER_ROLES, PERMISSION_PRIVATE
from contracts.errors.exceptions import WorkbenchError


def _to_group_id_set(group_ids: Any) -> set[int]:
    if isinstance(group_ids, str):
        return {
            int(group_id.strip())
            for group_id in group_ids.split(",")
            if group_id.strip().isdigit()
        }
    if isinstance(group_ids, list):
        return {
            int(group_id) for group_id in group_ids if str(group_id).strip().isdigit()
        }
    return set()


def can_view_skill(
    *,
    skill: Dict[str, Any],
    user_id: str,
    user_role: str,
    user_group_ids: set[int],
) -> bool:
    """Return whether a skill is available to the current user."""
    if skill.get("source") == "official":
        return True
    if user_role in CAN_EDIT_ALL_USER_ROLES:
        return True
    if str(skill.get("created_by")) == str(user_id):
        return True
    if skill.get("ingroup_permission") == PERMISSION_PRIVATE:
        return False
    return bool(user_group_ids.intersection(_to_group_id_set(skill.get("group_ids"))))


def resolve_skill_config(schemas, defaults, published, runtime):
    """Validate declared configuration after applying the three precedence layers."""
    fields = {item["name"]: item for item in schemas if isinstance(item, dict) and item.get("name")}
    values = deepcopy(defaults)
    values.update(deepcopy(published))
    values.update(deepcopy(runtime))
    if any(name not in fields for name in runtime):
        raise WorkbenchError("RUNTIME_SKILL_CONFIG_INVALID")
    types = {
        "string": str, "boolean": bool, "integer": int,
        "number": (int, float), "object": dict, "array": list,
    }
    for name, schema in fields.items():
        value = values.get(name)
        if value is None and "default" in schema:
            value = values[name] = deepcopy(schema["default"])
        if value is None or value == "":
            if schema.get("required"):
                raise WorkbenchError("RUNTIME_SKILL_CONFIG_INVALID")
            continue
        expected = types.get(schema.get("type"))
        if expected and (not isinstance(value, expected) or (
            schema.get("type") in {"integer", "number"} and isinstance(value, bool)
        )):
            raise WorkbenchError("RUNTIME_SKILL_CONFIG_INVALID")
        if isinstance(schema.get("enum"), list) and value not in schema["enum"]:
            raise WorkbenchError("RUNTIME_SKILL_CONFIG_INVALID")
        if schema.get("type") in {"integer", "number"}:
            if not isfinite(value):
                raise WorkbenchError("RUNTIME_SKILL_CONFIG_INVALID")
            if schema.get("minimum") is not None and value < schema["minimum"]:
                raise WorkbenchError("RUNTIME_SKILL_CONFIG_INVALID")
            if schema.get("maximum") is not None and value > schema["maximum"]:
                raise WorkbenchError("RUNTIME_SKILL_CONFIG_INVALID")
    return values
