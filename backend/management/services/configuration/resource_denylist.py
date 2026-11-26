# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read and manage the tool denylist shared by recommendations and Agent configuration."""

from dataclasses import dataclass
from hashlib import sha256

from contracts.errors.exceptions import ResourceBindingError
from contracts.resource_denylist import GlobalDenylist, TenantDenylist
from infrastructure.rdb import client
from infrastructure.system_configuration.database import configuration_database
from management.db.configuration import resource_denylist as repository


class DenylistConflict(ValueError):
    """The configuration changed after the editor was opened."""


@dataclass(frozen=True)
class ToolDenylist:
    tool_names: frozenset[str]
    resource_refs: frozenset[str]
    global_resources: frozenset[str] = frozenset()
    mcp_tool_ids: frozenset[int] = frozenset()

    def blocks(self, name: str | None, tool_id: int | None = None) -> bool:
        return name in self.tool_names or f"tool:{tool_id}" in self.resource_refs or tool_id in self.mcp_tool_ids

    def blocks_skill(self, name: str | None, skill_id: int | None = None) -> bool:
        return f"skill:{name}" in self.global_resources or f"skill:{skill_id}" in self.resource_refs

    def blocks_mcp(self, name: str | None) -> bool:
        return f"mcp:{name}" in self.global_resources


def _global_value(row):
    return GlobalDenylist.model_validate(row.configuration_value) if row else GlobalDenylist(tool_names=[])


def _tenant_value(row):
    return TenantDenylist.model_validate_json(row.config_value) if row else TenantDenylist(resource_refs=[])


def load_tool_denylist(tenant_id, *, session=None):
    with (client.get_db_session() if session is None else client.get_db_session(session)) as db:
        global_value, tenant_value = repository.policy_values(db, tenant_id)
        global_policy = GlobalDenylist.model_validate(global_value or {})
        refs = TenantDenylist.model_validate_json(tenant_value).resource_refs if tenant_value is not None else []
        mcp_names = {ref.split(":", 1)[1] for ref in global_policy.resource_refs if ref.startswith("mcp:")}
        mcp_ids = {int(ref.split(":", 1)[1]) for ref in refs if ref.startswith("mcp:")}
        tool_ids = repository.blocked_mcp_tool_ids(db, tenant_id, mcp_names, mcp_ids) if mcp_names or mcp_ids else set()
    return ToolDenylist(frozenset(global_policy.tool_names), frozenset(refs),
                        frozenset(global_policy.resource_refs), frozenset(tool_ids))


def require_tool_allowed(tenant_id, name, tool_id, *, session=None):
    if load_tool_denylist(tenant_id, session=session).blocks(name, tool_id):
        raise ResourceBindingError("resource_blocked")


def require_skill_allowed(tenant_id, name, skill_id, *, session=None):
    if load_tool_denylist(tenant_id, session=session).blocks_skill(name, skill_id):
        raise ResourceBindingError("resource_blocked")


def filter_uninstalled_resources(catalog, tenant_id):
    """Exclude globally blocked Skill and MCP names from installable resources."""
    if not catalog:
        return []
    policy = load_tool_denylist(tenant_id)
    return [item for item in catalog if not (
        item["resource_type"] == "skill" and policy.blocks_skill(item["name"])
        or item["resource_type"] == "mcp_server" and policy.blocks_mcp(item["name"])
    )]


def _editor_state(session, tenant_id):
    global_row = repository.global_config(session)
    global_policy = _global_value(global_row)
    names = global_policy.tool_names
    tools = repository.tool_catalog(session, tenant_id)
    resources = repository.resource_catalog(session, tenant_id)
    services = {item["name"]: item["key"] for item in resources if item["resource_type"] == "mcp"}
    if tenant_id is None:
        row = global_row
        selected = [*names, *global_policy.resource_refs]
        items = [{"key": tool["name"], "name": tool["name"], "resource_type": "tool",
                  "description": tool.get("description") or "", "source": tool.get("source"),
                  "service": tool.get("usage") if tool.get("source") == "mcp" else None,
                  "parent_key": services.get(tool.get("usage")) if tool.get("source") == "mcp" else None}
                 for tool in tools]
    else:
        row = repository.tenant_config(session, tenant_id)
        selected = _tenant_value(row).resource_refs
        items = [
            {"key": f"tool:{tool['tool_id']}", "name": tool["name"],
             "service": tool["usage"] if tool["source"] == "mcp" else None,
             "description": tool.get("description") or "", "resource_type": "tool",
             "source": tool.get("source"),
             "parent_key": services.get(tool.get("usage")) if tool.get("source") == "mcp" else None,
             "global_blocked": tool["name"] in names or (
                 tool["source"] == "mcp" and f"mcp:{tool['usage']}" in global_policy.resource_refs)}
            for tool in tools
        ]
    for resource in resources:
        items.append({**resource, "global_blocked": tenant_id is not None and
                      f"{resource['resource_type']}:{resource['name']}" in global_policy.resource_refs})
    keys = {item["key"] for item in items}
    items.extend({"key": key, "name": key.split(":", 1)[-1], "missing": True,
                  "resource_type": key.split(":", 1)[0] if key.startswith(("mcp:", "skill:")) else "tool"}
                 for key in selected if key not in keys)
    revision = sha256(repr((row.update_time if row else None, sorted(selected),
                           sorted(global_policy.resource_refs), sorted(names))).encode()).hexdigest()
    return row, {"items": items, "selected": selected, "revision": revision}


def read_denylist(tenant_id=None):
    with _editor_session(tenant_id) as session:
        return _editor_state(session, tenant_id)[1]


def _editor_session(tenant_id):
    return configuration_database.session() if tenant_id is None else client.get_db_session()


def update_denylist(payload, actor, tenant_id=None):
    with _editor_session(tenant_id) as session:
        if tenant_id is not None:
            repository.lock_config(session, None)
        repository.lock_config(session, tenant_id)
        row, current = _editor_state(session, tenant_id)
        if payload.revision != current["revision"]:
            raise DenylistConflict("The denylist changed. Reload before saving.")
        old = set(current["selected"])
        if tenant_id is None:
            resources = (payload.resource_refs if payload.resource_refs is not None
                         else [key for key in old if key.startswith(("mcp:", "skill:"))])
            selected = set(payload.tool_names) | set(resources)
        else:
            selected = set(payload.resource_refs)
        available = {item["key"] for item in current["items"] if not item.get("missing")}
        locked = {item["key"] for item in current["items"] if item.get("global_blocked")}
        if (selected - old) - available or (selected ^ old) & locked:
            raise ValueError("The selection contains unavailable or globally blocked tools.")
        if old != selected:
            if tenant_id is None:
                value = GlobalDenylist(
                    tool_names=sorted(key for key in selected if not key.startswith(("mcp:", "skill:"))),
                    resource_refs=sorted(key for key in selected if key.startswith(("mcp:", "skill:"))),
                ).model_dump()
            else:
                value = TenantDenylist(resource_refs=sorted(selected)).model_dump_json()
            repository.save_config(session, tenant_id, row, value, actor)
            session.flush()
        return _editor_state(session, tenant_id)[1]
