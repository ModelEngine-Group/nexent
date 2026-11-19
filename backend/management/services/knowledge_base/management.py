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

from contracts.constants.constants import (
    PERMISSION_PRIVATE,
)
from contracts.roles import has_any_role
from management.db.agent.repository import query_knowledge_binding_agents
from management.db.knowledge_base.repository import (
    get_knowledge_record,
    update_embedding_model_by_index_name,
    update_knowledge_record,
)
from management.db.model.repository import get_model_by_model_id
from management.services.knowledge_base.common import (
    _QUOTA_LIMIT_UNSET,
    logger,
)
from management.services.knowledge_base.permission import (
    CREATOR_PERMISSION,
    filter_accessible_indices,
    require_knowledge_base_edit_permission,
    require_knowledge_base_read_permission,
    resolve_knowledge_base_permission,
)
from management.utils.serialization import (
    convert_list_to_string,
)


class KnowledgeBaseManagementService:
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





    DOCUMENT_DELETE_SCOPES = ("source_only", "full")
