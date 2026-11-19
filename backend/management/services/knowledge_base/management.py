# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""
Elasticsearch Application Interface Module

This module provides REST API interfaces for interacting with Elasticsearch, including index management, document
operations, and search functionality.
Main features include:
1. Index creation, deletion, and querying
2. Document indexing, deletion, and searching
3. Support for multiple search methods: exact search, semantic search, and hybrid search
4. Health check interface
"""

from typing import Any, Dict, List, Optional


from contracts.constants.constants import ASSET_OWNER_TENANT_ID, PERMISSION_PRIVATE, PERMISSION_READ
from contracts.roles import has_any_role, roles_from_record
from management.db.agent.repository import query_knowledge_binding_agents
from management.db.identity.group import query_group_ids_by_user
from management.db.identity.user_tenant import get_user_tenant_by_user_id
from management.db.knowledge_base.repository import (
    get_knowledge_info_by_tenant_id,
    get_knowledge_record,
    update_embedding_model_by_index_name,
    update_knowledge_record,
    update_model_name_by_index_name,
)
from management.db.model.repository import get_model_by_model_id
from management.services.knowledge_base.common import (
    _QUOTA_LIMIT_UNSET,
    logger,
)
from management.services.knowledge_base.files import (
    KnowledgeBaseFileService,
)
from management.services.knowledge_base.listing import (
    apply_read_only_to_asset_indices_info,
    merge_list_indices_results,
    merge_paginated_list_indices_results,
)
from management.services.knowledge_base.permission import (
    CREATOR_PERMISSION,
    filter_accessible_indices,
    require_knowledge_base_edit_permission,
    require_knowledge_base_read_permission,
    resolve_knowledge_base_permission,
)
from management.services.model.resolver import (
    get_model_descriptor,
)
from management.services.permission.asset_owner import postprocess_knowledge_visibility
from management.services.permission.identity import groups as group_service
from management.services.tag.projection import (
    project_authorized_resource_tags,
)
from management.utils.serialization import (
    convert_list_to_string,
    convert_string_to_list,
)
from nexent.vector_database.base import VectorDatabaseCore
from permissions.dac import ResourceAccessControl
from permissions.models import Resource


class KnowledgeBaseManagementService(KnowledgeBaseFileService):
    CREATOR_PERMISSION = CREATOR_PERMISSION
    resolve_knowledge_base_permission = staticmethod(resolve_knowledge_base_permission)
    require_knowledge_base_edit_permission = staticmethod(
        require_knowledge_base_edit_permission
    )
    require_knowledge_base_read_permission = staticmethod(
        require_knowledge_base_read_permission
    )
    filter_accessible_indices = staticmethod(filter_accessible_indices)

    @staticmethod
    def get_bound_agents(index_names: list[str], *, tenant_id: str) -> dict:
        """Preview agents affected by deleting the selected knowledge bases."""
        return {"agents": query_knowledge_binding_agents(index_names=index_names, tenant_id=tenant_id)}


    @staticmethod
    def update_knowledge_base(
        index_name: str,
        knowledge_name: Optional[str] = None,
        ingroup_permission: Optional[str] = None,
        group_ids: Optional[List[int]] = None,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        quota_limit_bytes: Any = _QUOTA_LIMIT_UNSET,
        user_role: Optional[str] = None,
    ) -> bool:
        """
        Update knowledge base information (name, group permission, group assignments).

        Args:
            index_name: Internal index name of the knowledge base
            knowledge_name: New display name for the knowledge base (optional)
            ingroup_permission: Permission level - EDIT, READ_ONLY, or PRIVATE (optional)
            group_ids: List of group IDs to assign (optional)
            tenant_id: ID of the tenant (optional, for validation)
            user_id: ID of the user making the update
            quota_limit_bytes: New soft quota in bytes; None removes the quota
            user_role: Caller role. USER callers may only manage PRIVATE
                personal knowledge bases and cannot turn them into shared KBs.

        Returns:
            bool: Whether the update was successful

        Raises:
            ValueError: If ingroup_permission is invalid
        """
        valid_permissions = ["EDIT", "READ_ONLY", "PRIVATE"]
        if (
            ingroup_permission is not None
            and ingroup_permission not in valid_permissions
        ):
            raise ValueError(
                f"Invalid ingroup_permission. Must be one of: {valid_permissions}"
            )

        if has_any_role(user_role, {"USER"}) and not has_any_role(user_role, {"DEV", "ADMIN", "SU", "ASSET_OWNER"}):
            record = get_knowledge_record({"index_name": index_name})
            if not record:
                raise ValueError(f"Knowledge base '{index_name}' not found")
            if (
                str(record.get("ingroup_permission") or "").upper()
                != PERMISSION_PRIVATE
            ):
                raise PermissionError(
                    "USER role can only manage PRIVATE personal knowledge bases"
                )
            if (
                ingroup_permission is not None
                and str(ingroup_permission).upper() != PERMISSION_PRIVATE
            ):
                raise PermissionError(
                    "USER role cannot turn a personal knowledge base into a shared knowledge base"
                )
            if group_ids is not None:
                raise PermissionError(
                    "USER role cannot assign groups to a personal knowledge base"
                )

        # Build update data for database
        update_data = {
            "index_name": index_name,
            "updated_by": user_id,
        }

        if knowledge_name is not None:
            update_data["knowledge_name"] = knowledge_name

        if ingroup_permission is not None:
            update_data["ingroup_permission"] = ingroup_permission

        if group_ids is not None:
            # Convert list to string for database storage
            update_data["group_ids"] = convert_list_to_string(group_ids)

        if quota_limit_bytes is not _QUOTA_LIMIT_UNSET:
            update_data["quota_limit_bytes"] = quota_limit_bytes

        # Call database update function
        result = update_knowledge_record(update_data)

        if result:
            logger.info(
                f"Knowledge base '{index_name}' updated successfully by user '{user_id}'"
            )

        return result

    @staticmethod
    def update_embedding_model(
        index_name: str,
        model_id: int,
        tenant_id: str,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Update the embedding model for a knowledge base.

        Args:
            index_name: Internal index name of the knowledge base
            model_id: ID of the embedding model to use
            tenant_id: Tenant ID
            user_id: ID of the user making the update

        Returns:
            Dict containing update result information

        Raises:
            ValueError: If model is not found or is not an embedding model
            Exception: If update fails
        """
        try:
            # Validate the model exists and is an embedding model
            model = get_model_by_model_id(model_id, tenant_id)
            if not model:
                raise ValueError(f"Model with id {model_id} not found")

            if model.get("model_type") not in ["embedding", "multi_embedding"]:
                raise ValueError(
                    f"Model '{model.get('display_name', model_id)}' is not an embedding model. "
                    f"Please select an embedding model."
                )

            # Update the database record
            # Use display_name as embedding_model_name
            embedding_model_name = model.get("display_name")
            success = update_embedding_model_by_index_name(
                index_name=index_name,
                embedding_model_id=model_id,
                embedding_model_name=embedding_model_name,
                tenant_id=tenant_id,
                user_id=user_id or "",
            )

            if not success:
                raise Exception(
                    f"Failed to update embedding model for index '{index_name}'"
                )

            logger.info(
                f"Embedding model updated for knowledge base '{index_name}' "
                f"to model '{model.get('display_name', model_id)}' (id: {model_id}) by user '{user_id}'"
            )

            # Use display_name for consistency with database update
            model_display_name = model.get("display_name")
            return {
                "status": "success",
                "index_name": index_name,
                "model_id": model_id,
                "model_name": model_display_name,
                "model_display_name": model.get("display_name"),
                "message": f"Embedding model updated successfully to '{model_display_name}'",
            }

        except ValueError:
            raise
        except Exception as e:
            logger.error(
                f"Failed to update embedding model for index '{index_name}': {e}"
            )
            raise Exception(f"Failed to update embedding model: {str(e)}")


    @staticmethod
    def _prepare_indices_page(
        visible_knowledgebases: List[Dict[str, Any]],
        pagination_enabled: bool,
        offset: int,
        limit: int | None,
        keyword: str | None,
        sources: List[str] | None,
        models: List[str] | None,
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Apply list filters and optional pagination to ordered visible records."""
        facets = {
            "sources": sorted(
                {
                    str(record.get("knowledge_sources"))
                    for record in visible_knowledgebases
                    if record.get("knowledge_sources")
                }
            ),
            "models": sorted(
                {
                    str(record.get("embedding_model_name"))
                    for record in visible_knowledgebases
                    if record.get("embedding_model_name")
                }
            ),
        }
        normalized_keyword = (keyword or "").strip().lower()
        selected_sources = {source for source in (sources or []) if source}
        selected_models = {model for model in (models or []) if model}
        filtered = [
            record
            for record in visible_knowledgebases
            if (
                not normalized_keyword
                or normalized_keyword in str(record.get("knowledge_name") or "").lower()
                or normalized_keyword in str(record.get("description") or "").lower()
                or normalized_keyword in str(record.get("nickname") or "").lower()
            )
            and (
                not selected_sources
                or record.get("knowledge_sources") in selected_sources
            )
            and (
                not selected_models
                or record.get("embedding_model_name") in selected_models
            )
        ]
        if not pagination_enabled:
            return filtered, {}
        if limit is None:
            raise ValueError("limit is required when pagination is enabled")

        total = len(filtered)
        page = filtered[offset : offset + limit]
        next_offset = offset + len(page)
        return page, {
            "total": total,
            "next_offset": next_offset if next_offset < total else None,
            "facets": facets,
        }

    _apply_read_only_to_asset_indices_info = staticmethod(
        apply_read_only_to_asset_indices_info
    )
    merge_list_indices_results = staticmethod(merge_list_indices_results)
    merge_paginated_list_indices_results = staticmethod(
        merge_paginated_list_indices_results
    )

    @staticmethod
    def list_indices(
        pattern: str = "*",
        include_stats: bool = False,
        target_tenant_id: str = "",
        user_id: str = "",
        vdb_core: VectorDatabaseCore | None = None,
        pagination_enabled: bool = False,
        offset: int = 0,
        limit: int | None = None,
        keyword: str | None = None,
        sources: List[str] | None = None,
        models: List[str] | None = None,
        *,
        inventory_read: bool = False,
    ):
        """
        List all indices that the current user has permissions to access based on role and group permissions.

        Permission logic:
        - SU: All knowledgebases visible, all editable
        - ADMIN: Knowledgebases from same tenant visible, all editable
        - DEV on ASSET_OWNER-scoped records: all visible, read-only (READ_ONLY)
        - SU/ADMIN cross-tenant view of ASSET_OWNER records: read-only
        - USER/DEV (non-ASSET_OWNER records): group intersection required; permission by:
            * If user is creator: editable
            * If ingroup_permission=EDIT: editable
            * If ingroup_permission=READ_ONLY: read-only
            * If ingroup_permission=PRIVATE: not visible

        Also syncs PG database with ES, removing data that is not in ES.

        Args:
            pattern: Pattern to match index names
            include_stats: Whether to include index stats
            target_tenant_id: ID of the tenant to list knowledge bases for
            user_id: ID of the user listing the knowledge base
            vdb_core: VectorDatabaseCore instance

        Returns:
            Dict[str, Any]: A dictionary containing the list of visible knowledgebases with permissions.
        """
        # Get user tenant information for permission checking
        user_tenant = get_user_tenant_by_user_id(user_id)
        if not user_tenant:
            return {"indices": [], "count": 0}

        user_role = roles_from_record(user_tenant)
        user_tenant_id = str(user_tenant.get("tenant_id") or target_tenant_id or "")
        # Get user group IDs from tenant_group_user_t table
        user_group_ids = [] if inventory_read else query_group_ids_by_user(user_id)

        # Get all indices from Elasticsearch
        es_indices_list = vdb_core.get_user_indices(pattern)

        # Get all knowledgebase records from database (for cleanup and permission checking)
        if pagination_enabled:
            all_db_records = get_knowledge_info_by_tenant_id(
                target_tenant_id,
                ordered=True,
            )
        else:
            all_db_records = get_knowledge_info_by_tenant_id(target_tenant_id)

        # Filter visible knowledgebases based on user role and permissions
        visible_knowledgebases = []
        model_name_is_none_list = []

        for record in all_db_records:
            index_name = record["index_name"]
            if record["knowledge_sources"] == "datamate":
                continue
            # Check if index exists in Elasticsearch (skip if not found)
            if index_name not in es_indices_list:
                continue

            effective_user_role = user_role
            effective_user_tenant_id = user_tenant_id
            if has_any_role(user_role, {"SU"}):
                effective_user_tenant_id = target_tenant_id
            if inventory_read:
                permission = PERMISSION_READ
            else:
                access = ResourceAccessControl.check(
                    Resource(
                        resource_type="knowledge_base",
                        resource_id=index_name,
                        tenant_id=record.get("tenant_id"),
                        created_by=record.get("created_by"),
                        ingroup_permission=record.get("ingroup_permission"),
                        group_ids=record.get("group_ids"),
                        knowledge_sources=record.get("knowledge_sources"),
                    ),
                    user_id=user_id,
                    role=effective_user_role,
                    user_groups=user_group_ids,
                    user_tenant_id=effective_user_tenant_id,
                    asset_owner_tenant_id=ASSET_OWNER_TENANT_ID,
                )
                permission = access.permission_label

            # Add to visible list if permission is granted
            if permission:
                record_with_permission = dict(record)
                record_with_permission["permission"] = permission
                # Convert group_ids string to list for easier client consumption
                if record.get("group_ids"):
                    record_with_permission["group_ids"] = convert_string_to_list(
                        record["group_ids"]
                    )
                else:
                    # If no group_ids specified, use tenant default group
                    default_group_id = group_service.get_tenant_default_group_id(
                        record.get("tenant_id")
                    )
                    record_with_permission["group_ids"] = (
                        [default_group_id] if default_group_id else []
                    )
                visible_knowledgebases.append(record_with_permission)

                # Track records with missing embedding model for stats update
                if record.get("embedding_model_name") is None:
                    model_name_is_none_list.append(index_name)

        # Build response
        visible_knowledgebases = postprocess_knowledge_visibility(
            visible_knowledgebases,
            caller_role=user_role,
            caller_tenant_id=target_tenant_id,
        )

        visible_knowledgebases, pagination = (
            KnowledgeBaseManagementService._prepare_indices_page(
                visible_knowledgebases=visible_knowledgebases,
                pagination_enabled=pagination_enabled,
                offset=offset,
                limit=limit,
                keyword=keyword,
                sources=sources,
                models=models,
            )
        )

        indices = [record["index_name"] for record in visible_knowledgebases]

        if include_stats:

            visible_knowledgebases = project_authorized_resource_tags(
                visible_knowledgebases,
                resource_type="knowledge_base",
                id_field="index_name",
                default_tenant_id=target_tenant_id,
            )

        response = {
            "indices": indices,
            "count": len(indices),
            "index_permissions": {
                record["index_name"]: record["permission"]
                for record in visible_knowledgebases
            },
        }
        if pagination_enabled:
            response.update(
                {
                    **pagination,
                    "estimated_row_height": 112,
                    "estimated_item_heights": None,
                }
            )

        if include_stats:
            stats_info = []
            if visible_knowledgebases:
                index_names = [
                    record["index_name"] for record in visible_knowledgebases
                ]
                indice_stats = vdb_core.get_indices_detail(index_names)

                for record in visible_knowledgebases:
                    index_name = record["index_name"]
                    index_stats = indice_stats.get(index_name, {})

                    # Get embedding model display_name from model_id
                    model_id = record.get("embedding_model_id")
                    tenant_id = record.get("tenant_id") or target_tenant_id
                    model_descriptor = get_model_descriptor(model_id, tenant_id)
                    embedding_model_display_name = model_descriptor.display_name
                    is_multimodal = model_descriptor.is_multimodal

                    stats_info.append(
                        {
                            "knowledge_id": record.get("knowledge_id"),
                            "tags": record.get("tags", []),
                            # Internal index name (used as ID)
                            "name": index_name,
                            # User-facing knowledge base name from PostgreSQL (fallback to index_name)
                            "display_name": record.get("knowledge_name", index_name),
                            "permission": record["permission"],
                            "group_ids": record["group_ids"],
                            # knowledge source and ingroup permission from DB record
                            "knowledge_sources": record["knowledge_sources"],
                            "ingroup_permission": record["ingroup_permission"],
                            "is_multimodal": is_multimodal,
                            "tenant_id": record.get("tenant_id"),
                            # Embedding model info: display_name from model_id
                            "embedding_model_name": embedding_model_display_name
                            or record.get("embedding_model_name", ""),
                            "embedding_model_id": model_id,
                            # Update time for sorting and display
                            "update_time": record.get("update_time"),
                            # Auto-summary settings
                            "summary_frequency": record.get("summary_frequency"),
                            "last_summary_time": record.get("last_summary_time"),
                            "preserve_source_file": record.get(
                                "preserve_source_file", True
                            ),
                            "stats": index_stats,
                        }
                    )

                    # Update model name if missing
                    if not inventory_read and index_name in model_name_is_none_list:
                        update_model_name_by_index_name(
                            index_name,
                            index_stats.get("base_info", {}).get("embedding_model", ""),
                            record.get("tenant_id", target_tenant_id),
                            user_id,
                        )

            response["indices_info"] = stats_info

        return response

    DOCUMENT_DELETE_SCOPES = ("source_only", "full")
