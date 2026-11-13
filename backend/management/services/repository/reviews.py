# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Snapshot submission and atomic publication, independent of repository state."""

import base64
import io
import json
import logging
import zipfile
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit

from contracts.errors.exceptions import ReviewConflictError, UnauthorizedError
from contracts.review import ReviewListItem, ReviewListResponse, ReviewPagination
from contracts.roles import has_any_role, roles_from_record
from management.db.agent.models import AgentInfo
from management.db.client import get_db_session
from management.db.identity.models import UserTenant
from management.db.identity.role_permission import check_role_permission
from management.db.mcp.models import McpRecord
from management.db.repository_reviews import REVIEW_MODELS, get_review, list_reviews
from management.db.repository_transactions import (
    lock_repository_source,
    repository_unit_of_work,
)
from management.db.resource_review_model import ResourceReview
from management.db.skill.models import SkillInfo
from management.services.repository.review_notifications import (
    create_repository_pending_review_notification,
    create_repository_review_notification,
)
from sqlalchemy import select, update

logger = logging.getLogger(__name__)


def require_repository_access(role):
    if not check_role_permission(
        role, permission_type="LEFT_NAV_MENU", permission_subtype="/resource-space"
    ):
        raise UnauthorizedError("Resource repository access is required")


def can_decide(resource_type, role):
    return has_any_role(role, {"ADMIN"}) or (resource_type == "mcp" and has_any_role(role, {"SU", "SUPER_ADMIN"}))


def public_item(record, role, names=None):
    payload = record.resource_snapshot["payload"]
    return ReviewListItem(
        review_id=str(record.review_id),
        source_resource_id=str(record.source_resource_id),
        resource_type=record.resource_type,
        version_no=record.version_no,
        repository_id=str(record.repository_id)
        if record.repository_id is not None
        else None,
        tenant_id=record.tenant_id,
        name=payload.get("display_name")
        or payload.get("name")
        or payload.get("mcp_name")
        or "",
        description=payload.get("description"),
        version_label=payload.get("version_name"),
        status=record.review_status,
        submitted_user_id=record.submitted_user_id,
        submitter={
            "user_id": record.submitted_user_id,
            **(names or {}).get(record.submitted_user_id, {}),
        },
        submitted_at=record.submitted_at,
        submit_description=record.submit_description,
        review_comment=record.review_comment,
        reviewed_by=record.reviewed_by,
        reviewed_at=record.reviewed_at,
        published_at=record.reviewed_at if record.review_status == "approved" else None,
        allowed_actions=["approve", "reject"]
        if record.review_status == "pending_review"
        and can_decide(record.resource_type, role)
        else [],
    )


def _names(session, rows: list[dict]) -> dict:
    ids = {row["submitted_user_id"] for row in rows if row.get("submitted_user_id")}
    if not ids:
        return {}
    from management.db.models import UserOAuthAccount

    names = {
        user_id: {"display_name": email}
        for user_id, email in session.execute(
            select(UserTenant.user_id, UserTenant.user_email).where(
                UserTenant.user_id.in_(ids), UserTenant.delete_flag != "Y"
            )
        ).all()
    }
    identities = session.execute(
        select(UserOAuthAccount.user_id, UserOAuthAccount.provider_username)
        .where(
            UserOAuthAccount.user_id.in_(ids),
            UserOAuthAccount.provider == "cas",
            UserOAuthAccount.delete_flag == "N",
        )
        .order_by(UserOAuthAccount.oauth_account_id.asc())
    ).all()
    for user_id, username in identities:
        if username and user_id in names:
            names[user_id].setdefault("cas_username", username)
    return names


def _safe_url(value: str | None) -> str | None:
    if not value:
        return value
    parts = urlsplit(value)
    host = parts.netloc.rsplit("@", 1)[-1]
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def _field_states(value, prefix: str = "") -> list[dict]:
    """Expose configuration field paths and presence, never their values."""
    if not isinstance(value, dict):
        return []
    result = []
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(child, dict):
            result.extend(_field_states(child, path))
        else:
            result.append(
                {
                    "name": path,
                    "configured": child is not None and child != "",
                    "masked": True,
                }
            )
    return result


