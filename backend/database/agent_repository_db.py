import logging
import math
from typing import Any, Collection, Dict, List, Optional

from sqlalchemy import and_, case, false, func, or_, true, update

from consts.const import (
    CAN_EDIT_ALL_USER_ROLES,
    PERMISSION_EDIT,
)
from database.client import as_dict, filter_property, get_db_session
from database.db_models import AgentInfo, AgentRepository, AgentVersion
from database.group_db import query_group_ids_by_user

logger = logging.getLogger("agent_repository_db")

# Listing status: not_shared (未共享), pending_review (待审核),
# rejected (审核驳回), shared (已共享)
STATUS_NOT_SHARED = "not_shared"
STATUS_PENDING_REVIEW = "pending_review"
STATUS_REJECTED = "rejected"
STATUS_SHARED = "shared"

VALID_REPOSITORY_STATUSES = frozenset({
    STATUS_NOT_SHARED,
    STATUS_PENDING_REVIEW,
    STATUS_REJECTED,
    STATUS_SHARED,
})

OWNERSHIP_ALL = "all"
OWNERSHIP_CREATED = "created"
OWNERSHIP_OTHERS = "others"

VALID_OWNERSHIP_FILTERS = frozenset({
    OWNERSHIP_ALL,
    OWNERSHIP_CREATED,
    OWNERSHIP_OTHERS,
})

_UPSERT_IMMUTABLE_FIELDS = frozenset({
    "agent_id",
    "agent_repository_id",
    "publisher_tenant_id",
})

_UPSERT_SNAPSHOT_FIELDS = frozenset({
    "version_no",
    "name",
    "display_name",
    "description",
    "author",
    "category_id",
    "tags",
    "tool_count",
    "version_name",
    "icon",
    "downloads",
    "agent_info_json",
})


def insert_agent_repository_record(
    repository_data: Dict[str, Any],
    publisher_tenant_id: str,
    publisher_user_id: str,
) -> int:
    """Insert a new agent repository listing record."""
    with get_db_session() as session:
        payload = {
            **repository_data,
            "publisher_tenant_id": publisher_tenant_id,
            "publisher_user_id": publisher_user_id,
            "created_by": publisher_user_id,
            "updated_by": publisher_user_id,
            "delete_flag": "N",
        }
        if payload.get("status") is None:
            payload["status"] = STATUS_NOT_SHARED

        new_record = AgentRepository(
            **filter_property(payload, AgentRepository)
        )
        session.add(new_record)
        session.flush()
        return int(new_record.agent_repository_id)


def get_agent_repository_by_id(repository_id: int) -> Optional[dict]:
    """Fetch a repository listing by primary key."""
    with get_db_session() as session:
        record = session.query(AgentRepository).filter(
            AgentRepository.agent_repository_id == repository_id,
            AgentRepository.delete_flag != "Y",
        ).first()
        return as_dict(record) if record else None


def get_agent_repository_by_id_and_publisher(
    repository_id: int,
    publisher_tenant_id: str,
) -> Optional[dict]:
    """Fetch a repository listing scoped to the publisher tenant."""
    with get_db_session() as session:
        record = session.query(AgentRepository).filter(
            AgentRepository.agent_repository_id == repository_id,
            AgentRepository.publisher_tenant_id == publisher_tenant_id,
            AgentRepository.delete_flag != "Y",
        ).first()
        return as_dict(record) if record else None


def get_agent_repository_by_agent_id(
    agent_id: int,
    version_no: Optional[int] = None,
) -> Optional[dict]:
    """Fetch an active repository listing by root agent_id and optional version."""
    with get_db_session() as session:
        query = session.query(AgentRepository).filter(
            AgentRepository.agent_id == agent_id,
            AgentRepository.delete_flag != "Y",
        )
        if version_no is not None:
            query = query.filter(
                AgentRepository.version_no == version_no
            )
        record = query.first()
        return as_dict(record) if record else None


