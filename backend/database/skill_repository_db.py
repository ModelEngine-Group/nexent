import math
from typing import Any, Collection, Dict, List, Optional

from sqlalchemy import func, or_, update

from consts.agent_repository import STATUS_NOT_SHARED
from database.client import as_dict, filter_property, get_db_session
from database.db_models import SkillRepository

_UPDATE_ALLOWED_FIELDS = frozenset({
    "name",
    "description",
    "source",
    "submitted_by",
    "category_id",
    "tags",
    "icon",
    "downloads",
    "skill_info_json",
    "skill_zip_base64",
    "status",
})


def insert_skill_repository_record(
    repository_data: Dict[str, Any],
    publisher_tenant_id: str,
    publisher_user_id: str,
) -> int:
    """Insert a new skill repository listing record."""
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

        new_record = SkillRepository(
            **filter_property(payload, SkillRepository)
        )
        session.add(new_record)
        session.flush()
        return int(new_record.skill_repository_id)


def get_skill_repository_by_id_and_publisher(
    repository_id: int,
    publisher_tenant_id: str,
) -> Optional[dict]:
    """Fetch a repository listing scoped to the publisher tenant."""
    with get_db_session() as session:
        record = session.query(SkillRepository).filter(
            SkillRepository.skill_repository_id == repository_id,
            SkillRepository.publisher_tenant_id == publisher_tenant_id,
            SkillRepository.delete_flag != "Y",
        ).first()
        return as_dict(record) if record else None


def get_skill_repository_by_skill_id(
    skill_id: int,
    *,
    publisher_tenant_id: Optional[str] = None,
    statuses: Optional[Collection[str]] = None,
) -> Optional[dict]:
    """Fetch an active repository listing by source skill_id."""
    with get_db_session() as session:
        query = session.query(SkillRepository).filter(
            SkillRepository.skill_id == skill_id,
            SkillRepository.delete_flag != "Y",
        )
        if publisher_tenant_id is not None:
            query = query.filter(
                SkillRepository.publisher_tenant_id == publisher_tenant_id,
            )
        if statuses is not None:
            query = query.filter(SkillRepository.status.in_(list(statuses)))
        record = query.order_by(SkillRepository.update_time.desc()).first()
        return as_dict(record) if record else None


def _apply_skill_repository_filters(
    query,
    *,
    publisher_tenant_id: str,
    status: Optional[str],
    skill_id: Optional[int],
    category_id: Optional[int],
    search: Optional[str],
):
    query = query.filter(
        SkillRepository.delete_flag != "Y",
        SkillRepository.publisher_tenant_id == publisher_tenant_id,
    )
    if status:
        query = query.filter(SkillRepository.status == status)
    if skill_id is not None:
        query = query.filter(SkillRepository.skill_id == skill_id)
    if category_id is not None:
        query = query.filter(SkillRepository.category_id == category_id)

    keyword = (search or "").strip()
    if keyword:
        pattern = f"%{keyword}%"
        query = query.filter(or_(
            SkillRepository.name.ilike(pattern),
            SkillRepository.description.ilike(pattern),
            SkillRepository.source.ilike(pattern),
            SkillRepository.submitted_by.ilike(pattern),
            func.array_to_string(SkillRepository.tags, " ").ilike(pattern),
        ))
    return query


def list_skill_repository_summaries(
    publisher_tenant_id: str,
    *,
    status: Optional[str] = None,
    skill_id: Optional[int] = None,
    category_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 10,
    search: Optional[str] = None,
    sort_by_update_time: bool = False,
) -> Dict[str, Any]:
    """List active repository summaries for a publisher tenant without heavy payloads."""
    safe_page = max(int(page or 1), 1)
    safe_page_size = max(int(page_size or 10), 1)

    with get_db_session() as session:
        query = session.query(
            SkillRepository.skill_repository_id,
            SkillRepository.skill_id,
            SkillRepository.publisher_user_id,
            SkillRepository.submitted_by,
            SkillRepository.name,
            SkillRepository.description,
            SkillRepository.source,
            SkillRepository.status,
            SkillRepository.category_id,
            SkillRepository.tags,
            SkillRepository.icon,
            SkillRepository.downloads,
            SkillRepository.create_time,
        )
        query = _apply_skill_repository_filters(
            query,
            publisher_tenant_id=publisher_tenant_id,
            status=status,
            skill_id=skill_id,
            category_id=category_id,
            search=search,
        )

        total = query.count()
        order_by_fields = (
            (SkillRepository.update_time.desc(),
             SkillRepository.skill_repository_id.desc())
            if sort_by_update_time
            else (SkillRepository.skill_repository_id.desc(),)
        )
        rows = (
            query.order_by(*order_by_fields)
            .offset((safe_page - 1) * safe_page_size)
            .limit(safe_page_size)
            .all()
        )

    items = [
        {
            "skill_repository_id": row.skill_repository_id,
            "skill_id": row.skill_id,
            "publisher_user_id": row.publisher_user_id,
            "submitted_by": row.submitted_by,
            "name": row.name,
            "description": row.description,
            "source": row.source,
            "status": row.status,
            "category_id": row.category_id,
            "tags": row.tags or [],
            "icon": row.icon,
            "downloads": row.downloads or 0,
            "created_at": row.create_time.isoformat() if row.create_time else None,
        }
        for row in rows
    ]
    return {
        "items": items,
        "pagination": {
            "page": safe_page,
            "page_size": safe_page_size,
            "total": total,
            "total_pages": math.ceil(total / safe_page_size) if total else 0,
        },
    }


