"""Tenant-scoped persistence operations for unified tag management."""

import base64
import json
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from consts.exceptions import (
    TagManagementConflictError,
    TagManagementNotFoundError,
    ValidationError,
)
from database.client import get_db_session
from database.db_models import (
    ResourceTagAssignment,
    TagBucket,
    TagBucketResourceType,
    TagDefinition,
    TagValue,
)
from sqlalchemy import and_, func

SYSTEM_BUCKET_KEYS = ("default_resource", "knowledge_content")
ACTIVE_DELETE_FLAG = "N"
DELETED_DELETE_FLAG = "Y"
ACTIVE_STATUS = "active"
RESOURCE_ASSIGNMENT_LIMIT = 100
NO_VALUE_TAG_NORMALIZED_VALUE = "__no_value__"


def _set_audit_fields(record: Any, actor_id: str) -> None:
    record.updated_by = actor_id


def _audit_data(record: Any) -> dict[str, Any]:
    return {
        "created_by": record.created_by,
        "updated_by": record.updated_by,
        "create_time": record.create_time,
        "update_time": record.update_time,
    }


def _value_data(value: TagValue) -> dict[str, Any]:
    return _audit_data(value) | {
        "value_id": value.value_id,
        "display_value": value.display_value,
        "normalized_value": value.normalized_value,
        "sort_order": value.sort_order,
        "status": value.status,
    }


def _definition_data(
    definition: TagDefinition,
    active_value_count: int,
    values: Iterable[TagValue] | None = None,
) -> dict[str, Any]:
    data = _audit_data(definition) | {
        "definition_id": definition.definition_id,
        "bucket_id": definition.bucket_id,
        "definition_key": definition.definition_key,
        "definition_name": definition.definition_name,
        "selection_mode": definition.selection_mode,
        "sort_order": definition.sort_order,
        "status": definition.status,
        "active_value_count": active_value_count,
        "value_capacity": 1000,
    }
    if values is not None:
        data["values"] = [_value_data(value) for value in values]
    return data


def _assignment_data(
    definition: TagDefinition,
    value: TagValue,
) -> dict[str, Any]:
    return {
        "definition_id": definition.definition_id,
        "definition_key": definition.definition_key,
        "definition_name": definition.definition_name,
        "selection_mode": definition.selection_mode,
        "value_id": value.value_id,
        "display_value": value.display_value,
        "value_status": value.status,
    }