def upsert_agent_repository_record(
    repository_data: Dict[str, Any],
    publisher_tenant_id: str,
    publisher_user_id: str,
) -> tuple[int, bool]:
    """Insert or update a repository listing keyed by agent_id.

    When no record exists, inserts a new listing. When a record exists:
    - Same version_no: updates status (and updated_by) only.
    - Different version_no: updates all snapshot fields, preserving
      agent_id, agent_repository_id, and publisher_tenant_id.

    Returns:
        Tuple of (agent_repository_id, is_updated). is_updated is False on insert.
    """
    agent_id = repository_data.get("agent_id")
    if agent_id is None:
        raise ValueError("agent_id is required for repository upsert")

    existing = get_agent_repository_by_agent_id(int(agent_id))
    if not existing:
        repository_id = insert_agent_repository_record(
            repository_data=repository_data,
            publisher_tenant_id=publisher_tenant_id,
            publisher_user_id=publisher_user_id,
        )
        return repository_id, False

    existing_version = existing.get("version_no")
    incoming_version = repository_data.get("version_no")
    repository_id = int(existing["agent_repository_id"])

    if existing_version == incoming_version:
        update_fields: Dict[str, Any] = {
            "status": repository_data.get("status", STATUS_NOT_SHARED),
            "updated_by": publisher_user_id,
        }
    else:
        update_fields = {
            key: repository_data[key]
            for key in _UPSERT_SNAPSHOT_FIELDS
            if key in repository_data
        }
        update_fields["publisher_user_id"] = publisher_user_id
        update_fields["updated_by"] = publisher_user_id
        update_fields["status"] = repository_data.get("status", STATUS_NOT_SHARED)

    with get_db_session() as session:
        session.execute(
            update(AgentRepository)
            .where(
                AgentRepository.agent_repository_id == repository_id,
                AgentRepository.publisher_tenant_id == publisher_tenant_id,
                AgentRepository.delete_flag != "Y",
            )
            .values(**update_fields)
        )
    return repository_id, True


def list_agent_repository_summaries(
    *,
    status: Optional[str] = None,
    agent_id: Optional[int] = None,
    category_id: Optional[int] = None,
) -> List[dict]:
    """List all active repository summaries without heavy JSON blobs."""
    with get_db_session() as session:
        query = session.query(
            AgentRepository.agent_repository_id,
            AgentRepository.agent_id,
            AgentRepository.author,
            AgentRepository.submitted_by,
            AgentRepository.name,
            AgentRepository.display_name,
            AgentRepository.description,
            AgentRepository.status,
            AgentRepository.category_id,
            AgentRepository.tags,
            AgentRepository.tool_count,
            AgentRepository.version_name,
            AgentRepository.icon,
            AgentRepository.downloads,
        ).filter(
            AgentRepository.delete_flag != "Y",
        )
        if status:
            query = query.filter(AgentRepository.status == status)
        if agent_id is not None:
            query = query.filter(AgentRepository.agent_id == agent_id)
        if category_id is not None:
            query = query.filter(AgentRepository.category_id == category_id)
        rows = query.order_by(AgentRepository.agent_repository_id.desc()).all()
        return [
            {
                "agent_repository_id": row.agent_repository_id,
                "agent_id": row.agent_id,
                "author": row.author,
                "submitted_by": row.submitted_by,
                "name": row.name,
                "display_name": row.display_name,
                "description": row.description,
                "status": row.status,
                "category_id": row.category_id,
                "tags": row.tags,
                "tool_count": row.tool_count,
                "version_name": row.version_name,
                "icon": row.icon,
                "downloads": row.downloads,
            }
            for row in rows
        ]


def update_agent_repository_by_id(
    *,
    repository_id: int,
    publisher_tenant_id: str,
    user_id: str,
    updates: Dict[str, Any],
) -> int:
    """Update a repository listing owned by the publisher tenant. Returns affected row count."""
    allowed_fields = {
        "display_name",
        "description",
        "author",
        "submitted_by",
        "category_id",
        "tags",
        "tool_count",
        "version_name",
        "icon",
        "downloads",
        "version_no",
        "agent_info_json",
        "status",
    }
    update_fields = {
        key: value
        for key, value in updates.items()
        if key in allowed_fields
    }
    if not update_fields:
        return 0

    update_fields["updated_by"] = user_id

    with get_db_session() as session:
        result = session.execute(
            update(AgentRepository)
            .where(
                AgentRepository.agent_repository_id == repository_id,
                AgentRepository.publisher_tenant_id == publisher_tenant_id,
                AgentRepository.delete_flag != "Y",
            )
            .values(**update_fields)
        )
        return int(result.rowcount or 0)