def resource_detail(resource_type: str, record) -> dict:
    if resource_type == "mcp":
        return {
            "source_mcp_id": record.source_mcp_id,
            "transport_type": record.transport_type,
            "server_url": _safe_url(record.mcp_server),
            "shared_fields": {
                str(key): bool(value)
                for key, value in (record.shared_fields or {}).items()
            },
            "sensitive_fields": _field_states(record.config_json)
            + _field_states(record.registry_json),
        }
    if resource_type == "skill":
        snapshot = record.skill_info_json or {}
        files = []
        unavailable = False
        try:
            with zipfile.ZipFile(
                io.BytesIO(base64.b64decode(record.skill_zip_base64, validate=True))
            ) as archive:
                files = [
                    {"path": item.filename, "size_bytes": item.file_size}
                    for item in archive.infolist()
                    if not item.is_dir()
                ]
        except (ValueError, zipfile.BadZipFile):
            unavailable = True
        return {
            "skill_id": record.skill_id,
            "name": record.name,
            "tags": record.tags or [],
            "description": record.description,
            "readme": snapshot.get("content") or snapshot.get("skill_content"),
            "icon": record.icon,
            "file_manifest": files[:200],
            "file_count": len(files),
            "files_unavailable": unavailable,
        }
    snapshot = record.agent_info_json or {}
    agents = snapshot.get("agent_info") or {}
    return {
        "agent_id": record.agent_id,
        "version_no": record.version_no,
        "version_name": record.version_name,
        "agents": [
            {
                "name": info.get("display_name") or info.get("name"),
                "description": info.get("description"),
                "prompt": info.get("system_prompt") or info.get("prompt"),
                "tools": [
                    tool.get("name")
                    for tool in info.get("tools", [])
                    if isinstance(tool, dict)
                ],
            }
            for info in agents.values()
            if isinstance(info, dict)
        ]
        if isinstance(agents, dict)
        else [],
    }


def _public(session, record, role):
    return public_item(
        record, role, _names(session, [{"submitted_user_id": record.submitted_user_id}])
    ).model_dump(mode="json")


def list_repository_reviews(user_id, tenant_id, role, query):
    require_repository_access(role)
    with get_db_session() as session:
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        rows, total = list_reviews(session, user_id, tenant_id, role, query)
        names = _names(
            session, [{"submitted_user_id": row.submitted_user_id} for row in rows]
        )
        return ReviewListResponse(
            items=[public_item(row, role, names) for row in rows],
            pagination=ReviewPagination(
                page=query.page, page_size=query.page_size, total=total
            ),
        ).model_dump(mode="json")


def get_repository_review(review_id, user_id, tenant_id, role):
    require_repository_access(role)
    with get_db_session() as session:
        record = get_review(session, review_id, user_id, tenant_id, role)
        if record is None:
            raise LookupError("Review record not found")
        result = _public(session, record, role)
        if record.repository_id is not None:
            model, key, tenant_field, status_field, _ = REVIEW_MODELS[
                record.resource_type
            ]
            result["current_repository_status"] = session.scalar(
                select(getattr(model, status_field)).where(
                    getattr(model, key) == record.repository_id,
                    getattr(model, tenant_field) == record.tenant_id,
                    model.delete_flag != "Y",
                )
            )
        payload = record.resource_snapshot["payload"]
        result["resource_detail"] = resource_detail(
            record.resource_type, SimpleNamespace(**payload)
        )
        return result


