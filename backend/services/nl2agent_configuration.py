# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Read and update the explicitly supported NL2Agent configuration sections."""

from nexent.core.agents.contracts.config import AgentVerificationConfig, GuardrailConfig
from nexent.core.concurrency import run_blocking

from contracts.agent import AgentInfoRequest
from contracts.constants.constants import CAN_EDIT_ALL_USER_ROLES
from contracts.nl2agent_configuration import ConfigurationSection, PATCH_MODELS
from contracts.tag import AuthenticatedCaller
from management.db.agent.repository import (
    is_system_agent,
    query_all_agent_info_by_tenant_id,
    query_sub_agent_relations,
    update_agent_draft_fields,
    update_related_agents,
)
from management.db.agent.version import query_version_list
from management.db.identity.group import query_group_ids_by_user_in_tenant, query_groups_by_tenant
from management.db.model.repository import get_model_records
from management.services.agent.authorization import require_agent_draft_edit
from management.services.agent.service import _validate_agent_relationships
from management.services.tag.library import TagManagementService
from management.utils.serialization import convert_list_to_string, convert_string_to_list


class ConfigurationError(ValueError):
    pass


def _draft(caller: AuthenticatedCaller, agent_id: int) -> dict:
    draft = require_agent_draft_edit(agent_id=agent_id, tenant_id=caller.authenticated_tenant_id,
                                    user_id=caller.user_id)
    if is_system_agent(agent_id, caller.authenticated_tenant_id):
        raise ConfigurationError("system_agent_read_only")
    if not caller.can_edit_all and draft.get("created_by") != caller.user_id:
        groups = query_group_ids_by_user_in_tenant(caller.user_id, caller.authenticated_tenant_id)
        if not set(groups).intersection(convert_string_to_list(draft.get("group_ids"))):
            raise ConfigurationError("agent_read_only")
    return draft


def _available_models(tenant_id: str) -> list[dict]:
    return [
        {"model_id": model["model_id"], "name": model["display_name"] or model["model_name"]}
        for model in get_model_records({"model_type": "llm"}, tenant_id)
        if str(model.get("connect_status", "")).lower() == "available"
    ]


def _visible_collaborators(caller: AuthenticatedCaller, agent_id: int) -> list[dict]:
    tenant = caller.authenticated_tenant_id
    groups = set(query_group_ids_by_user_in_tenant(caller.user_id, tenant))
    return [
        {"agent_id": row["agent_id"], "name": row.get("display_name") or row["name"]}
        for row in query_all_agent_info_by_tenant_id(tenant)
        if row["agent_id"] != agent_id and row.get("agent_origin") != "SYSTEM" and (
            caller.can_edit_all or row.get("created_by") == caller.user_id or (
                row.get("ingroup_permission") in {"READ_ONLY", "EDIT"}
                and groups.intersection(convert_string_to_list(row.get("group_ids")))
            )
        )
    ]


def _relations(tenant_id: str, agent_id: int) -> dict[int, int | None]:
    return {
        row["selected_agent_id"]: row["selected_agent_version_no"]
        for row in query_sub_agent_relations(agent_id, tenant_id)
    }


def _groups(tenant_id: str) -> list[dict]:
    return [
        {"group_id": row["group_id"], "name": row["group_name"]}
        for row in query_groups_by_tenant(tenant_id, page=None)["groups"]
    ]


def _tag_options(tenant_id: str) -> list[dict]:
    return [
        {"value_id": value["value_id"], "name": value["display_value"], "definition": definition["definition_name"]}
        for library in TagManagementService.list_libraries(tenant_id) if "agent" in library["resource_types"]
        for definition in TagManagementService.list_definitions(tenant_id, library["bucket_id"])
        if definition.get("status") == "active"
        for value in definition.get("values") or [] if value.get("status") == "active"
    ]


def _read_section(caller: AuthenticatedCaller, agent_id: int, section: ConfigurationSection, draft: dict) -> dict:
    tenant = caller.authenticated_tenant_id
    if section == "model":
        return {"model_ids": draft.get("model_ids") or [], "options": _available_models(tenant)}
    if section == "collaborators":
        return {
            "related_agents": [{"agent_id": key, "version_no": value} for key, value in _relations(tenant, agent_id).items()],
            "options": [
                {**row, "versions": [0, *(item["version_no"] for item in query_version_list(row["agent_id"], tenant)
                                         if item["version_no"] != 0)]}
                for row in _visible_collaborators(caller, agent_id)
            ],
        }
    if section == "permissions":
        return {
            "group_ids": convert_string_to_list(draft.get("group_ids")),
            "ingroup_permission": draft.get("ingroup_permission"),
            "is_main_agent": draft.get("is_main_agent"), "is_a2a": draft.get("is_a2a"),
            "groups": _groups(tenant), "permission_options": ["PRIVATE", "READ_ONLY", "EDIT"],
        }
    if section == "tags":
        return {"options": _tag_options(tenant)}
    verification_config = draft.get("verification_config") or {}
    if section == "guardrails":
        verification = AgentVerificationConfig.model_validate(verification_config)
        return (verification.guardrail_config or GuardrailConfig()).model_dump(mode="json")
    verification = AgentVerificationConfig.model_validate(
        {"enabled": verification_config["enabled"]} if "enabled" in verification_config else {},
    )
    return {
        **{key: draft.get(key) for key in (
            "max_steps", "provide_run_summary", "allow_chat_metadata", "enable_protocol_repair_retry",
        )},
        "self_verification_enabled": verification.enabled,
    }


