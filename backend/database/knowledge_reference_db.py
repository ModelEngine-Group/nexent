# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Reference queries and advisory locks backing the knowledge-base guards.

The guards answer two questions without any remote call:

* which non-deleted agent configurations reference a knowledge resource, and
* which resource is currently being deleted (cross-process exclusion).

References are stored as opaque JSON params, so candidate rows are narrowed by
managed retrieval tool ids and then matched with an exact id comparison instead
of a substring search.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from consts.error_code import ErrorCode
from consts.exceptions import AppException
from database.client import as_dict, get_db_session
from database.db_models import (
    AgentInfo,
    AgentVersion,
    KnowledgeRecord,
    SkillInfo,
    SkillInstance,
    SkillToolRelation,
    ToolInfo,
    ToolInstance,
)
from utils.knowledge_reference import (
    KNOWLEDGE_RANGE_PARAM_BY_TOOL_NAME,
    REFERENCE_ORIGIN_SKILL,
    REFERENCE_ORIGIN_TOOL,
    KnowledgeResourceRef,
    dedupe_ids,
    parse_knowledge_id_list,
)


logger = logging.getLogger("knowledge_reference_db")

_RESOURCE_LOCK_TIMEOUT_SECONDS = 3.0
_RESOURCE_LOCK_POLL_SECONDS = 0.05


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
    ref: KnowledgeResourceRef,
) -> List[Dict[str, Any]]:
    """Return reference rows persisted in tool instances for one resource."""
    tool_ids = _knowledge_tool_ids(session, ref.range_param)
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
        if ref.resource_id not in parse_knowledge_id_list(params.get(ref.range_param)):
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
    ref: KnowledgeResourceRef,
) -> List[Dict[str, Any]]:
    """Return reference rows injected through enabled skill configurations.

    Mirrors ``_resolve_runtime_tool_records``: the skill template values are
    overridden by the per-agent skill instance values before the merged config
    is applied to every tool listed on the skill.
    """
    knowledge_tool_ids = _knowledge_tool_ids(session, ref.range_param)
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
        if ref.resource_id not in parse_knowledge_id_list(effective_config.get(ref.range_param)):
            continue
        rows.append(
            {
                "agent_id": data.get("agent_id"),
                "version_no": int(data.get("version_no") or 0),
                "reference_origin": REFERENCE_ORIGIN_SKILL,
            }
        )
    return rows


def query_reference_rows(session: Session, ref: KnowledgeResourceRef) -> List[Dict[str, Any]]:
    """Return deduplicated reference rows for one resource across all write paths."""
    rows = [
        *query_tool_instance_reference_rows(session, ref),
        *query_skill_instance_reference_rows(session, ref),
    ]
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
    ref: KnowledgeResourceRef,
) -> List[Dict[str, Any]]:
    """Return reference rows whose agent and version still exist undeleted.

    Agent and tool ``enabled`` flags are intentionally ignored: a disabled
    agent or a disabled tool keeps its persisted configuration and therefore
    still blocks deletion.
    """
    rows = query_reference_rows(session, ref)
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