def update_agent_repository_status_by_id(
    *,
    repository_id: int,
    status: str,
    user_id: str,
    publisher_tenant_id: Optional[str] = None,
    publisher_user_id: Optional[str] = None,
    submitted_by: Optional[str] = None,
) -> int:
    """Update repository listing status by primary key. Returns affected row count."""
    update_values: Dict[str, Any] = {
        "status": status,
        "updated_by": user_id,
    }
    if publisher_tenant_id is not None:
        update_values["publisher_tenant_id"] = publisher_tenant_id
    if publisher_user_id is not None:
        update_values["publisher_user_id"] = publisher_user_id
    if submitted_by is not None:
        update_values["submitted_by"] = submitted_by

    with get_db_session() as session:
        result = session.execute(
            update(AgentRepository)
            .where(
                AgentRepository.agent_repository_id == repository_id,
                AgentRepository.delete_flag != "Y",
            )
            .values(**update_values)
        )
        return int(result.rowcount or 0)


def reset_agent_repository_status(
    *,
    agent_repository_id: int,
    agent_id: int,
    status: str,
) -> int:
    """Set other active listings with the same agent and status to not_shared."""
    with get_db_session() as session:
        result = session.execute(
            update(AgentRepository)
            .where(
                AgentRepository.agent_id == agent_id,
                AgentRepository.status == status,
                AgentRepository.agent_repository_id != agent_repository_id,
                AgentRepository.delete_flag != "Y",
            )
            .values(status=STATUS_NOT_SHARED)
        )
        return int(result.rowcount or 0)


def soft_delete_agent_repository_by_id(
    *,
    repository_id: int,
    publisher_tenant_id: str,
    user_id: str,
) -> int:
    """Soft-delete a repository listing owned by the publisher tenant."""
    with get_db_session() as session:
        result = session.execute(
            update(AgentRepository)
            .where(
                AgentRepository.agent_repository_id == repository_id,
                AgentRepository.publisher_tenant_id == publisher_tenant_id,
                AgentRepository.delete_flag != "Y",
            )
            .values(delete_flag="Y", updated_by=user_id)
        )
        return int(result.rowcount or 0)


def list_agent_repository_by_publisher(
    publisher_tenant_id: str,
    *,
    publisher_user_id: Optional[str] = None,
) -> List[dict]:
    """List all repository listings published by a tenant."""
    with get_db_session() as session:
        query = session.query(AgentRepository).filter(
            AgentRepository.publisher_tenant_id == publisher_tenant_id,
            AgentRepository.delete_flag != "Y",
        )
        if publisher_user_id:
            query = query.filter(
                AgentRepository.publisher_user_id == publisher_user_id
            )
        rows = query.order_by(AgentRepository.agent_repository_id.desc()).all()
        return [as_dict(row) for row in rows]


def _build_group_ids_overlap_condition(user_group_ids: set[int]):
    """Build SQL condition for CSV group_ids overlapping user_group_ids."""
    if not user_group_ids:
        return false()
    padded = func.concat(",", AgentInfo.group_ids, ",")
    return or_(*(padded.like(f"%,{gid},%") for gid in user_group_ids))


def _build_editable_agent_filter(
    user_id: str,
    *,
    can_edit_all: bool,
    user_group_ids: set[int],
):
    """Build SQL WHERE clause for agents the user can edit."""
    if can_edit_all:
        return true()
    group_overlap = _build_group_ids_overlap_condition(user_group_ids)
    return or_(
        AgentInfo.created_by == user_id,
        and_(
            AgentInfo.ingroup_permission == PERMISSION_EDIT,
            group_overlap,
        ),
    )


def _resolve_editable_agent_access(
    user_id: str,
    user_role: str,
) -> tuple[bool, set[int], Any]:
    """Resolve role-based edit access and the editable-agent SQL filter."""
    role = (user_role or "").upper()
    can_edit_all = role in CAN_EDIT_ALL_USER_ROLES
    user_group_ids: set[int] = set()
    if not can_edit_all:
        user_group_ids = set(query_group_ids_by_user(user_id) or [])
    editable_filter = _build_editable_agent_filter(
        user_id,
        can_edit_all=can_edit_all,
        user_group_ids=user_group_ids,
    )
    return can_edit_all, user_group_ids, editable_filter


def _build_ownership_filter(user_id: str, ownership_filter: str):
    """Build SQL WHERE clause for mine-tab ownership filtering."""
    if ownership_filter == OWNERSHIP_CREATED:
        return AgentInfo.created_by == user_id
    if ownership_filter == OWNERSHIP_OTHERS:
        return or_(
            AgentInfo.created_by != user_id,
            AgentInfo.created_by.is_(None),
        )
    return true()


