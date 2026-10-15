# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Query bound agents and remove deleted knowledge bases from persisted bindings."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Dict, Iterable, List, Sequence, Set, Tuple

from sqlalchemy import String, cast, or_
from sqlalchemy.orm import Session

from consts.const import ASSET_OWNER_TENANT_ID
from database.client import as_dict
from database.db_models import (
    AgentInfo,
    AgentVersion,
    ConversationRecord,
    KnowledgeRecord,
    SkillInfo,
    SkillInstance,
    SkillToolRelation,
    ToolInfo,
    ToolInstance,
)


PROVIDER_LOCAL = "local"
PROVIDER_AIDP = "aidp"
KNOWLEDGE_RANGE_PARAM_BY_TOOL_NAME = {
    "knowledge_base_search": "index_names",
    "aidp_search": "kds_list",
}
RANGE_PARAM_BY_PROVIDER = {PROVIDER_LOCAL: "index_names", PROVIDER_AIDP: "kds_list"}
REFERENCE_ORIGIN_TOOL = "tool"
REFERENCE_ORIGIN_SKILL = "skill"


def _parse_knowledge_ids(value: Any) -> List[str]:
    """Read lists or JSON arrays, as produced by the knowledge selectors."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(
        str(item).strip() for item in value
        if type(item) in (str, int) and str(item).strip()
    ))

def _knowledge_tool_ids(session: Session, param_name: str) -> Set[int]:
    """Return ids of managed retrieval tools whose params may carry ``param_name``."""
    names = [
        name
        for name, mapped_param in KNOWLEDGE_RANGE_PARAM_BY_TOOL_NAME.items()
        if mapped_param == param_name
    ]
    if not names:
        return set()
    rows = (
        session.query(ToolInfo.tool_id)
        .filter(
            ToolInfo.name.in_(tuple(names)),
            ToolInfo.delete_flag != "Y",
        )
        .all()
    )
    return {int(row[0]) for row in rows if row[0] is not None}


def query_tool_instance_reference_rows(
    session: Session,
    provider: str,
    resource_ids: Set[str],
) -> List[Dict[str, Any]]:
    """Return tool instances referencing any requested ID for this provider."""
    param_name = RANGE_PARAM_BY_PROVIDER[provider]
    tool_ids = _knowledge_tool_ids(session, param_name)
    if not tool_ids:
        return []
    instances = (
        session.query(ToolInstance)
        .filter(
            ToolInstance.tool_id.in_(tuple(tool_ids)),
            ToolInstance.delete_flag != "Y",
        )
        .all()
    )
    rows: List[Dict[str, Any]] = []
    for instance in instances:
        data = as_dict(instance) or {}
        params = data.get("params") or {}
        if not isinstance(params, dict):
            continue
        if not resource_ids.intersection(_parse_knowledge_ids(params.get(param_name))):
            continue
        rows.append(
            {
                "agent_id": data.get("agent_id"),
                "version_no": int(data.get("version_no") or 0),
                "reference_origin": REFERENCE_ORIGIN_TOOL,
            }
        )
    return rows


def query_skill_instance_reference_rows(
    session: Session,
    provider: str,
    resource_ids: Set[str],
) -> List[Dict[str, Any]]:
    """Return reference rows injected through enabled skill configurations.

    Mirrors ``_resolve_runtime_tool_records``: the skill template values are
    overridden by the per-agent skill instance values before the merged config
    is applied to every tool listed on the skill.
    """
    param_name = RANGE_PARAM_BY_PROVIDER[provider]
    knowledge_tool_ids = _knowledge_tool_ids(session, param_name)
    if not knowledge_tool_ids:
        return []
    instances = (
        session.query(SkillInstance)
        .filter(SkillInstance.delete_flag != "Y")
        .all()
    )
    if not instances:
        return []
    skill_ids = {int(inst.skill_id) for inst in instances if inst.skill_id is not None}
    if not skill_ids:
        return []
    skills: Dict[int, Dict[str, Any]] = {}
    for skill in (
        session.query(SkillInfo)
        .filter(
            SkillInfo.skill_id.in_(tuple(skill_ids)),
            SkillInfo.delete_flag != "Y",
        )
        .all()
    ):
        skills[int(skill.skill_id)] = as_dict(skill) or {}
    tool_ids_by_skill: Dict[int, Set[int]] = {}
    for skill_id, tool_id in (
        session.query(SkillToolRelation.skill_id, SkillToolRelation.tool_id)
        .filter(SkillToolRelation.skill_id.in_(tuple(skill_ids)))
        .all()
    ):
        tool_ids_by_skill.setdefault(int(skill_id), set()).add(int(tool_id))

    rows: List[Dict[str, Any]] = []
    for instance in instances:
        data = as_dict(instance) or {}
        skill_id = data.get("skill_id")
        if skill_id is None:
            continue
        skill = skills.get(int(skill_id))
        if not skill:
            continue
        if not (tool_ids_by_skill.get(int(skill_id), set()) & knowledge_tool_ids):
            continue
        effective_config: Dict[str, Any] = dict(skill.get("config_values") or {})
        effective_config.update(data.get("config_values") or {})
        if not resource_ids.intersection(_parse_knowledge_ids(effective_config.get(param_name))):
            continue
        rows.append(
            {
                "agent_id": data.get("agent_id"),
                "version_no": int(data.get("version_no") or 0),
                "reference_origin": REFERENCE_ORIGIN_SKILL,
            }
        )
    return rows


def query_reference_rows(session: Session, resources: Sequence[tuple[str, str]]) -> List[Dict[str, Any]]:
    """Return deduplicated reference rows across providers and write paths."""
    rows = []
    for provider in RANGE_PARAM_BY_PROVIDER:
        resource_ids = {resource_id for kind, resource_id in resources if kind == provider}
        if resource_ids:
            rows.extend(query_tool_instance_reference_rows(session, provider, resource_ids))
            rows.extend(query_skill_instance_reference_rows(session, provider, resource_ids))
    deduped: Dict[Tuple[Any, int, str], Dict[str, Any]] = {}
    for row in rows:
        agent_id = row.get("agent_id")
        if agent_id is None:
            continue
        key = (int(agent_id), int(row.get("version_no") or 0), str(row.get("reference_origin")))
        deduped[key] = row
    return list(deduped.values())


def query_live_agent_reference_rows(
    session: Session,
    resources: Sequence[tuple[str, str]],
) -> List[Dict[str, Any]]:
    """Return reference rows whose agent and version still exist undeleted.

    Agent and tool ``enabled`` flags are intentionally ignored: a disabled
    agent or a disabled tool keeps its bindings and therefore still appears
    in the deletion preview.
    """
    rows = query_reference_rows(session, resources)
    if not rows:
        return []
    agent_ids = {int(row["agent_id"]) for row in rows}
    live_agent_keys: Set[Tuple[int, int]] = set()
    for agent_id, version_no in (
        session.query(AgentInfo.agent_id, AgentInfo.version_no)
        .filter(
            AgentInfo.agent_id.in_(tuple(agent_ids)),
            AgentInfo.delete_flag != "Y",
        )
        .all()
    ):
        live_agent_keys.add((int(agent_id), int(version_no or 0)))

    version_pairs = {(aid, vno) for (aid, vno) in live_agent_keys if vno > 0}
    live_version_keys: Set[Tuple[int, int]] = set()
    if version_pairs:
        version_agent_ids = {aid for aid, _ in version_pairs}
        for agent_id, version_no in (
            session.query(AgentVersion.agent_id, AgentVersion.version_no)
            .filter(
                AgentVersion.agent_id.in_(tuple(version_agent_ids)),
                AgentVersion.delete_flag != "Y",
            )
            .all()
        ):
            live_version_keys.add((int(agent_id), int(version_no)))

    live_rows: List[Dict[str, Any]] = []
    for row in rows:
        key = (int(row["agent_id"]), int(row.get("version_no") or 0))
        if key not in live_agent_keys:
            continue
        if key[1] > 0 and key not in live_version_keys:
            continue
        live_rows.append(row)
    return live_rows


def _strip_scope_ids(scope: Any, provider: str, target_ids: Set[str]) -> Tuple[Any, bool]:
    """Remove target ids from a conversation scope payload; report whether it changed.

    An override scope that loses its last item falls back to ``inherit``: the
    persisted model rejects an override with an empty list, and "inherit" is
    the honest meaning of "no conversation-scoped selection anymore".
    """
    if not isinstance(scope, dict):
        return scope, False
    branch_name = "aidp" if provider == PROVIDER_AIDP else "local"
    list_key = "kds_ids" if provider == PROVIDER_AIDP else "knowledge_ids"
    branch = scope.get(branch_name)
    if not isinstance(branch, dict):
        return scope, False
    values = branch.get(list_key)
    if not isinstance(values, list):
        return scope, False
    kept = [item for item in values if str(item) not in target_ids]
    if len(kept) == len(values):
        return scope, False
    updated = deepcopy(scope)
    updated[branch_name][list_key] = kept
    if not kept and updated[branch_name].get("mode") == "override":
        updated[branch_name]["mode"] = "inherit"
    return updated, True


def strip_deleted_resource_from_bindings(
    session: Session, resources: Sequence[tuple[str, str]]
) -> Dict[str, int]:
    """Remove deleted resources from bindings within the caller's transaction.

    The deletion cascades: agent tool instances (draft and published versions),
    skill instances, and conversation scopes all stop referencing the resource
    once it is gone. Skill *template* configs stay untouched on purpose — they
    are shared configuration, and their knowledge references are cleaned where
    an instance actually carries them.
    """
    counts = {"tool_instances": 0, "skill_instances": 0, "conversations": 0}
    targets_by_param: Dict[str, Set[str]] = {}
    for provider, resource_id in resources:
        targets_by_param.setdefault(RANGE_PARAM_BY_PROVIDER[provider], set()).add(resource_id)
    if not targets_by_param:
        return counts
    for param_name, target_ids in targets_by_param.items():
        tool_ids = _knowledge_tool_ids(session, param_name)
        if not tool_ids:
            continue
        instances = (
            session.query(ToolInstance)
            .filter(
                ToolInstance.tool_id.in_(tuple(tool_ids)),
                ToolInstance.delete_flag != "Y",
            )
            .all()
        )
        for instance in instances:
            data = as_dict(instance) or {}
            params = data.get("params") or {}
            if not isinstance(params, dict):
                continue
            current = params.get(param_name)
            ids = _parse_knowledge_ids(current)
            if not target_ids.intersection(ids):
                continue
            names = params.get("display_names")
            aligned_names = (
                list(names)
                if isinstance(names, list) and len(names) == len(ids)
                else None
            )
            kept_ids = [item for item in ids if item not in target_ids]
            updated = dict(params)
            updated[param_name] = (
                json.dumps(kept_ids) if isinstance(current, str) else kept_ids
            )
            if aligned_names is not None:
                updated["display_names"] = [
                    name
                    for item, name in zip(ids, aligned_names)
                    if item not in target_ids
                ]
            instance.params = updated
            counts["tool_instances"] += 1

    for instance in (
        session.query(SkillInstance)
        .filter(SkillInstance.delete_flag != "Y")
        .all()
    ):
        data = as_dict(instance) or {}
        config_values = data.get("config_values") or {}
        if not isinstance(config_values, dict):
            continue
        updated = dict(config_values)
        for param_name, target_ids in targets_by_param.items():
            current = config_values.get(param_name)
            ids = _parse_knowledge_ids(current)
            if not target_ids.intersection(ids):
                continue
            kept_ids = [item for item in ids if item not in target_ids]
            updated[param_name] = json.dumps(kept_ids) if isinstance(current, str) else kept_ids
        if updated != config_values:
            instance.config_values = updated
            counts["skill_instances"] += 1

    counts["conversations"] = _strip_deleted_resource_from_conversation_scopes(
        session, resources
    )

    return counts


def _strip_deleted_resource_from_conversation_scopes(
    session: Session, resources: Sequence[tuple[str, str]]
) -> int:
    """Strip deleted resources from both persisted conversation scope copies.

    Local conversation scopes persist the numeric ``knowledge_id`` while AIDP
    scopes persist the ``kds_id``; both spellings of the target are removed.
    The scope lives on the conversation row twice — as the projected
    ``knowledge_scope`` and inside ``workbench_config`` — and both copies are
    updated so the next workbench save cannot resurrect the stale reference.
    """
    targets_by_provider: Dict[str, Set[str]] = {}
    for provider, resource_id in resources:
        targets_by_provider.setdefault(provider, set()).add(resource_id)
    if not targets_by_provider:
        return 0
    if PROVIDER_LOCAL in targets_by_provider:
        records = (
            session.query(KnowledgeRecord)
            .filter(KnowledgeRecord.index_name.in_(tuple(targets_by_provider[PROVIDER_LOCAL])))
            .all()
        )
        targets_by_provider[PROVIDER_LOCAL].update(
            str(record.knowledge_id) for record in records if record.knowledge_id is not None
        )

    patterns = {f"%{item}%" for ids in targets_by_provider.values() for item in ids}
    filters = []
    for pattern in patterns:
        filters.append(cast(ConversationRecord.knowledge_scope, String).like(pattern))
        filters.append(cast(ConversationRecord.workbench_config, String).like(pattern))
    rows = (
        session.query(ConversationRecord)
        .filter(
            ConversationRecord.delete_flag == "N",
            or_(*filters),
        )
        .all()
    )

    changed = 0
    for record in rows:
        row_changed = False
        scope = record.knowledge_scope
        workbench = deepcopy(record.workbench_config)
        for provider, target_ids in targets_by_provider.items():
            scope, scope_changed = _strip_scope_ids(scope, provider, target_ids)
            row_changed |= scope_changed
            if isinstance(workbench, dict):
                inner_scope, inner_changed = _strip_scope_ids(
                    workbench.get("knowledge_scope"), provider, target_ids
                )
                if inner_changed:
                    workbench["knowledge_scope"] = inner_scope
                    row_changed = True
        if row_changed:
            record.knowledge_scope = scope
            record.workbench_config = workbench
            changed += 1
    return changed


def query_agent_reference_metadata(
    session: Session,
    agent_ids: Iterable[int],
    *,
    tenant_id: str,
) -> Dict[int, Dict[str, Any]]:
    """Return draft metadata within the caller's tenant and shared assets."""
    ids = sorted({int(agent_id) for agent_id in agent_ids})
    if not ids:
        return {}
    rows = (
        session.query(AgentInfo)
        .filter(
            AgentInfo.agent_id.in_(tuple(ids)),
            AgentInfo.tenant_id.in_((tenant_id, ASSET_OWNER_TENANT_ID)),
            AgentInfo.version_no == 0,
            AgentInfo.delete_flag != "Y",
        )
        .all()
    )
    metadata: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        data = as_dict(row) or {}
        metadata[int(data["agent_id"])] = data
    return metadata
