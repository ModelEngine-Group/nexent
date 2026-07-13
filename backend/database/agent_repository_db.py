from typing import Any, Collection, Dict, List, Optional

from sqlalchemy import and_, case, false, func, or_, true, update

from consts.agent_repository import (
    OWNERSHIP_ALL,
    OWNERSHIP_CREATED,
    OWNERSHIP_OTHERS,
    STATUS_NOT_SHARED,
)
from consts.const import (
    CAN_EDIT_ALL_USER_ROLES,
    PERMISSION_EDIT,
)
from database.client import as_dict, filter_property, get_db_session
from database.db_models import AgentInfo, AgentRepository, AgentVersion
from database.group_db import query_group_ids_by_user

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
    *,
    publisher_tenant_id: Optional[str] = None,
) -> Optional[dict]:
    """Fetch an active repository listing by root agent_id and optional version."""
    with get_db_session() as session:
        query = session.query(AgentRepository).filter(
            AgentRepository.agent_id == agent_id,
            AgentRepository.delete_flag != "Y",
        )
        if publisher_tenant_id is not None:
            query = query.filter(
                AgentRepository.publisher_tenant_id == publisher_tenant_id,
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

    existing = get_agent_repository_by_agent_id(
        int(agent_id),
        publisher_tenant_id=publisher_tenant_id,
    )
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
    publisher_tenant_id: str,
    *,
    status: Optional[str] = None,
    agent_id: Optional[int] = None,
) -> List[dict]:
    """List active repository summaries for a publisher tenant without heavy JSON blobs."""
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
            AgentRepository.tags,
            AgentRepository.tool_count,
            AgentRepository.version_name,
            AgentRepository.icon,
            AgentRepository.downloads,
        ).filter(
            AgentRepository.delete_flag != "Y",
            AgentRepository.publisher_tenant_id == publisher_tenant_id,
        )
        if status:
            query = query.filter(AgentRepository.status == status)
        if agent_id is not None:
            query = query.filter(AgentRepository.agent_id == agent_id)
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
    filter_publisher_tenant_id: Optional[str] = None,
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
        where_clauses = [
            AgentRepository.agent_repository_id == repository_id,
            AgentRepository.delete_flag != "Y",
        ]
        if filter_publisher_tenant_id is not None:
            where_clauses.append(
                AgentRepository.publisher_tenant_id == filter_publisher_tenant_id
            )
        result = session.execute(
            update(AgentRepository)
            .where(*where_clauses)
            .values(**update_values)
        )
        return int(result.rowcount or 0)


def reset_agent_repository_status(
    *,
    agent_repository_id: int,
    agent_id: int,
    status: str,
    publisher_tenant_id: str,
) -> int:
    """Set other active listings with the same agent and status to not_shared."""
    with get_db_session() as session:
        result = session.execute(
            update(AgentRepository)
            .where(
                AgentRepository.agent_id == agent_id,
                AgentRepository.status == status,
                AgentRepository.agent_repository_id != agent_repository_id,
                AgentRepository.publisher_tenant_id == publisher_tenant_id,
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


def increment_agent_repository_downloads(agent_repository_id: int) -> int:
    """Increment download count for an active repository listing."""
    with get_db_session() as session:
        result = session.execute(
            update(AgentRepository)
            .where(
                AgentRepository.agent_repository_id == agent_repository_id,
                AgentRepository.delete_flag != "Y",
            )
            .values(downloads=func.coalesce(AgentRepository.downloads, 0) + 1)
        )
        return int(result.rowcount or 0)


def sum_agent_repository_downloads_by_agent_ids(
    agent_ids: List[int],
) -> Dict[int, int]:
    """Sum downloads across all repository rows for each agent_id.

    Includes soft-deleted rows and does not filter by status or publisher.
    """
    if not agent_ids:
        return {}

    with get_db_session() as session:
        rows = (
            session.query(
                AgentRepository.agent_id,
                func.coalesce(func.sum(AgentRepository.downloads), 0).label(
                    "total_downloads"
                ),
            )
            .filter(AgentRepository.agent_id.in_(agent_ids))
            .group_by(AgentRepository.agent_id)
            .all()
        )

    return {int(row.agent_id): int(row.total_downloads) for row in rows}


def fetch_draft_agent_mine_metadata(
    tenant_id: str,
    agent_ids: List[int],
) -> Dict[int, dict]:
    """Batch-fetch draft agent fields needed by the mine tab.

    Returns a map of agent_id to created_by, current_version_no, version_name,
    and version_create_time (from the published version row when present).
    """
    if not agent_ids:
        return {}

    with get_db_session() as session:
        rows = (
            session.query(
                AgentInfo.agent_id,
                AgentInfo.created_by,
                AgentInfo.current_version_no,
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
                AgentInfo.tenant_id == tenant_id,
                AgentInfo.version_no == 0,
                AgentInfo.delete_flag != "Y",
                AgentInfo.enabled.is_(True),
                AgentInfo.agent_id.in_(agent_ids),
            )
            .all()
        )

    return {
        int(row.agent_id): {
            "created_by": row.created_by,
            "current_version_no": row.current_version_no,
            "version_name": row.version_name,
            "version_create_time": row.create_time,
        }
        for row in rows
    }