def _build_editable_agent_base_filters(
    tenant_id: str,
    editable_filter: Any,
) -> tuple[Any, ...]:
    """Shared base filters for editable draft agents in a tenant."""
    return (
        AgentInfo.tenant_id == tenant_id,
        AgentInfo.version_no == 0,
        AgentInfo.delete_flag != "Y",
        AgentInfo.enabled.is_(True),
        editable_filter,
    )


def list_agent_repository_by_agent_ids(
    agent_ids: List[int],
    *,
    statuses: Collection[str],
    publisher_tenant_id: str,
) -> List[dict]:
    """List repository rows for the given agents, scoped to publisher tenant and statuses."""
    if not agent_ids:
        return []

    status_list = list(statuses)
    with get_db_session() as session:
        rows = (
            session.query(
                AgentRepository.agent_repository_id,
                AgentRepository.agent_id,
                AgentRepository.status,
                AgentRepository.version_no,
                AgentRepository.version_name,
                AgentRepository.create_time,
            )
            .filter(
                AgentRepository.delete_flag != "Y",
                AgentRepository.publisher_tenant_id == publisher_tenant_id,
                AgentRepository.agent_id.in_(agent_ids),
                AgentRepository.status.in_(status_list),
            )
            .order_by(
                AgentRepository.agent_id,
                AgentRepository.create_time.desc(),
            )
            .all()
        )

    return [
        {
            "agent_repository_id": row.agent_repository_id,
            "agent_id": row.agent_id,
            "status": row.status,
            "version_no": row.version_no,
            "version_name": row.version_name,
            "create_time": row.create_time,
        }
        for row in rows
    ]


def list_editable_agents_for_user(
    tenant_id: str,
    user_id: str,
    *,
    user_role: str,
    ownership_filter: str = OWNERSHIP_ALL,
) -> List[dict]:
    """List draft agents in a tenant that the user can edit.

    Queries version_no=0 rows and returns agent_id, name, display_name, description,
    current_version_no, and the current published version_name and create_time
    (via LEFT JOIN on ag_tenant_agent_version_t) for agents where permission resolves to EDIT.
    """
    _, _, editable_filter = _resolve_editable_agent_access(user_id, user_role)
    ownership_clause = _build_ownership_filter(user_id, ownership_filter)

    with get_db_session() as session:
        rows = (
            session.query(
                AgentInfo.agent_id,
                AgentInfo.name,
                AgentInfo.display_name,
                AgentInfo.description,
                AgentInfo.current_version_no,
                AgentInfo.created_by,
                AgentVersion.version_name,
                AgentVersion.create_time,
            )
            .outerjoin(
                AgentVersion,
                and_(
                    AgentInfo.agent_id == AgentVersion.agent_id,
                    AgentInfo.current_version_no == AgentVersion.version_no,
                    AgentInfo.tenant_id == AgentVersion.tenant_id,
                    AgentVersion.delete_flag == "N",
                ),
            )
            .filter(
                *_build_editable_agent_base_filters(tenant_id, editable_filter),
                ownership_clause,
            )
            .order_by(AgentInfo.create_time.desc())
            .all()
        )

    return [
        {
            "agent_id": row.agent_id,
            "name": row.name,
            "display_name": row.display_name,
            "description": row.description,
            "current_version_no": row.current_version_no,
            "created_by": row.created_by,
            "version_name": row.version_name,
            "version_create_time": row.create_time,
        }
        for row in rows
    ]


def count_editable_agents_by_ownership(
    tenant_id: str,
    user_id: str,
    *,
    user_role: str,
) -> Dict[str, int]:
    """Count editable draft agents grouped by ownership for mine-tab badges."""
    _, _, editable_filter = _resolve_editable_agent_access(user_id, user_role)
    created_case = case(
        (AgentInfo.created_by == user_id, 1),
        else_=0,
    )
    others_case = case(
        (
            or_(
                AgentInfo.created_by != user_id,
                AgentInfo.created_by.is_(None),
            ),
            1,
        ),
        else_=0,
    )

    with get_db_session() as session:
        row = (
            session.query(
                func.count(AgentInfo.agent_id),
                func.coalesce(func.sum(created_case), 0),
                func.coalesce(func.sum(others_case), 0),
            )
            .filter(*_build_editable_agent_base_filters(tenant_id, editable_filter))
            .one()
        )

    return {
        "all": int(row[0] or 0),
        "created": int(row[1] or 0),
        "others": int(row[2] or 0),
    }