def save_submission(
    resource_type,
    source_id,
    tenant_id,
    user_id,
    role,
    payload,
    version_no=None,
    repository_id=None,
):
    """Persist a frozen validated payload without touching repository contents."""
    model = REVIEW_MODELS[resource_type][0]
    for column in model.__table__.columns:
        value = payload.get(column.name)
        maximum = getattr(column.type, "length", None)
        if isinstance(value, str) and maximum is not None and len(value) > maximum:
            raise ValueError(
                f"{column.name} exceeds the publication field length limit"
            )
    snapshot = {
        "schema_version": 1,
        "payload": json.loads(json.dumps(payload, default=str)),
    }
    description = (payload.get("content") or "").strip() or None
    with repository_unit_of_work() as session:
        lock_repository_source(session, resource_type, tenant_id, source_id)
        pending = session.scalar(
            select(ResourceReview)
            .where(
                ResourceReview.tenant_id == tenant_id,
                ResourceReview.resource_type == resource_type,
                ResourceReview.source_resource_id == source_id,
                ResourceReview.review_status == "pending_review",
                ResourceReview.delete_flag == "N",
            )
            .with_for_update()
        )
        if pending:
            if pending.submitted_user_id != user_id:
                raise ReviewConflictError("PENDING_REVIEW_EXISTS")
            if (
                pending.resource_snapshot != snapshot
                or pending.version_no != version_no
            ):
                raise ReviewConflictError("PENDING_REVIEW_EXISTS")
            return _public(session, pending, role)
        record = ResourceReview(
            tenant_id=tenant_id,
            resource_type=resource_type,
            source_resource_id=source_id,
            version_no=version_no,
            repository_id=repository_id,
            submitted_user_id=user_id,
            submitted_at=datetime.now(timezone.utc),
            submit_description=description,
            resource_snapshot=snapshot,
            review_status="pending_review",
            created_by=user_id,
            updated_by=user_id,
            delete_flag="N",
        )
        session.add(record)
        session.flush()
        result = _public(session, record, role)
        create_repository_pending_review_notification(
            resource_type="resource_review",
            tenant_id=tenant_id,
            unique_id=record.review_id,
            created_by=user_id,
            details={
                "review_id": str(record.review_id),
                "resource_type": resource_type,
                "name": result["name"],
            },
        )
        return result


async def submit_repository_review(user_id, tenant_id, role, request):
    require_repository_access(role)
    fields = dict(request.listing_fields)
    allowed = {
        "agent": {"icon_url", "tags"},
        "skill": {"icon", "category_id", "tags"},
        "mcp": {
            "name",
            "description",
            "tags",
            "mcp_server",
            "config_json",
            "group_ids",
            "ingroup_permission",
            "shared_fields",
        },
    }
    if fields.keys() - allowed[request.resource_type]:
        raise ValueError("Unsupported listing fields")
    if (request.resource_type == "agent") != (request.version_no is not None):
        raise ValueError("Only Agent submissions require version_no")
    source_id = int(request.source_resource_id)
    fields["content"] = request.submit_description
    from contracts.agent import AgentRepositoryListingCreateRequest
    from contracts.skill import SkillRepositoryListingCreateRequest
    from contracts.tool import CommunityPublishRequest

    if request.resource_type == "agent":
        fields = AgentRepositoryListingCreateRequest.model_validate(fields).model_dump(
            exclude_unset=True
        )
    elif request.resource_type == "skill":
        fields = SkillRepositoryListingCreateRequest.model_validate(fields).model_dump(
            exclude_unset=True
        )
    else:
        validated = CommunityPublishRequest.model_validate(
            {"mcp_id": source_id, **fields}
        )
        fields = validated.model_dump(exclude_unset=True, exclude={"mcp_id"})

    if request.resource_type == "agent":
        from management.services.repository.agent.publishing import (
            create_agent_repository_listing_impl,
        )

        return await create_agent_repository_listing_impl(
            source_id, tenant_id, user_id, request.version_no, card_fields=fields
        )
    if request.resource_type == "skill":
        from services.skill_repository_service import (
            create_skill_repository_listing_impl,
        )

        return create_skill_repository_listing_impl(
            source_id, tenant_id, user_id, card_fields=fields
        )
    from management.services.repository.mcp.service import publish_community_mcp_service

    return await publish_community_mcp_service(
        tenant_id=tenant_id, user_id=user_id, mcp_id=source_id, **fields
    )