def _is_document_assignment_in_knowledge_base(
    resource_id: str,
    provider: str,
    knowledge_base_id: str,
) -> bool:
    """Match only the canonical encoded document identity for one provider knowledge base."""

    try:
        decoded = base64.urlsafe_b64decode(str(resource_id).encode("ascii"))
        identity = json.loads(decoded.decode("utf-8"))
    except (UnicodeEncodeError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return False
    return (
        isinstance(identity, list)
        and len(identity) == 3
        and str(identity[0]) == provider
        and str(identity[1]) == knowledge_base_id
    )


class TagManagementDB:
    """All tag identifiers are resolved within the supplied tenant."""

    @staticmethod
    def _get_bucket(
        session, tenant_id: str, bucket_id: int, for_update: bool = False
    ) -> TagBucket:
        query = session.query(TagBucket).filter(
            TagBucket.tenant_id == tenant_id,
            TagBucket.bucket_id == bucket_id,
            TagBucket.bucket_key.in_(SYSTEM_BUCKET_KEYS),
            TagBucket.delete_flag == ACTIVE_DELETE_FLAG,
        )
        if for_update:
            query = query.with_for_update()
        bucket = query.one_or_none()
        if bucket is None:
            raise TagManagementNotFoundError("Tag library not found")
        return bucket

    @staticmethod
    def _get_definition(
        session,
        tenant_id: str,
        bucket_id: int,
        definition_id: int,
        for_update: bool = False,
    ) -> TagDefinition:
        TagManagementDB._get_bucket(session, tenant_id, bucket_id)
        query = session.query(TagDefinition).filter(
            TagDefinition.tenant_id == tenant_id,
            TagDefinition.bucket_id == bucket_id,
            TagDefinition.definition_id == definition_id,
            TagDefinition.delete_flag == ACTIVE_DELETE_FLAG,
        )
        if for_update:
            query = query.with_for_update()
        definition = query.one_or_none()
        if definition is None:
            raise TagManagementNotFoundError("Tag definition not found")
        return definition

    @staticmethod
    def _get_value(
        session,
        tenant_id: str,
        bucket_id: int,
        definition_id: int,
        value_id: int,
        for_update: bool = False,
    ) -> TagValue:
        TagManagementDB._get_definition(session, tenant_id, bucket_id, definition_id)
        query = session.query(TagValue).filter(
            TagValue.tenant_id == tenant_id,
            TagValue.definition_id == definition_id,
            TagValue.value_id == value_id,
            TagValue.delete_flag == ACTIVE_DELETE_FLAG,
        )
        if for_update:
            query = query.with_for_update()
        value = query.one_or_none()
        if value is None:
            raise TagManagementNotFoundError("Tag value not found")
        return value

    @staticmethod
    def _definition_usage_count(session, tenant_id: str, definition_id: int) -> int:
        return (
            session.query(ResourceTagAssignment)
            .filter(
                ResourceTagAssignment.tenant_id == tenant_id,
                ResourceTagAssignment.definition_id == definition_id,
                ResourceTagAssignment.delete_flag == ACTIVE_DELETE_FLAG,
            )
            .count()
        )

    @staticmethod
    def _value_usage_count(session, tenant_id: str, value_id: int) -> int:
        return (
            session.query(ResourceTagAssignment)
            .filter(
                ResourceTagAssignment.tenant_id == tenant_id,
                ResourceTagAssignment.value_id == value_id,
                ResourceTagAssignment.delete_flag == ACTIVE_DELETE_FLAG,
            )
            .count()
        )

    @staticmethod
    def _active_value_count(session, tenant_id: str, definition_id: int) -> int:
        return (
            session.query(TagValue)
            .filter(
                TagValue.tenant_id == tenant_id,
                TagValue.definition_id == definition_id,
                TagValue.delete_flag == ACTIVE_DELETE_FLAG,
            )
            .count()
        )

    @staticmethod
    def _get_active_resource_binding(
        session,
        tenant_id: str,
        resource_type: str,
        library_code: str,
        *,
        for_update: bool,
    ):
        """Lock the immutable binding to serialize replacements for its resources."""

        query = (
            session.query(TagBucketResourceType)
            .join(
                TagBucket,
                and_(
                    TagBucket.tenant_id == TagBucketResourceType.tenant_id,
                    TagBucket.bucket_id == TagBucketResourceType.bucket_id,
                ),
            )
            .filter(
                TagBucketResourceType.tenant_id == tenant_id,
                TagBucketResourceType.resource_type == resource_type,
                TagBucketResourceType.status == ACTIVE_STATUS,
                TagBucketResourceType.delete_flag == ACTIVE_DELETE_FLAG,
                TagBucket.bucket_key == library_code,
                TagBucket.status == ACTIVE_STATUS,
                TagBucket.delete_flag == ACTIVE_DELETE_FLAG,
            )
        )
        if for_update:
            query = query.with_for_update()
        binding = query.one_or_none()
        if binding is None:
            raise ValidationError("Resource type is not bound to an active tag library")
        return binding

    @staticmethod
    def _assignment_rows(session, tenant_id: str, resource_type: str, resource_id: str):
        return (
            session.query(ResourceTagAssignment, TagDefinition, TagValue)
            .join(
                TagDefinition,
                and_(
                    TagDefinition.tenant_id == ResourceTagAssignment.tenant_id,
                    TagDefinition.definition_id == ResourceTagAssignment.definition_id,
                ),
            )
            .join(
                TagValue,
                and_(
                    TagValue.tenant_id == ResourceTagAssignment.tenant_id,
                    TagValue.definition_id == ResourceTagAssignment.definition_id,
                    TagValue.value_id == ResourceTagAssignment.value_id,
                ),
            )
            .filter(
                ResourceTagAssignment.tenant_id == tenant_id,
                ResourceTagAssignment.resource_type == resource_type,
                ResourceTagAssignment.resource_id == resource_id,
                ResourceTagAssignment.delete_flag == ACTIVE_DELETE_FLAG,
            )
            .order_by(
                TagDefinition.sort_order,
                TagDefinition.definition_id,
                TagValue.sort_order,
                TagValue.value_id,
            )
        )

    @staticmethod
    def _load_assignable_values(session, tenant_id: str, bucket_id: int, value_ids: list[int]):
        if not value_ids:
            return []
        return (
            session.query(TagValue, TagDefinition)
            .join(
                TagDefinition,
                and_(
                    TagDefinition.tenant_id == TagValue.tenant_id,
                    TagDefinition.definition_id == TagValue.definition_id,
                ),
            )
            .filter(
                TagValue.tenant_id == tenant_id,
                TagValue.value_id.in_(value_ids),
                TagValue.status == ACTIVE_STATUS,
                TagValue.delete_flag == ACTIVE_DELETE_FLAG,
                TagDefinition.bucket_id == bucket_id,
                TagDefinition.status == ACTIVE_STATUS,
                TagDefinition.delete_flag == ACTIVE_DELETE_FLAG,
            )
            .with_for_update()
            .all()
        )

    @staticmethod
    def _validate_replacement_values(value_ids: list[int], value_rows) -> None:
        """Validate controlled values before the replacement deletes prior rows."""

        if len(value_ids) > RESOURCE_ASSIGNMENT_LIMIT:
            raise TagManagementConflictError(
                "Resource tag assignment capacity exceeded",
                {
                    "limit": RESOURCE_ASSIGNMENT_LIMIT,
                    "current_count": len(value_ids),
                    "scope": "assignment",
                },
            )
        if len(value_rows) != len(value_ids):
            raise ValidationError(
                "Each assigned tag value must be active and belong to the resource library"
            )

        values_per_definition: dict[int, int] = defaultdict(int)
        for _, definition in value_rows:
            values_per_definition[definition.definition_id] += 1
        if any(
            definition.selection_mode == "single_select"
            and values_per_definition[definition.definition_id] > 1
            for _, definition in value_rows
        ):
            raise ValidationError(
                "A single-select tag definition accepts only one assigned value"
            )

    @staticmethod
    def list_libraries(tenant_id: str) -> list[dict[str, Any]]:
        with get_db_session() as session:
            buckets = (
                session.query(TagBucket)
                .filter(
                    TagBucket.tenant_id == tenant_id,
                    TagBucket.bucket_key.in_(SYSTEM_BUCKET_KEYS),
                    TagBucket.delete_flag == ACTIVE_DELETE_FLAG,
                )
                .order_by(TagBucket.bucket_id)
                .all()
            )
            bindings = (
                session.query(TagBucketResourceType)
                .filter(
                    TagBucketResourceType.tenant_id == tenant_id,
                    TagBucketResourceType.delete_flag == ACTIVE_DELETE_FLAG,
                )
                .order_by(TagBucketResourceType.resource_type)
                .all()
            )
            resource_types_by_bucket: dict[int, list[str]] = defaultdict(list)
            for binding in bindings:
                resource_types_by_bucket[binding.bucket_id].append(
                    binding.resource_type
                )
            definition_counts = dict(
                session.query(
                    TagDefinition.bucket_id, func.count(TagDefinition.definition_id)
                )
                .filter(
                    TagDefinition.tenant_id == tenant_id,
                    TagDefinition.delete_flag == ACTIVE_DELETE_FLAG,
                )
                .group_by(TagDefinition.bucket_id)
                .all()
            )
            return [
                _audit_data(bucket)
                | {
                    "bucket_id": bucket.bucket_id,
                    "bucket_key": bucket.bucket_key,
                    "bucket_name": bucket.bucket_name,
                    "status": bucket.status,
                    "resource_types": resource_types_by_bucket[bucket.bucket_id],
                    "definition_count": definition_counts.get(bucket.bucket_id, 0),
                    "definition_capacity": 100,
                }
                for bucket in buckets
            ]

    @staticmethod
    def list_definitions(tenant_id: str, bucket_id: int) -> list[dict[str, Any]]:
        with get_db_session() as session:
            TagManagementDB._get_bucket(session, tenant_id, bucket_id)
            definitions = (
                session.query(TagDefinition)
                .filter(
                    TagDefinition.tenant_id == tenant_id,
                    TagDefinition.bucket_id == bucket_id,
                    TagDefinition.delete_flag == ACTIVE_DELETE_FLAG,
                )
                .order_by(TagDefinition.sort_order, TagDefinition.definition_id)
                .all()
            )
            definition_ids = [definition.definition_id for definition in definitions]
            values_by_definition: dict[int, list[TagValue]] = defaultdict(list)
            if definition_ids:
                values = (
                    session.query(TagValue)
                    .filter(
                        TagValue.tenant_id == tenant_id,
                        TagValue.definition_id.in_(definition_ids),
                        TagValue.delete_flag == ACTIVE_DELETE_FLAG,
                    )
                    .order_by(TagValue.sort_order, TagValue.value_id)
                    .all()
                )
                for value in values:
                    values_by_definition[value.definition_id].append(value)
            return [
                _definition_data(
                    definition,
                    len(values_by_definition[definition.definition_id]),
                    values_by_definition[definition.definition_id],
                )
                for definition in definitions
            ]

    @staticmethod
    def create_definition(
        tenant_id: str,
        bucket_id: int,
        definition_key: str,
        definition_name: str,
        selection_mode: str,
        initial_values: list[str],
        sort_order: int | None,
        actor_id: str,
    ) -> dict[str, Any]:
        if selection_mode == "no_value":
            if initial_values:
                raise ValidationError("A no-value tag definition cannot contain tag values")
            normalized_values = [NO_VALUE_TAG_NORMALIZED_VALUE]
            stored_values = [definition_name.strip()]
        else:
            if not initial_values:
                raise ValidationError("At least one tag value is required")
            normalized_values = [value.strip().lower() for value in initial_values]
            stored_values = initial_values
        if len(set(normalized_values)) != len(normalized_values):
            raise TagManagementConflictError(
                "Tag values must be unique after normalization"
            )

        with get_db_session() as session:
            TagManagementDB._get_bucket(session, tenant_id, bucket_id, for_update=True)
            definition_count = (
                session.query(TagDefinition)
                .filter(
                    TagDefinition.tenant_id == tenant_id,
                    TagDefinition.bucket_id == bucket_id,
                    TagDefinition.delete_flag == ACTIVE_DELETE_FLAG,
                )
                .count()
            )
            if definition_count >= 100:
                raise TagManagementConflictError(
                    "Tag definition capacity exceeded",
                    {
                        "limit": 100,
                        "current_count": definition_count,
                        "scope": "definition",
                    },
                )

            if sort_order is None:
                highest_sort_order = (
                    session.query(func.max(TagDefinition.sort_order))
                    .filter(
                        TagDefinition.tenant_id == tenant_id,
                        TagDefinition.bucket_id == bucket_id,
                        TagDefinition.delete_flag == ACTIVE_DELETE_FLAG,
                    )
                    .scalar()
                )
                sort_order = (
                    highest_sort_order if highest_sort_order is not None else -1
                ) + 1

            definition = TagDefinition(
                tenant_id=tenant_id,
                bucket_id=bucket_id,
                definition_key=definition_key,
                definition_name=definition_name,
                selection_mode=selection_mode,
                sort_order=sort_order,
                status="active",
                created_by=actor_id,
                updated_by=actor_id,
                delete_flag=ACTIVE_DELETE_FLAG,
            )
            session.add(definition)
            session.flush()

            values = [
                TagValue(
                    tenant_id=tenant_id,
                    definition_id=definition.definition_id,
                    normalized_value=normalized_value,
                    display_value=display_value.strip(),
                    sort_order=index,
                    status="active",
                    created_by=actor_id,
                    updated_by=actor_id,
                    delete_flag=ACTIVE_DELETE_FLAG,
                )
                for index, (display_value, normalized_value) in enumerate(
                    zip(stored_values, normalized_values)
                )
            ]
            session.add_all(values)
            session.flush()
            return _definition_data(definition, len(values), values)

    @staticmethod
    def update_definition(
        tenant_id: str,
        bucket_id: int,
        definition_id: int,
        definition_name: str | None,
        selection_mode: str | None,
        actor_id: str,
    ) -> tuple[dict[str, Any], int]:
        with get_db_session() as session:
            definition = TagManagementDB._get_definition(
                session, tenant_id, bucket_id, definition_id, for_update=True
            )
            multiple_resource_count = 0
            if (
                definition.selection_mode == "multi_select"
                and selection_mode == "single_select"
            ):
                multiple_resource_count = (
                    session.query(
                        ResourceTagAssignment.resource_type,
                        ResourceTagAssignment.resource_id,
                    )
                    .filter(
                        ResourceTagAssignment.tenant_id == tenant_id,
                        ResourceTagAssignment.definition_id == definition_id,
                        ResourceTagAssignment.delete_flag == ACTIVE_DELETE_FLAG,
                    )
                    .group_by(
                        ResourceTagAssignment.resource_type,
                        ResourceTagAssignment.resource_id,
                    )
                    .having(func.count(ResourceTagAssignment.assignment_id) > 1)
                    .count()
                )
                if multiple_resource_count:
                    return (
                        _definition_data(
                            definition,
                            TagManagementDB._active_value_count(
                                session, tenant_id, definition_id
                            ),
                        ),
                        multiple_resource_count,
                    )
            if definition_name is not None:
                definition.definition_name = definition_name
            if selection_mode is not None:
                definition.selection_mode = selection_mode
            _set_audit_fields(definition, actor_id)
            session.flush()
            return (
                _definition_data(
                    definition,
                    TagManagementDB._active_value_count(
                        session, tenant_id, definition_id
                    ),
                ),
                0,
            )

    @staticmethod
    def set_definition_status(
        tenant_id: str, bucket_id: int, definition_id: int, status: str, actor_id: str
    ) -> dict[str, Any]:
        with get_db_session() as session:
            definition = TagManagementDB._get_definition(
                session, tenant_id, bucket_id, definition_id, for_update=True
            )
            definition.status = status
            _set_audit_fields(definition, actor_id)
            session.flush()
            return _definition_data(
                definition,
                TagManagementDB._active_value_count(session, tenant_id, definition_id),
            )

    @staticmethod
    def set_definition_order(
        tenant_id: str,
        bucket_id: int,
        definition_id: int,
        sort_order: int,
        actor_id: str,
    ) -> dict[str, Any]:
        with get_db_session() as session:
            definition = TagManagementDB._get_definition(
                session, tenant_id, bucket_id, definition_id, for_update=True
            )
            definition.sort_order = sort_order
            _set_audit_fields(definition, actor_id)
            session.flush()
            return _definition_data(
                definition,
                TagManagementDB._active_value_count(session, tenant_id, definition_id),
            )

    @staticmethod
    def move_definition_to_top(
        tenant_id: str,
        bucket_id: int,
        definition_id: int,
        actor_id: str,
    ) -> dict[str, Any]:
        with get_db_session() as session:
            TagManagementDB._get_bucket(
                session, tenant_id, bucket_id, for_update=True
            )
            definitions = (
                session.query(TagDefinition)
                .filter(
                    TagDefinition.tenant_id == tenant_id,
                    TagDefinition.bucket_id == bucket_id,
                    TagDefinition.delete_flag == ACTIVE_DELETE_FLAG,
                )
                .order_by(TagDefinition.sort_order, TagDefinition.definition_id)
                .with_for_update()
                .all()
            )
            target = next(
                (
                    definition
                    for definition in definitions
                    if definition.definition_id == definition_id
                ),
                None,
            )
            if target is None:
                raise TagManagementNotFoundError("Tag definition not found")

            for index, definition in enumerate(
                [target, *(item for item in definitions if item is not target)]
            ):
                definition.sort_order = index
                _set_audit_fields(definition, actor_id)
            session.flush()
            return _definition_data(
                target,
                TagManagementDB._active_value_count(
                    session, tenant_id, definition_id
                ),
            )

    @staticmethod
    def get_definition_usage(
        tenant_id: str, bucket_id: int, definition_id: int
    ) -> dict[str, int]:
        with get_db_session() as session:
            TagManagementDB._get_definition(
                session, tenant_id, bucket_id, definition_id
            )
            return {
                "definition_id": definition_id,
                "active_value_count": TagManagementDB._active_value_count(
                    session, tenant_id, definition_id
                ),
                "active_usage_count": TagManagementDB._definition_usage_count(
                    session, tenant_id, definition_id
                ),
                "value_capacity": 1000,
            }

    @staticmethod
    def delete_definition(
        tenant_id: str, bucket_id: int, definition_id: int, actor_id: str
    ) -> dict[str, int]:
        with get_db_session() as session:
            definition = TagManagementDB._get_definition(
                session, tenant_id, bucket_id, definition_id, for_update=True
            )
            active_value_count = TagManagementDB._active_value_count(
                session, tenant_id, definition_id
            )
            active_usage_count = TagManagementDB._definition_usage_count(
                session, tenant_id, definition_id
            )
            if active_value_count or active_usage_count:
                return {
                    "active_value_count": active_value_count,
                    "active_usage_count": active_usage_count,
                }
            definition.delete_flag = DELETED_DELETE_FLAG
            _set_audit_fields(definition, actor_id)
            session.flush()
            return {"active_value_count": 0, "active_usage_count": 0}

    @staticmethod
    def create_value(
        tenant_id: str,
        bucket_id: int,
        definition_id: int,
        display_value: str,
        sort_order: int,
        actor_id: str,
    ) -> dict[str, Any]:
        normalized_value = display_value.strip().lower()
        with get_db_session() as session:
            TagManagementDB._get_definition(
                session, tenant_id, bucket_id, definition_id, for_update=True
            )
            value_count = (
                session.query(TagValue)
                .filter(
                    TagValue.tenant_id == tenant_id,
                    TagValue.definition_id == definition_id,
                    TagValue.delete_flag == ACTIVE_DELETE_FLAG,
                )
                .count()
            )
            if value_count >= 1000:
                raise TagManagementConflictError(
                    "Tag value capacity exceeded",
                    {"limit": 1000, "current_count": value_count, "scope": "value"},
                )
            value = TagValue(
                tenant_id=tenant_id,
                definition_id=definition_id,
                normalized_value=normalized_value,
                display_value=display_value.strip(),
                sort_order=sort_order,
                status="active",
                created_by=actor_id,
                updated_by=actor_id,
                delete_flag=ACTIVE_DELETE_FLAG,
            )
            session.add(value)
            session.flush()
            return _value_data(value)

    @staticmethod
    def update_value(
        tenant_id: str,
        bucket_id: int,
        definition_id: int,
        value_id: int,
        display_value: str,
        actor_id: str,
    ) -> dict[str, Any]:
        with get_db_session() as session:
            value = TagManagementDB._get_value(
                session, tenant_id, bucket_id, definition_id, value_id, for_update=True
            )
            value.display_value = display_value.strip()
            value.normalized_value = display_value.strip().lower()
            _set_audit_fields(value, actor_id)
            session.flush()
            return _value_data(value)

    @staticmethod
    def set_value_status(
        tenant_id: str,
        bucket_id: int,
        definition_id: int,
        value_id: int,
        status: str,
        actor_id: str,
    ) -> dict[str, Any]:
        with get_db_session() as session:
            value = TagManagementDB._get_value(
                session, tenant_id, bucket_id, definition_id, value_id, for_update=True
            )
            value.status = status
            _set_audit_fields(value, actor_id)
            session.flush()
            return _value_data(value)

    @staticmethod
    def set_value_order(
        tenant_id: str,
        bucket_id: int,
        definition_id: int,
        value_id: int,
        sort_order: int,
        actor_id: str,
    ) -> dict[str, Any]:
        with get_db_session() as session:
            value = TagManagementDB._get_value(
                session, tenant_id, bucket_id, definition_id, value_id, for_update=True
            )
            value.sort_order = sort_order
            _set_audit_fields(value, actor_id)
            session.flush()
            return _value_data(value)

    @staticmethod
    def get_value_usage(
        tenant_id: str, bucket_id: int, definition_id: int, value_id: int
    ) -> dict[str, int]:
        with get_db_session() as session:
            TagManagementDB._get_value(
                session, tenant_id, bucket_id, definition_id, value_id
            )
            return {
                "value_id": value_id,
                "active_usage_count": TagManagementDB._value_usage_count(
                    session, tenant_id, value_id
                ),
            }

    @staticmethod
    def delete_value(
        tenant_id: str, bucket_id: int, definition_id: int, value_id: int, actor_id: str
    ) -> int:
        with get_db_session() as session:
            value = TagManagementDB._get_value(
                session, tenant_id, bucket_id, definition_id, value_id, for_update=True
            )
            usage_count = TagManagementDB._value_usage_count(
                session, tenant_id, value_id
            )
            if usage_count:
                return usage_count
            value.delete_flag = DELETED_DELETE_FLAG
            _set_audit_fields(value, actor_id)
            session.flush()
            return 0

    @staticmethod
    def list_resource_assignments(
        tenant_id: str, resource_type: str, resource_id: str, library_code: str
    ) -> list[dict[str, Any]]:
        with get_db_session() as session:
            TagManagementDB._get_active_resource_binding(
                session, tenant_id, resource_type, library_code, for_update=False
            )
            rows = TagManagementDB._assignment_rows(
                session, tenant_id, resource_type, resource_id
            ).all()
            return [_assignment_data(definition, value) for _, definition, value in rows]

    @staticmethod
    def replace_resource_assignments(
        tenant_id: str,
        resource_type: str,
        resource_id: str,
        library_code: str,
        value_ids: list[int],
        actor_id: str,
    ) -> list[dict[str, Any]]:
        """Atomically replace one resolved resource's controlled assignments."""

        value_ids = list(dict.fromkeys(value_ids))
        with get_db_session() as session:
            binding = TagManagementDB._get_active_resource_binding(
                session, tenant_id, resource_type, library_code, for_update=True
            )
            existing_assignments = (
                session.query(ResourceTagAssignment)
                .filter(
                    ResourceTagAssignment.tenant_id == tenant_id,
                    ResourceTagAssignment.resource_type == resource_type,
                    ResourceTagAssignment.resource_id == resource_id,
                    ResourceTagAssignment.delete_flag == ACTIVE_DELETE_FLAG,
                )
                .with_for_update()
                .all()
            )
            value_rows = TagManagementDB._load_assignable_values(
                session, tenant_id, binding.bucket_id, value_ids
            )
            TagManagementDB._validate_replacement_values(value_ids, value_rows)

            existing_by_value_id = {
                assignment.value_id: assignment for assignment in existing_assignments
            }
            target_value_ids = {value.value_id for value, _ in value_rows}

            for value_id, assignment in existing_by_value_id.items():
                if value_id not in target_value_ids:
                    session.delete(assignment)

            assignments = [
                ResourceTagAssignment(
                    tenant_id=tenant_id,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    definition_id=definition.definition_id,
                    value_id=value.value_id,
                    status=ACTIVE_STATUS,
                    created_by=actor_id,
                    updated_by=actor_id,
                    delete_flag=ACTIVE_DELETE_FLAG,
                )
                for value, definition in value_rows
                if value.value_id not in existing_by_value_id
            ]
            if assignments:
                session.add_all(assignments)
            if any(
                value_id not in target_value_ids
                for value_id in existing_by_value_id
            ) or assignments:
                session.flush()
            return [_assignment_data(definition, value) for value, definition in value_rows]

    @staticmethod
    def filter_authorized_resource_ids(
        tenant_id: str,
        resource_type: str,
        authorized_resource_ids: list[str],
        filters: list,
    ) -> list[str]:
        """Filter only IDs supplied by a resource-specific authorized list flow."""

        candidate_ids = list(dict.fromkeys(str(resource_id) for resource_id in authorized_resource_ids))
        if not candidate_ids or not filters:
            return candidate_ids

        matching_ids = set(candidate_ids)
        with get_db_session() as session:
            for tag_filter in filters:
                definition_id = tag_filter.definition_id
                value_ids = tag_filter.value_ids
                matched = {
                    resource_id
                    for (resource_id,) in (
                        session.query(ResourceTagAssignment.resource_id)
                        .filter(
                            ResourceTagAssignment.tenant_id == tenant_id,
                            ResourceTagAssignment.resource_type == resource_type,
                            ResourceTagAssignment.resource_id.in_(candidate_ids),
                            ResourceTagAssignment.definition_id == definition_id,
                            ResourceTagAssignment.value_id.in_(value_ids),
                            ResourceTagAssignment.delete_flag == ACTIVE_DELETE_FLAG,
                        )
                        .distinct()
                        .all()
                    )
                }
                matching_ids &= matched
                if not matching_ids:
                    break
        return [resource_id for resource_id in candidate_ids if resource_id in matching_ids]

    @staticmethod
    def count_resource_assignments_by_ids(
        tenant_id: str, resource_type: str, resource_ids: list[str]
    ) -> dict[str, int]:
        """Count active assignments per canonical resource id (one query)."""

        candidate_ids = list(dict.fromkeys(str(resource_id) for resource_id in resource_ids))
        if not candidate_ids:
            return {}
        with get_db_session() as session:
            rows = (
                session.query(ResourceTagAssignment.resource_id, func.count(ResourceTagAssignment.assignment_id))
                .filter(
                    ResourceTagAssignment.tenant_id == tenant_id,
                    ResourceTagAssignment.resource_type == resource_type,
                    ResourceTagAssignment.resource_id.in_(candidate_ids),
                    ResourceTagAssignment.delete_flag == ACTIVE_DELETE_FLAG,
                )
                .group_by(ResourceTagAssignment.resource_id)
                .all()
            )
            return {resource_id: int(count) for resource_id, count in rows}

    @staticmethod
    def list_resource_assignment_display_values_by_ids(
        tenant_id: str, resource_type: str, resource_ids: list[str]
    ) -> dict[str, list[str]]:
        """Return assignment display values for multiple resources in one query."""

        candidate_ids = list(
            dict.fromkeys(str(resource_id) for resource_id in resource_ids)
        )
        if not candidate_ids:
            return {}
        with get_db_session() as session:
            rows = (
                session.query(
                    ResourceTagAssignment.resource_id,
                    TagValue.display_value,
                )
                .join(
                    TagValue,
                    and_(
                        TagValue.tenant_id
                        == ResourceTagAssignment.tenant_id,
                        TagValue.definition_id
                        == ResourceTagAssignment.definition_id,
                        TagValue.value_id == ResourceTagAssignment.value_id,
                    ),
                )
                .filter(
                    ResourceTagAssignment.tenant_id == tenant_id,
                    ResourceTagAssignment.resource_type == resource_type,
                    ResourceTagAssignment.resource_id.in_(candidate_ids),
                    ResourceTagAssignment.delete_flag == ACTIVE_DELETE_FLAG,
                )
                .order_by(
                    ResourceTagAssignment.resource_id,
                    ResourceTagAssignment.assignment_id,
                )
                .all()
            )
            values_by_resource: dict[str, list[str]] = defaultdict(list)
            for resource_id, display_value in rows:
                if display_value:
                    values_by_resource[str(resource_id)].append(
                        str(display_value)
                    )
            return dict(values_by_resource)

    @staticmethod
    def soft_delete_resource_assignments(
        tenant_id: str,
        resource_type: str,
        resource_id: str,
        actor_id: str,
    ) -> int:
        """Soft-delete assignments only within a proven owner tenant."""

        with get_db_session() as session:
            updated_count = (
                session.query(ResourceTagAssignment)
                .filter(
                    ResourceTagAssignment.tenant_id == tenant_id,
                    ResourceTagAssignment.resource_type == resource_type,
                    ResourceTagAssignment.resource_id == resource_id,
                    ResourceTagAssignment.delete_flag == ACTIVE_DELETE_FLAG,
                )
                .update(
                    {
                        ResourceTagAssignment.delete_flag: DELETED_DELETE_FLAG,
                        ResourceTagAssignment.updated_by: actor_id,
                    },
                    synchronize_session=False,
                )
            )
            session.flush()
            return updated_count

    @staticmethod
    def soft_delete_document_assignments_for_knowledge_base(
        tenant_id: str,
        provider: str,
        knowledge_base_id: str,
        actor_id: str,
    ) -> int:
        """Soft-delete canonical document assignments when their parent knowledge base is removed."""

        with get_db_session() as session:
            assignments = (
                session.query(ResourceTagAssignment)
                .filter(
                    ResourceTagAssignment.tenant_id == tenant_id,
                    ResourceTagAssignment.resource_type == "knowledge_document",
                    ResourceTagAssignment.delete_flag == ACTIVE_DELETE_FLAG,
                )
                .all()
            )
            resource_ids = [
                assignment.resource_id
                for assignment in assignments
                if _is_document_assignment_in_knowledge_base(
                    assignment.resource_id, provider, knowledge_base_id
                )
            ]
            if not resource_ids:
                return 0
            updated_count = (
                session.query(ResourceTagAssignment)
                .filter(
                    ResourceTagAssignment.tenant_id == tenant_id,
                    ResourceTagAssignment.resource_type == "knowledge_document",
                    ResourceTagAssignment.resource_id.in_(resource_ids),
                    ResourceTagAssignment.delete_flag == ACTIVE_DELETE_FLAG,
                )
                .update(
                    {
                        ResourceTagAssignment.delete_flag: DELETED_DELETE_FLAG,
                        ResourceTagAssignment.updated_by: actor_id,
                    },
                    synchronize_session=False,
                )
            )
            session.flush()
            return updated_count
