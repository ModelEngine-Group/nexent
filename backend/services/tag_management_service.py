"""Business operations for fixed tenant tag libraries."""

import logging
from uuid import uuid4

from consts.const import TAG_DOCUMENT_PROJECTION_ENABLED
from consts.exceptions import (
    TagManagementConflictError,
    TagManagementNotFoundError,
    ValidationError,
)
from database.tag_management_db import TagManagementDB
from services.tag_resource_adapters import (
    DEFAULT_TAG_RESOURCE_ADAPTER_REGISTRY,
    AuthenticatedCaller,
    ResourceReference,
    _encode_document_resource_id,
)
from sqlalchemy.exc import DBAPIError, IntegrityError

logger = logging.getLogger(__name__)


class TagManagementService:
    """Keep tag-library governance separate from resource assignment operations."""

    resource_adapter_registry = DEFAULT_TAG_RESOURCE_ADAPTER_REGISTRY

    @staticmethod
    def _translate_database_error(error: Exception) -> None:
        message = str(error)
        if "Tag definition limit exceeded" in message:
            raise TagManagementConflictError(
                "Tag definition capacity exceeded",
                {"limit": 100, "current_count": 100, "scope": "definition"},
            )
        if "Tag value limit exceeded" in message:
            raise TagManagementConflictError(
                "Tag value capacity exceeded",
                {"limit": 1000, "current_count": 1000, "scope": "value"},
            )
        if "Resource tag assignment limit exceeded" in message:
            raise TagManagementConflictError(
                "Resource tag assignment capacity exceeded",
                {"limit": 100, "current_count": 100, "scope": "assignment"},
            )
        if (
            "uq_tag_definition" in message
            or "uq_tag_value" in message
            or "duplicate key" in message
        ):
            raise TagManagementConflictError(
                "A tag definition or value with the same normalized name already exists"
            )
        raise error

    @classmethod
    def list_libraries(cls, tenant_id: str) -> list[dict]:
        return TagManagementDB.list_libraries(tenant_id)

    @classmethod
    def list_definitions(cls, tenant_id: str, bucket_id: int) -> list[dict]:
        return TagManagementDB.list_definitions(tenant_id, bucket_id)

    @classmethod
    def create_definition(
        cls, tenant_id: str, bucket_id: int, request, actor_id: str
    ) -> dict:
        try:
            return TagManagementDB.create_definition(
                tenant_id,
                bucket_id,
                request.definition_key or f"custom_{uuid4().hex}",
                request.definition_name,
                request.selection_mode,
                request.initial_values,
                request.sort_order,
                actor_id,
            )
        except (IntegrityError, DBAPIError) as error:
            cls._translate_database_error(error)

    @classmethod
    def update_definition(
        cls, tenant_id: str, bucket_id: int, definition_id: int, request, actor_id: str
    ) -> dict:
        if request.definition_name is None and request.selection_mode is None:
            raise ValidationError("At least one definition field must be provided")
        try:
            definition, multiple_resource_count = TagManagementDB.update_definition(
                tenant_id,
                bucket_id,
                definition_id,
                request.definition_name,
                request.selection_mode,
                actor_id,
            )
        except (IntegrityError, DBAPIError) as error:
            cls._translate_database_error(error)
        if multiple_resource_count:
            raise TagManagementConflictError(
                "Cannot convert to single_select while resources have multiple assigned values",
                {
                    "definition_id": definition_id,
                    "resources_with_multiple_values": multiple_resource_count,
                },
            )
        return definition

    @classmethod
    def set_definition_status(
        cls,
        tenant_id: str,
        bucket_id: int,
        definition_id: int,
        status: str,
        actor_id: str,
    ) -> dict:
        return TagManagementDB.set_definition_status(
            tenant_id, bucket_id, definition_id, status, actor_id
        )

    @classmethod
    def set_definition_order(
        cls,
        tenant_id: str,
        bucket_id: int,
        definition_id: int,
        sort_order: int,
        actor_id: str,
    ) -> dict:
        return TagManagementDB.set_definition_order(
            tenant_id, bucket_id, definition_id, sort_order, actor_id
        )

    @classmethod
    def move_definition_to_top(
        cls,
        tenant_id: str,
        bucket_id: int,
        definition_id: int,
        actor_id: str,
    ) -> dict:
        return TagManagementDB.move_definition_to_top(
            tenant_id, bucket_id, definition_id, actor_id
        )

    @classmethod
    def get_definition_usage(
        cls, tenant_id: str, bucket_id: int, definition_id: int
    ) -> dict:
        return TagManagementDB.get_definition_usage(tenant_id, bucket_id, definition_id)

    @classmethod
    def delete_definition(
        cls, tenant_id: str, bucket_id: int, definition_id: int, actor_id: str
    ) -> None:
        usage = TagManagementDB.delete_definition(
            tenant_id, bucket_id, definition_id, actor_id
        )
        if usage["active_value_count"] or usage["active_usage_count"]:
            raise TagManagementConflictError(
                "Cannot delete a tag definition with values or active assignments",
                {"definition_id": definition_id, **usage},
            )

    @classmethod
    def create_value(
        cls, tenant_id: str, bucket_id: int, definition_id: int, request, actor_id: str
    ) -> dict:
        try:
            return TagManagementDB.create_value(
                tenant_id,
                bucket_id,
                definition_id,
                request.display_value,
                request.sort_order,
                actor_id,
            )
        except (IntegrityError, DBAPIError) as error:
            cls._translate_database_error(error)

    @classmethod
    def update_value(
        cls,
        tenant_id: str,
        bucket_id: int,
        definition_id: int,
        value_id: int,
        request,
        actor_id: str,
    ) -> dict:
        try:
            return TagManagementDB.update_value(
                tenant_id,
                bucket_id,
                definition_id,
                value_id,
                request.display_value,
                actor_id,
            )
        except (IntegrityError, DBAPIError) as error:
            cls._translate_database_error(error)

    @classmethod
    def set_value_status(
        cls,
        tenant_id: str,
        bucket_id: int,
        definition_id: int,
        value_id: int,
        status: str,
        actor_id: str,
    ) -> dict:
        return TagManagementDB.set_value_status(
            tenant_id, bucket_id, definition_id, value_id, status, actor_id
        )

    @classmethod
    def set_value_order(
        cls,
        tenant_id: str,
        bucket_id: int,
        definition_id: int,
        value_id: int,
        sort_order: int,
        actor_id: str,
    ) -> dict:
        return TagManagementDB.set_value_order(
            tenant_id, bucket_id, definition_id, value_id, sort_order, actor_id
        )

    @classmethod
    def get_value_usage(
        cls, tenant_id: str, bucket_id: int, definition_id: int, value_id: int
    ) -> dict:
        return TagManagementDB.get_value_usage(
            tenant_id, bucket_id, definition_id, value_id
        )

    @classmethod
    def delete_value(
        cls,
        tenant_id: str,
        bucket_id: int,
        definition_id: int,
        value_id: int,
        actor_id: str,
    ) -> None:
        usage_count = TagManagementDB.delete_value(
            tenant_id, bucket_id, definition_id, value_id, actor_id
        )
        if usage_count:
            raise TagManagementConflictError(
                "Cannot delete a tag value that is in use",
                {"value_id": value_id, "active_usage_count": usage_count},
            )

    @classmethod
    async def _resolve_assignment_resource(
        cls,
        caller: AuthenticatedCaller,
        resource_type: str,
        resource_id: str,
        *,
        require_edit: bool,
        provider: str | None = None,
        knowledge_base_id: str | None = None,
    ):
        resolved = await cls.resource_adapter_registry.resolve(
            ResourceReference(
                resource_type=resource_type,
                resource_id=resource_id,
                provider=provider,
                knowledge_base_id=knowledge_base_id,
            ),
            caller,
        )
        if (
            not resolved.found
            or resolved.identity is None
            or (require_edit and not resolved.capabilities.can_edit)
            or (not require_edit and not resolved.capabilities.can_read)
        ):
            raise TagManagementNotFoundError("Resource not found")
        return resolved.identity

    @classmethod
    async def get_resource_assignments(
        cls,
        caller: AuthenticatedCaller,
        resource_type: str,
        resource_id: str,
        *,
        provider: str | None = None,
        knowledge_base_id: str | None = None,
    ) -> dict:
        identity = await cls._resolve_assignment_resource(
            caller,
            resource_type,
            resource_id,
            require_edit=False,
            provider=provider,
            knowledge_base_id=knowledge_base_id,
        )
        assignments = TagManagementDB.list_resource_assignments(
            caller.authenticated_tenant_id,
            identity.resource_type.value,
            identity.resource_id,
            identity.library_code,
        )
        return {
            "resource_type": identity.resource_type.value,
            "resource_id": identity.resource_id,
            "assignment_count": len(assignments),
            "assignment_capacity": 100,
            "assignments": assignments,
        }

    @classmethod
    async def replace_resource_assignments(
        cls,
        caller: AuthenticatedCaller,
        resource_type: str,
        resource_id: str,
        value_ids: list[int],
        *,
        provider: str | None = None,
        knowledge_base_id: str | None = None,
    ) -> dict:
        identity = await cls._resolve_assignment_resource(
            caller,
            resource_type,
            resource_id,
            require_edit=True,
            provider=provider,
            knowledge_base_id=knowledge_base_id,
        )
        normalized_value_ids = list(dict.fromkeys(value_ids))
        try:
            assignments = TagManagementDB.replace_resource_assignments(
                caller.authenticated_tenant_id,
                identity.resource_type.value,
                identity.resource_id,
                identity.library_code,
                normalized_value_ids,
                caller.user_id,
            )
        except (IntegrityError, DBAPIError) as error:
            cls._translate_database_error(error)
        projection_status = None
        if (
            identity.resource_type.value == "knowledge_document"
            and identity.provider
            and identity.knowledge_base_id
            and identity.provider_document_id
        ):
            try:
                from services.tag_document_projection import (
                    project_document_assignments,
                )

                projection_status = project_document_assignments(
                    caller.authenticated_tenant_id,
                    identity.provider,
                    identity.knowledge_base_id,
                    identity.provider_document_id,
                    caller.user_id,
                    enabled=TAG_DOCUMENT_PROJECTION_ENABLED,
                )
            except Exception as error:
                logger.exception("Document tag projection hook failed: %s", error)  # noqa: TRY401
        return {
            "resource_type": identity.resource_type.value,
            "resource_id": identity.resource_id,
            "assignment_count": len(assignments),
            "assignment_capacity": 100,
            "assignments": assignments,
            "projection_status": projection_status,
        }

    @classmethod
    async def replace_resource_assignments_bulk(
        cls, caller: AuthenticatedCaller, resource_type: str, targets: list
    ) -> list[dict]:
        """Internal bulk primitive with explicit outcome per supplied target."""

        outcomes = []
        for target in targets:
            try:
                document_context = {}
                if target.provider is not None:
                    document_context["provider"] = target.provider
                if target.knowledge_base_id is not None:
                    document_context["knowledge_base_id"] = target.knowledge_base_id
                assignment = await cls.replace_resource_assignments(
                    caller,
                    resource_type,
                    target.resource_id,
                    target.value_ids,
                    **document_context,
                )
            except TagManagementNotFoundError:
                outcomes.append(
                    {
                        "resource_id": target.resource_id,
                        "outcome": "not_found_or_forbidden",
                    }
                )
            except (ValidationError, TagManagementConflictError) as error:
                outcomes.append(
                    {
                        "resource_id": target.resource_id,
                        "outcome": "validation",
                        "message": str(error),
                        "details": getattr(error, "details", None),
                    }
                )
            else:
                # Bulk updates report each successful target alongside partial failures.
                outcomes.append(
                    {
                        "resource_id": target.resource_id,
                        "outcome": "updated",
                        "assignment": assignment,
                    }
                )
        return outcomes

    @classmethod
    async def get_document_tag_batch_status(
        cls,
        caller: AuthenticatedCaller,
        provider: str,
        knowledge_base_id: str,
        document_ids: list[str],
        predicates: list | None = None,
    ) -> list[dict]:
        """Batch tag status for a provider knowledge base, read-scoped by the caller."""

        normalized_provider = (provider or "").strip().lower()
        if not normalized_provider:
            raise ValidationError("provider is required for document tag status")
        if not knowledge_base_id or not str(knowledge_base_id).strip():
            raise ValidationError("knowledge_base_id is required for document tag status")
        resolved = await cls.resource_adapter_registry.resolve(
            ResourceReference(
                resource_type="knowledge_base",
                resource_id=str(knowledge_base_id).strip(),
                provider=normalized_provider,
            ),
            caller,
        )
        if not resolved.found or not resolved.capabilities.can_read:
            raise TagManagementNotFoundError("Knowledge base not found")
        if not document_ids:
            return []
        unique_ids = list(dict.fromkeys(str(document_id) for document_id in document_ids))
        if len(unique_ids) > 200:
            raise ValidationError("A batch may include at most 200 documents")
        encoded_to_document_id = {
            _encode_document_resource_id(normalized_provider, str(knowledge_base_id).strip(), document_id): document_id
            for document_id in unique_ids
        }
        encoded_ids = list(encoded_to_document_id.keys())
        assignment_counts = TagManagementDB.count_resource_assignments_by_ids(
            caller.authenticated_tenant_id,
            "knowledge_document",
            encoded_ids,
        )
        if predicates:
            filtered_encoded = cls.filter_authorized_resource_ids(
                caller.authenticated_tenant_id,
                "knowledge_document",
                encoded_ids,
                predicates,
            )
            filtered = set(filtered_encoded)
            encoded_ids = [resource_id for resource_id in encoded_ids if resource_id in filtered]
        states = {}
        try:
            from database import document_tag_projection_db

            states = document_tag_projection_db.list_projection_states_for_knowledge_base(
                caller.authenticated_tenant_id,
                normalized_provider,
                str(knowledge_base_id).strip(),
            )
        except Exception as error:  # noqa: BLE001 - ledger is best-effort for read status
            logger.warning("Failed to load document projection states: %s", error)
        results = []
        for encoded_id in encoded_ids:
            provider_document_id = encoded_to_document_id[encoded_id]
            state = states.get(provider_document_id)
            projection_status = None
            if state is not None:
                try:
                    from services.tag_document_projection import (
                        document_projection_status_dict,
                    )

                    projection_status = document_projection_status_dict(state)
                except Exception as error:  # noqa: BLE001 - never fail the batch for one row
                    logger.warning("Failed to build projection status: %s", error)
            results.append({
                "document_id": provider_document_id,
                "assignment_count": int(assignment_counts.get(encoded_id, 0)),
                "projection_status": projection_status,
            })
        return results

    @classmethod
    def filter_authorized_resource_ids(
        cls,
        tenant_id: str,
        resource_type: str,
        authorized_resource_ids: list[str],
        filters: list,
    ) -> list[str]:
        """Apply tag predicates after the owning list flow has authorized IDs."""

        return TagManagementDB.filter_authorized_resource_ids(
            tenant_id, resource_type, authorized_resource_ids, filters
        )

    @classmethod
    def filter_resource_ids_for_caller(
        cls,
        caller: AuthenticatedCaller,
        resource_type: str,
        authorized_resource_ids: list[str],
        predicates: list,
    ) -> dict:
        """Narrow a caller-supplied, already-authorized resource id set.

        The tag service never widens scope: it only intersects the caller's
        authorized ids with resources matching every predicate (OR within a
        definition, AND across definitions). Document resources are rejected
        because they have a dedicated batch-status endpoint.
        """
        from services.tag_resource_adapters import ResourceType

        normalized_type = str(resource_type).strip()
        if normalized_type == ResourceType.KNOWLEDGE_DOCUMENT.value:
            raise ValidationError("document resources must use the batch-status endpoint")
        supported = {member.value for member in ResourceType}
        if normalized_type not in supported:
            raise ValidationError(f"unsupported resource type: {normalized_type}")
        matched = cls.filter_authorized_resource_ids(
            caller.authenticated_tenant_id,
            normalized_type,
            authorized_resource_ids,
            predicates,
        )
        return {
            "resource_type": normalized_type,
            "matched_resource_ids": matched,
        }

    @classmethod
    def cleanup_resource_assignments(
        cls,
        tenant_id: str,
        resource_type: str,
        resource_id: str,
        actor_id: str,
    ) -> int:
        """Remove assignments after an owner service has proven and deleted a resource."""

        return TagManagementDB.soft_delete_resource_assignments(
            tenant_id, resource_type, resource_id, actor_id
        )

    @classmethod
    def cleanup_document_assignments(
        cls,
        tenant_id: str,
        provider: str,
        knowledge_base_id: str,
        provider_document_id: str,
        actor_id: str,
    ) -> int:
        """Clean up one document after its provider has completed deletion."""

        deleted = cls.cleanup_resource_assignments(
            tenant_id,
            "knowledge_document",
            _encode_document_resource_id(provider, knowledge_base_id, provider_document_id),
            actor_id,
        )
        try:
            from services.tag_document_projection import clear_document_projection

            clear_document_projection(
                tenant_id, provider, knowledge_base_id, provider_document_id
            )
        except Exception as error:  # noqa: BLE001 - best-effort ledger cleanup
            logger.warning("Failed to clear document projection ledger: %s", error)
        return deleted

    @classmethod
    def cleanup_document_assignments_for_knowledge_base(
        cls,
        tenant_id: str,
        provider: str,
        knowledge_base_id: str,
        actor_id: str,
    ) -> int:
        """Clean up document assignments after their provider knowledge base is deleted."""

        deleted = TagManagementDB.soft_delete_document_assignments_for_knowledge_base(
            tenant_id, provider, knowledge_base_id, actor_id
        )
        try:
            from services.tag_document_projection import (
                clear_projection_states_for_knowledge_base,
            )

            clear_projection_states_for_knowledge_base(
                tenant_id, provider, knowledge_base_id
            )
        except Exception as error:  # noqa: BLE001 - best-effort ledger cleanup
            logger.warning("Failed to clear knowledge base projection ledger: %s", error)
        return deleted

    @classmethod
    async def get_document_projection_status(
        cls,
        caller: AuthenticatedCaller,
        resource_type: str,
        resource_id: str,
        *,
        provider: str | None = None,
        knowledge_base_id: str | None = None,
    ) -> dict:
        identity = await cls._resolve_assignment_resource(
            caller,
            resource_type,
            resource_id,
            require_edit=False,
            provider=provider,
            knowledge_base_id=knowledge_base_id,
        )
        if not (identity.provider and identity.knowledge_base_id and identity.provider_document_id):
            raise ValidationError("Document projection status requires a provider document")
        from services.tag_document_projection import get_document_projection_status

        return get_document_projection_status(
            caller.authenticated_tenant_id,
            identity.provider,
            identity.knowledge_base_id,
            identity.provider_document_id,
        )

    @classmethod
    async def get_legacy_flat_tags_projection(
        cls,
        caller: AuthenticatedCaller,
        resource_type: str,
        resource_id: str,
        *,
        provider: str | None = None,
        knowledge_base_id: str | None = None,
        limit: int = 100,
    ) -> dict:
        """Return the bounded deprecated flat-array projection for a resource.

        The flat value-name array is derived from active structured assignments
        and is deprecated: it exists only for the two-minor-release compatibility
        window and SHALL NOT be used by new clients.
        """

        identity = await cls._resolve_assignment_resource(
            caller,
            resource_type,
            resource_id,
            require_edit=False,
            provider=provider,
            knowledge_base_id=knowledge_base_id,
        )
        assignments = TagManagementDB.list_resource_assignments(
            caller.authenticated_tenant_id,
            identity.resource_type.value,
            identity.resource_id,
            identity.library_code,
        )
        bounded_limit = max(1, min(int(limit), 100))
        tags = sorted({item["display_value"] for item in assignments})[:bounded_limit]
        return {
            "resource_type": identity.resource_type.value,
            "resource_id": identity.resource_id,
            "tags": tags,
            "count": len(tags),
            "limit": bounded_limit,
            "deprecated": True,
        }

    @classmethod
    def filter_document_ids_by_predicates(
        cls,
        tenant_id: str,
        provider: str,
        knowledge_base_id: str,
        predicates: list[dict],
    ) -> list[str]:
        from services.tag_document_projection import filter_document_ids_by_predicates

        return filter_document_ids_by_predicates(
            tenant_id, provider, knowledge_base_id, predicates
        )

    @classmethod
    def retry_pending_document_projections(
        cls,
        tenant_id: str | None = None,
        limit: int = 50,
    ) -> dict:
        from services.tag_document_projection import retry_pending_document_projections

        return retry_pending_document_projections(tenant_id=tenant_id, limit=limit)