async def read_configuration(caller: AuthenticatedCaller, agent_id: int, section: ConfigurationSection) -> dict:
    draft = await run_blocking("nl2agent-config-draft", _draft, caller, agent_id, lane="control-io")
    values = await run_blocking("nl2agent-config-read", _read_section, caller, agent_id, section, draft,
                                lane="control-io")
    if section == "tags":
        tags = await TagManagementService.get_resource_assignments(caller, "agent", str(agent_id))
        values["assignments"] = tags["assignments"]
    return values


def _update_collaboration(caller: AuthenticatedCaller, agent_id: int, patch: dict) -> None:
    tenant = caller.authenticated_tenant_id
    current = _relations(tenant, agent_id)
    add = patch.get("add", [])
    remove = set(patch.get("remove", []))
    additions = {row["agent_id"]: row.get("version_no") for row in add}
    if (not additions and not remove) or len(additions) != len(add) or set(additions) & remove:
        raise ConfigurationError("invalid_collaborators")
    if additions:
        visible = {row["agent_id"] for row in _visible_collaborators(caller, agent_id)}
        if not set(additions) <= visible:
            raise ConfigurationError("invalid_collaborators")
    merged = {**{key: version for key, version in current.items() if key not in remove}, **additions}
    request = AgentInfoRequest(agent_id=agent_id, related_agents=[
        {"agent_id": key, "version_no": value} for key, value in merged.items()
    ])
    related = _validate_agent_relationships(request, tenant)
    if not update_related_agents(agent_id, tenant, caller.user_id, related_agents=related, expected_relations=current):
        raise ConfigurationError("configuration_changed")


def _guardrail_changes(draft: dict, patch: dict) -> dict:
    verification = dict(draft.get("verification_config") or {})
    guardrail = dict(verification.get("guardrail_config") or {})
    existing_rules = guardrail.get("rules", [])
    upserts = patch.get("upsert_rules", [])
    by_name = {rule["name"]: rule for rule in upserts}
    removed = set(patch.get("remove_rules", []))
    if len(by_name) != len(upserts) or removed & by_name.keys():
        raise ConfigurationError("invalid_guardrails")
    rules = {rule["name"]: rule for rule in existing_rules if rule["name"] not in removed}
    rules.update(by_name)
    guardrail.update({"rules": list(rules.values())})
    if "enabled" in patch:
        guardrail["enabled"] = patch["enabled"]
    GuardrailConfig.model_validate(guardrail)
    verification["guardrail_config"] = guardrail
    return {"verification_config": verification}


def _apply(
    caller: AuthenticatedCaller, agent_id: int, section: ConfigurationSection, patch: dict, draft: dict,
) -> list[str]:
    tenant = caller.authenticated_tenant_id
    if section == "collaborators":
        _update_collaboration(caller, agent_id, patch)
        return ["related_agents"]
    if section == "model":
        ids = patch["model_ids"]
        if len(ids) != len(set(ids)) or not set(ids) <= {row["model_id"] for row in _available_models(tenant)}:
            raise ConfigurationError("invalid_model_selection")
    if section == "permissions":
        if "group_ids" in patch:
            ids = patch["group_ids"]
            if len(ids) != len(set(ids)) or not set(ids) <= {row["group_id"] for row in _groups(tenant)}:
                raise ConfigurationError("invalid_permission_groups")
            patch["group_ids"] = convert_list_to_string(ids)
        if patch.get("ingroup_permission") == "PRIVATE":
            patch["group_ids"] = convert_list_to_string([])
    if section == "guardrails":
        patch = _guardrail_changes(draft, patch)
    if section == "advanced" and "self_verification_enabled" in patch:
        patch["verification_config"] = {
            **(draft.get("verification_config") or {}),
            "enabled": patch.pop("self_verification_enabled"),
        }
    expected = {key: draft.get(key) for key in {*patch, "group_ids", "ingroup_permission"}}
    count = update_agent_draft_fields(agent_id, tenant, {**patch, "updated_by": caller.user_id},
                                      expected_fields=expected)
    if count != 1:
        raise ConfigurationError("configuration_changed")
    return list(patch)


async def save_configuration(
    caller: AuthenticatedCaller, agent_id: int, section: ConfigurationSection, changes: dict,
) -> list[str]:
    patch = PATCH_MODELS[section].model_validate(changes).model_dump(mode="json", exclude_unset=True)
    draft = await run_blocking("nl2agent-config-draft", _draft, caller, agent_id, lane="control-io")
    if section == "tags":
        add, remove = patch.get("add", []), patch.get("remove", [])
        if (not add and not remove) or set(add).intersection(remove):
            raise ConfigurationError("invalid_tag_changes")
        await TagManagementService.replace_resource_assignments(
            caller, "agent", str(agent_id), add, remove_value_ids=remove,
        )
        return ["tags"]
    return await run_blocking("nl2agent-config-update", _apply, caller, agent_id, section, patch, draft,
                              lane="control-io")