def query_agent_reference_metadata(
    session: Session,
    agent_ids: Iterable[int],
) -> Dict[int, Dict[str, Any]]:
    """Return draft agent rows (version 0) for the given agent ids."""
    ids = sorted({int(agent_id) for agent_id in agent_ids})
    if not ids:
        return {}
    rows = (
        session.query(AgentInfo)
        .filter(
            AgentInfo.agent_id.in_(tuple(ids)),
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


def query_agent_version_names(
    session: Session,
    keys: Iterable[Tuple[int, int]],
) -> Dict[Tuple[int, int], Optional[str]]:
    """Return version names for non-deleted version rows keyed by (agent_id, version_no)."""
    pairs = sorted({(int(agent_id), int(version_no)) for agent_id, version_no in keys})
    if not pairs:
        return {}
    agent_ids = {agent_id for agent_id, _ in pairs}
    names: Dict[Tuple[int, int], Optional[str]] = {}
    for agent_id, version_no, version_name in (
        session.query(AgentVersion.agent_id, AgentVersion.version_no, AgentVersion.version_name)
        .filter(
            AgentVersion.agent_id.in_(tuple(agent_ids)),
            AgentVersion.delete_flag != "Y",
        )
        .all()
    ):
        names[(int(agent_id), int(version_no))] = version_name
    return {key: names.get(key) for key in pairs}


def query_local_knowledge_records(
    session: Session,
    index_names: Sequence[str],
    *,
    include_deleted: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """Return knowledge records keyed by index name."""
    names = dedupe_ids(index_names)
    if not names:
        return {}
    query = session.query(KnowledgeRecord).filter(KnowledgeRecord.index_name.in_(tuple(names)))
    if not include_deleted:
        query = query.filter(KnowledgeRecord.delete_flag != "Y")
    records: Dict[str, Dict[str, Any]] = {}
    for record in query.all():
        data = as_dict(record) or {}
        index_name = data.get("index_name")
        if not index_name:
            continue
        records[str(index_name)] = data
    return records


def _safe_knowledge_id(value: Any) -> Optional[int]:
    """Return the integer knowledge id of a candidate, or None when invalid.

    ``str.isdigit`` accepts Unicode digits such as "²" that ``int`` rejects,
    and arbitrarily long digit strings exceed Python's conversion limit, so
    candidates are checked with ASCII digits and the database BigInteger range
    before parsing. Invalid candidates keep their per-item not_found result
    instead of failing the whole batch.
    """
    text = str(value).strip()
    if not text or not text.isascii() or not text.isdigit():
        return None
    try:
        parsed = int(text)
    except ValueError:
        return None
    if parsed <= 0 or parsed > 2**63 - 1:
        return None
    return parsed


def query_local_knowledge_records_by_ids(
    session: Session,
    knowledge_ids: Sequence[Any],
) -> Dict[str, Dict[str, Any]]:
    """Return knowledge records keyed by their numeric knowledge id.

    Conversation scopes persist numeric knowledge ids while agent tool params
    persist index names; both must resolve to the same record.
    """
    ids = sorted(
        {
            parsed
            for parsed in (_safe_knowledge_id(value) for value in knowledge_ids)
            if parsed is not None
        }
    )
    if not ids:
        return {}
    records: Dict[str, Dict[str, Any]] = {}
    for record in (
        session.query(KnowledgeRecord)
        .filter(
            KnowledgeRecord.knowledge_id.in_(tuple(ids)),
            KnowledgeRecord.delete_flag != "Y",
        )
        .all()
    ):
        data = as_dict(record) or {}
        knowledge_id = data.get("knowledge_id")
        if knowledge_id is None:
            continue
        records[str(knowledge_id)] = data
    return records


def query_deleted_local_knowledge_ids(
    session: Session,
    index_names: Sequence[str],
) -> Set[str]:
    """Return ids that were confirmed deleted inside this deployment.

    A soft-deleted record proves the resource is gone here, which is stronger
    evidence than "not found" and is used to reject late reference writes.
    """
    names = dedupe_ids(index_names)
    if not names:
        return set()
    rows = (
        session.query(KnowledgeRecord.index_name)
        .filter(
            KnowledgeRecord.index_name.in_(tuple(names)),
            KnowledgeRecord.delete_flag == "Y",
        )
        .all()
    )
    return {str(row[0]) for row in rows if row[0]}


def query_knowledge_tool_params_by_ids(
    session: Session,
    tool_ids: Sequence[int],
) -> Dict[int, str]:
    """Map tool ids to the knowledge range param they persist, if any.

    Used by reference-writing paths that must know whether a given tool can
    introduce a knowledge reference without loading every tool record.
    """
    ids = sorted({int(tool_id) for tool_id in tool_ids})
    if not ids:
        return {}
    rows = (
        session.query(ToolInfo.tool_id, ToolInfo.name)
        .filter(
            ToolInfo.tool_id.in_(tuple(ids)),
            ToolInfo.delete_flag != "Y",
        )
        .all()
    )
    params: Dict[int, str] = {}
    for tool_id, name in rows:
        param_name = KNOWLEDGE_RANGE_PARAM_BY_TOOL_NAME.get(name)
        if tool_id is not None and param_name:
            params[int(tool_id)] = param_name
    return params


def query_deleted_aidp_kb_ids(    session: Session,
    kb_ids: Sequence[str],
    tenant_id: Optional[str] = None,
) -> Set[str]:
    """Return AIDP knowledge ids whose local permission record was soft deleted."""
    from ext_components.aidp.database.aidp_permission_db import AidpKbPermission

    ids = dedupe_ids(kb_ids)
    if not ids:
        return set()
    query = session.query(AidpKbPermission.kb_id).filter(
        AidpKbPermission.kb_id.in_(tuple(ids)),
        AidpKbPermission.delete_flag == "Y",
    )
    if tenant_id:
        query = query.filter(AidpKbPermission.tenant_id == tenant_id)
    rows = query.all()
    return {str(row[0]) for row in rows if row[0]}


@contextmanager
def acquire_lock_keys(
    keys: Iterable[int],
    *,
    timeout_seconds: float = _RESOURCE_LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Hold PostgreSQL session advisory locks for every key in stable order.

    Locks live on a dedicated connection so no transaction stays open while an
    external deletion runs. Multiple resources are locked in ascending key
    order to avoid deadlocks between concurrent multi-resource writers, and a
    bounded wait keeps a stuck holder from hanging unrelated requests.
    """
    sorted_keys = sorted({int(key) for key in keys})
    if not sorted_keys:
        yield
        return
    keys = sorted_keys

    # The session keeps its pooled connection for the whole context, so the
    # session-level advisory locks stay valid without holding an open
    # transaction across the external deletion.
    with get_db_session() as session:
        acquired: List[int] = []
        try:
            deadline = time.monotonic() + max(timeout_seconds, 0.0)
            while True:
                for key in keys:
                    if key in acquired:
                        continue
                    locked = session.execute(
                        text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
                    ).scalar()
                    if locked:
                        acquired.append(key)
                if len(acquired) == len(keys):
                    break
                if time.monotonic() >= deadline:
                    raise AppException(
                        ErrorCode.KNOWLEDGE_RESOURCE_BUSY,
                        "The knowledge base is busy with another operation; try again later",
                        details={"remaining_locks": len(keys) - len(acquired)},
                    )
                time.sleep(_RESOURCE_LOCK_POLL_SECONDS)
            yield
        finally:
            for key in acquired:
                try:
                    session.execute(
                        text("SELECT pg_advisory_unlock(:key)"), {"key": key}
                    )
                except Exception:
                    logger.warning(
                        "Failed to release knowledge resource lock %s; it is released when the connection closes",
                        key,
                    )
