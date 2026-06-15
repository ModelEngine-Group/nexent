import logging
import math
from typing import Any, Dict, List, Optional

from sqlalchemy import func, or_, update

from database.client import as_dict, filter_property, get_db_session
from database.db_models import AgentRepository

logger = logging.getLogger("agent_repository_db")

# Listing status: NOT_SHARED (未共享), PENDING_REVIEW (待审核),
# REJECTED (审核驳回), SHARED (已共享)
STATUS_NOT_SHARED = "NOT_SHARED"
STATUS_PENDING_REVIEW = "PENDING_REVIEW"
STATUS_REJECTED = "REJECTED"
STATUS_SHARED = "SHARED"

VALID_REPOSITORY_STATUSES = frozenset({
    STATUS_NOT_SHARED,
    STATUS_PENDING_REVIEW,
    STATUS_REJECTED,
    STATUS_SHARED,
})

_UPSERT_IMMUTABLE_FIELDS = frozenset({
    "agent_id",
    "agent_repository_id",
    "publisher_tenant_id",
})

_UPSERT_SNAPSHOT_FIELDS = frozenset({
    "source_version_no",
    "name",
    "display_name",
    "description",
    "author",
    "category_id",
    "tags",
    "tool_count",
    "version_label",
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


def get_agent_repository_by_agent_id(agent_id: int) -> Optional[dict]:
    """Fetch an active repository listing by root agent_id."""
    with get_db_session() as session:
        record = session.query(AgentRepository).filter(
            AgentRepository.agent_id == agent_id,
            AgentRepository.delete_flag != "Y",
        ).first()
        return as_dict(record) if record else None


def upsert_agent_repository_record(
    repository_data: Dict[str, Any],
    publisher_tenant_id: str,
    publisher_user_id: str,
) -> tuple[int, bool]:
    """Insert or update a repository listing keyed by agent_id.

    When no record exists, inserts a new listing. When a record exists:
    - Same source_version_no: updates status (and updated_by) only.
    - Different source_version_no: updates all snapshot fields, preserving
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

    existing_version = existing.get("source_version_no")
    incoming_version = repository_data.get("source_version_no")
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
) -> List[dict]:
    """List all active repository summaries without heavy JSON blobs."""
    with get_db_session() as session:
        query = session.query(
            AgentRepository.agent_repository_id,
            AgentRepository.author,
            AgentRepository.name,
            AgentRepository.display_name,
            AgentRepository.description,
            AgentRepository.status,
        ).filter(
            AgentRepository.delete_flag != "Y",
        )
        if status:
            query = query.filter(AgentRepository.status == status)
        rows = query.order_by(AgentRepository.agent_repository_id.desc()).all()
        return [
            {
                "agent_repository_id": row.agent_repository_id,
                "author": row.author,
                "name": row.name,
                "display_name": row.display_name,
                "description": row.description,
                "status": row.status,
            }
            for row in rows
        ]


def query_agent_repository_list(
    *,
    page: int = 1,
    page_size: int = 20,
    search: Optional[str] = None,
    tag: Optional[str] = None,
    category_id: Optional[int] = None,
    status: Optional[str] = STATUS_SHARED,
    publisher_tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Query repository listings with offset pagination."""
    page = max(page, 1)
    page_size = max(min(page_size, 100), 1)
    offset = (page - 1) * page_size

    with get_db_session() as session:
        query = session.query(AgentRepository).filter(
            AgentRepository.delete_flag != "Y",
        )

        if status:
            query = query.filter(AgentRepository.status == status)
        if publisher_tenant_id:
            query = query.filter(
                AgentRepository.publisher_tenant_id == publisher_tenant_id
            )
        if category_id is not None:
            query = query.filter(AgentRepository.category_id == category_id)
        if tag:
            query = query.filter(AgentRepository.tags.any(tag))
        if search:
            keyword = f"%{search}%"
            query = query.filter(
                or_(
                    AgentRepository.name.ilike(keyword),
                    AgentRepository.display_name.ilike(keyword),
                    AgentRepository.description.ilike(keyword),
                    AgentRepository.author.ilike(keyword),
                    func.array_to_string(AgentRepository.tags, ",").ilike(keyword),
                )
            )

        total = query.count()
        rows = (
            query.order_by(AgentRepository.agent_repository_id.desc())
            .offset(offset)
            .limit(page_size)
            .all()
        )

        total_pages = math.ceil(total / page_size) if total else 0
        return {
            "items": [as_dict(row) for row in rows],
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": total_pages,
            },
        }


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
        "category_id",
        "tags",
        "tool_count",
        "version_label",
        "source_version_no",
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
) -> int:
    """Update repository listing status by primary key. Returns affected row count."""
    with get_db_session() as session:
        result = session.execute(
            update(AgentRepository)
            .where(
                AgentRepository.agent_repository_id == repository_id,
                AgentRepository.delete_flag != "Y",
            )
            .values(status=status, updated_by=user_id)
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