def _publish(session, record, user_id):
    model, key, tenant_field, status_field, source_field = REVIEW_MODELS[
        record.resource_type
    ]
    source_model = {"agent": AgentInfo, "skill": SkillInfo, "mcp": McpRecord}[
        record.resource_type
    ]
    source_key = {"agent": "agent_id", "skill": "skill_id", "mcp": "mcp_id"}[
        record.resource_type
    ]
    source_filters = [
        getattr(source_model, source_key) == record.source_resource_id,
        source_model.tenant_id == record.tenant_id,
        source_model.delete_flag != "Y",
    ]
    if record.resource_type == "agent":
        source_filters.append(source_model.version_no == record.version_no)
    if (
        session.scalar(select(source_model).where(*source_filters).with_for_update())
        is None
    ):
        raise ReviewConflictError("SOURCE_UNAVAILABLE")
    filters = [
        getattr(model, tenant_field) == record.tenant_id,
        getattr(model, source_field) == record.source_resource_id,
        model.delete_flag != "Y",
    ]
    if record.resource_type == "agent":
        filters.append(model.version_no == record.version_no)
    if record.repository_id is not None:
        filters.append(getattr(model, key) == record.repository_id)
    target = session.scalar(
        select(model)
        .where(*filters)
        .order_by(getattr(model, key).desc())
        .with_for_update()
    )
    if record.repository_id is not None and target is None:
        raise ReviewConflictError("REVIEW_MAPPING_CONFLICT")
    peers = [
        getattr(model, tenant_field) == record.tenant_id,
        getattr(model, source_field) == record.source_resource_id,
        getattr(model, status_field) == "shared",
        model.delete_flag != "Y",
    ]
    if target is not None:
        peers.append(getattr(model, key) != getattr(target, key))
    session.execute(
        update(model)
        .where(*peers)
        .values(**{status_field: "not_shared", "updated_by": user_id})
    )
    data = record.resource_snapshot["payload"]
    protected = {
        key,
        tenant_field,
        "created_by",
        "create_time",
        "updated_by",
        "update_time",
        "delete_flag",
        "downloads",
        "download_count",
        "publisher_user_id",
        "user_id",
    }
    values = {
        field: value
        for field, value in data.items()
        if field in model.__table__.columns and field not in protected
    }
    values.update(
        {
            source_field: record.source_resource_id,
            status_field: "shared",
            "updated_by": user_id,
        }
    )
    if target is None:
        values.update(
            {
                tenant_field: record.tenant_id,
                "created_by": record.submitted_user_id,
                "delete_flag": "N",
                "user_id"
                if record.resource_type == "mcp"
                else "publisher_user_id": record.submitted_user_id,
            }
        )
        target = model(**values)
        session.add(target)
        session.flush()
    else:
        for field, value in values.items():
            setattr(target, field, value)
    record.repository_id = getattr(target, key)
    if record.resource_type == "mcp":
        session.execute(
            update(McpRecord)
            .where(
                McpRecord.mcp_id == record.source_resource_id,
                McpRecord.tenant_id == record.tenant_id,
            )
            .values(market_id=record.repository_id, updated_by=user_id)
        )