def update_skill_repository_by_id(
    *,
    repository_id: int,
    publisher_tenant_id: str,
    user_id: str,
    updates: Dict[str, Any],
) -> int:
    """Update a repository listing owned by the publisher tenant. Returns affected row count."""
    update_fields = {
        key: value
        for key, value in updates.items()
        if key in _UPDATE_ALLOWED_FIELDS
    }
    if not update_fields:
        return 0

    update_fields["updated_by"] = user_id

    with get_db_session() as session:
        result = session.execute(
            update(SkillRepository)
            .where(
                SkillRepository.skill_repository_id == repository_id,
                SkillRepository.publisher_tenant_id == publisher_tenant_id,
                SkillRepository.delete_flag != "Y",
            )
            .values(**update_fields)
        )
        return int(result.rowcount or 0)


def update_skill_repository_status_by_id(
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
            SkillRepository.skill_repository_id == repository_id,
            SkillRepository.delete_flag != "Y",
        ]
        if filter_publisher_tenant_id is not None:
            where_clauses.append(
                SkillRepository.publisher_tenant_id == filter_publisher_tenant_id
            )
        result = session.execute(
            update(SkillRepository)
            .where(*where_clauses)
            .values(**update_values)
        )
        return int(result.rowcount or 0)


def reset_skill_repository_status(
    *,
    repository_id: int,
    skill_id: int,
    status: str,
    publisher_tenant_id: str,
) -> int:
    """Set other active listings with the same skill and status to not_shared."""
    with get_db_session() as session:
        result = session.execute(
            update(SkillRepository)
            .where(
                SkillRepository.skill_id == skill_id,
                SkillRepository.status == status,
                SkillRepository.skill_repository_id != repository_id,
                SkillRepository.publisher_tenant_id == publisher_tenant_id,
                SkillRepository.delete_flag != "Y",
            )
            .values(status=STATUS_NOT_SHARED)
        )
        return int(result.rowcount or 0)


def increment_skill_repository_downloads(
    *,
    repository_id: int,
    user_id: Optional[str] = None,
    increment: int = 1,
) -> int:
    """Increment install count for a repository listing. Returns affected row count."""
    update_values: Dict[str, Any] = {
        "downloads": func.coalesce(SkillRepository.downloads, 0) + increment,
    }
    if user_id is not None:
        update_values["updated_by"] = user_id

    with get_db_session() as session:
        result = session.execute(
            update(SkillRepository)
            .where(
                SkillRepository.skill_repository_id == repository_id,
                SkillRepository.delete_flag != "Y",
            )
            .values(**update_values)
        )
        return int(result.rowcount or 0)


def list_skill_repository_by_skill_ids(
    skill_ids: List[int],
    *,
    statuses: Collection[str],
    publisher_tenant_id: str,
) -> List[dict]:
    """List repository rows for the given skills, scoped to publisher tenant and statuses."""
    if not skill_ids:
        return []

    status_list = list(statuses)
    with get_db_session() as session:
        rows = (
            session.query(
                SkillRepository.skill_repository_id,
                SkillRepository.skill_id,
                SkillRepository.status,
                SkillRepository.create_time,
            )
            .filter(
                SkillRepository.delete_flag != "Y",
                SkillRepository.publisher_tenant_id == publisher_tenant_id,
                SkillRepository.skill_id.in_(skill_ids),
                SkillRepository.status.in_(status_list),
            )
            .order_by(
                SkillRepository.skill_id,
                SkillRepository.create_time.desc(),
            )
            .all()
        )

    return [
        {
            "skill_repository_id": row.skill_repository_id,
            "skill_id": row.skill_id,
            "status": row.status,
            "create_time": row.create_time,
        }
        for row in rows
    ]