def decide_repository_review(review_id, user_id, tenant_id, role, request):
    require_repository_access(role)
    with repository_unit_of_work() as session:
        record = get_review(session, review_id, user_id, tenant_id, role)
        if record is None:
            raise LookupError("Review record not found")
        if not can_decide(record.resource_type, role):
            raise UnauthorizedError("Review decision permission is required")
        lock_repository_source(
            session, record.resource_type, record.tenant_id, record.source_resource_id
        )
        record = get_review(
            session, review_id, user_id, tenant_id, role, for_update=True
        )
        if record.review_status != "pending_review":
            raise ReviewConflictError("REVIEW_ALREADY_PROCESSED")
        if request.decision == "approve":
            _publish(session, record, user_id)
        record.review_status = (
            "approved" if request.decision == "approve" else "rejected"
        )
        record.review_comment = request.reason
        record.reviewed_by = user_id
        record.reviewed_at = datetime.now(timezone.utc)
        record.updated_by = user_id
        session.flush()
        from management.services.notification.service import deactivate_notifications

        deactivate_notifications(
            event_type="repository_review_pending",
            resource_type="resource_review",
            unique_id=record.review_id,
            updated_by=user_id,
        )
        result = _public(session, record, role)
        create_repository_review_notification(
            resource_type="resource_review",
            review_status="shared" if request.decision == "approve" else "rejected",
            receiver_user_id=record.submitted_user_id,
            tenant_id=record.tenant_id,
            unique_id=record.review_id,
            created_by=user_id,
            details={
                "review_id": str(record.review_id),
                "resource_type": record.resource_type,
                "repository_id": str(record.repository_id)
                if record.repository_id
                else None,
                "name": result["name"],
                "content": request.reason or "",
            },
        )
        return result


def decide_legacy_review(
    resource_type, repository_id, user_id, tenant_id, role, status, reason=None
):
    """Resolve a unique authorized application, never infer the latest completed one."""
    with repository_unit_of_work() as session:
        rows = session.scalars(
            select(ResourceReview).where(
                ResourceReview.resource_type == resource_type,
                ResourceReview.repository_id == repository_id,
                ResourceReview.review_status == "pending_review",
                ResourceReview.delete_flag == "N",
            )
        ).all()
        if len(rows) != 1:
            raise ReviewConflictError("REVIEW_MAPPING_CONFLICT")
        return decide_repository_review(
            rows[0].review_id,
            user_id,
            tenant_id,
            role,
            SimpleNamespace(
                decision="approve" if status == "shared" else "reject", reason=reason
            ),
        )


def get_legacy_repository_review(
    resource_type, repository_id, user_id, tenant_id, role
):
    """Resolve only a unique visible application for an old repository identity."""
    from management.db.repository_reviews import scope_conditions

    require_repository_access(role)
    with get_db_session() as session:
        ids = session.scalars(
            select(ResourceReview.review_id).where(
                ResourceReview.repository_id == repository_id,
                *scope_conditions(resource_type, user_id, tenant_id, role),
            )
        ).all()
        if not ids:
            raise LookupError("Review record not found")
        if len(ids) != 1:
            raise ReviewConflictError("REVIEW_MAPPING_CONFLICT")
        return get_repository_review(ids[0], user_id, tenant_id, role)


def attach_latest_reviews(items, resource_type, source_key, user_id, tenant_id):
    """Batch project application status separately from current repository state."""
    from management.db.identity.user_tenant import get_user_tenant_by_user_id
    from management.db.repository_reviews import scope_conditions

    source_ids = [
        int(item[source_key]) for item in items if item.get(source_key) is not None
    ]
    if not source_ids:
        return
    role = roles_from_record(get_user_tenant_by_user_id(user_id) or {})
    with get_db_session() as session:
        rows = session.scalars(
            select(ResourceReview)
            .where(
                ResourceReview.source_resource_id.in_(source_ids),
                *scope_conditions(resource_type, user_id, tenant_id, role),
            )
            .distinct(ResourceReview.source_resource_id)
            .order_by(
                ResourceReview.source_resource_id, ResourceReview.review_id.desc()
            )
        ).all()
        summaries = {
            row.source_resource_id: {
                "review_id": str(row.review_id),
                "status": row.review_status,
                "submitted_at": row.submitted_at.isoformat(),
                "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
            }
            for row in rows
        }
        for item in items:
            if item.get(source_key) is not None:
                item["latest_review"] = summaries.get(int(item[source_key]))
