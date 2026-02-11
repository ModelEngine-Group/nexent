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
import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, Path, Query
from fastapi.responses import StreamingResponse
from nexent.core.models.embedding_model import OpenAICompatibleEmbedding, JinaEmbedding, BaseEmbedding
from nexent.vector_database.base import VectorDatabaseCore
from nexent.vector_database.elasticsearch_core import ElasticSearchCore
from nexent.vector_database.datamate_core import DataMateCore

from consts.const import DATAMATE_URL, ES_API_KEY, ES_HOST, LANGUAGE, VectorDatabaseType, IS_SPEED_MODE, PERMISSION_EDIT, PERMISSION_READ
from consts.model import ChunkCreateRequest, ChunkUpdateRequest
from database.attachment_db import delete_file
from database.knowledge_db import (
    create_knowledge_record,
    delete_knowledge_record,
    get_knowledge_record,
    update_knowledge_record,
    get_knowledge_info_by_tenant_id,
    update_model_name_by_index_name,
)
from utils.str_utils import convert_list_to_string
from database.user_tenant_db import get_user_tenant_by_user_id
from database.group_db import query_group_ids_by_user
from database.model_management_db import get_model_records
from services.redis_service import get_redis_service
from services.group_service import get_tenant_default_group_id
from utils.config_utils import tenant_config_manager, get_model_name_from_config
from utils.file_management_utils import get_all_files_status, get_file_size
from utils.str_utils import convert_string_to_list


def _update_progress(task_id: str, processed: int, total: int):
    """Helper function to update progress in Redis"""
    try:
        redis_service = get_redis_service()

        # If this task has been marked as cancelled, stop updating progress
        # and raise an exception so the caller can abort long-running work.
        if redis_service.is_task_cancelled(task_id):
            logger.debug(
                f"[PROGRESS CALLBACK] Task {task_id} is marked as cancelled; "
                f"stopping further indexing work at {processed}/{total}."
            )
            raise RuntimeError(
                "Indexing cancelled because the task was marked as cancelled.")

        success = redis_service.save_progress_info(task_id, processed, total)
        if success:
            percentage = processed * 100 // total if total > 0 else 0
            logger.debug(
                f"[PROGRESS CALLBACK] Updated progress for task {task_id}: {processed}/{total} ({percentage}%)")
        else:
            logger.warning(
                f"[PROGRESS CALLBACK] Failed to save progress for task {task_id}: {processed}/{total}")
    except Exception as e:
        logger.warning(
            f"[PROGRESS CALLBACK] Exception updating progress for task {task_id}: {str(e)}")


ALLOWED_CHUNK_FIELDS = {
    "id",
    "title",
    "filename",
    "path_or_url",
    "content",
    "create_time",
    "language",
    "author",
    "date",
}

# Configure logging
logger = logging.getLogger("vectordatabase_service")


def get_vector_db_core(
    db_type: VectorDatabaseType = VectorDatabaseType.ELASTICSEARCH, tenant_id: Optional[str] = None,
) -> VectorDatabaseCore:
    """
    Return a VectorDatabaseCore implementation based on the requested type.

    Args:
        db_type: Target vector database provider. Defaults to Elasticsearch.
        tenant_id: Tenant ID for configuration lookup (required for DataMate).

    Returns:
        VectorDatabaseCore: Concrete vector database implementation.

    Raises:
        ValueError: If the requested database type is not supported.
    """
    if db_type == VectorDatabaseType.ELASTICSEARCH:
        return ElasticSearchCore(
            host=ES_HOST,
            api_key=ES_API_KEY,
            verify_certs=False,
            ssl_show_warn=False,
        )

    if db_type == VectorDatabaseType.DATAMATE:
        if tenant_id:
            datamate_url = tenant_config_manager.get_app_config(
                DATAMATE_URL, tenant_id=tenant_id)
            if not datamate_url:
                raise ValueError(
                    f"DataMate URL not configured for tenant {tenant_id}")
            return DataMateCore(base_url=datamate_url)
        else:
            raise ValueError("tenant_id must be provided for DataMate")

    raise ValueError(f"Unsupported vector database type: {db_type}")


def _rethrow_or_plain(exc: Exception) -> None:
    """
    If the exception message is a JSON dict with error_code, re-raise that JSON as-is.
    Otherwise, re-raise the original string (no additional nesting/context).
    """
    msg = str(exc)
    try:
        parsed = json.loads(msg)
    except Exception:
        raise Exception(msg)

    if isinstance(parsed, dict) and parsed.get("error_code"):
        raise Exception(json.dumps(parsed, ensure_ascii=False))

    raise Exception(msg)


def check_knowledge_base_exist_impl(knowledge_name: str, vdb_core: VectorDatabaseCore, user_id: str, tenant_id: str) -> dict:
    """
    Check knowledge base existence and handle orphan cases

    Args:
        knowledge_name: Name of the knowledge base to check
        vdb_core: Elasticsearch core instance
        user_id: Current user ID
        tenant_id: Current tenant ID

    Returns:
        dict: Status information about the knowledge base
    """
    # 1. Check if knowledge_name exists in PG for the current tenant
    pg_record = get_knowledge_record(
        {"knowledge_name": knowledge_name, "tenant_id": tenant_id})

    # Case A: Knowledge base name already exists in the same tenant
    if pg_record:
        return {"status": "exists_in_tenant"}

    # Case B: Name is available in this tenant
    return {"status": "available"}


def get_embedding_model(tenant_id: str, model_name: Optional[str] = None):
    """
    Get the embedding model for the tenant, optionally using a specific model name.

    Args:
        tenant_id: Tenant ID
        model_name: Optional specific model name to use (format: "model_repo/model_name" or just "model_name")
                   If provided, will try to find the model in the tenant's model list.

    Returns:
        Embedding model instance or None
    """
    # If model_name is provided, try to find it in the tenant's models
    if model_name:
        try:
            models = get_model_records({"model_type": "embedding"}, tenant_id)
            for model in models:
                model_display_name = model.get("model_repo") + "/" + model["model_name"] if model.get("model_repo") else model["model_name"]
                if model_display_name == model_name:
                    # Found the model, create embedding instance
                    model_config = {
                        "model_repo": model.get("model_repo", ""),
                        "model_name": model["model_name"],
                        "api_key": model.get("api_key", ""),
                        "base_url": model.get("base_url", ""),
                        "model_type": "embedding",
                        "max_tokens": model.get("max_tokens", 1024),
                        "ssl_verify": model.get("ssl_verify", True),
                    }
                    return OpenAICompatibleEmbedding(
                        api_key=model_config.get("api_key", ""),
                        base_url=model_config.get("base_url", ""),
                        model_name=get_model_name_from_config(model_config) or "",
                        embedding_dim=model_config.get("max_tokens", 1024),
                        ssl_verify=model_config.get("ssl_verify", True),
                    )
        except Exception as e:
            logger.warning(f"Failed to get embedding model by name {model_name}: {e}")

    # Fall back to default embedding model (current behavior)
    model_config = tenant_config_manager.get_model_config(
        key="EMBEDDING_ID", tenant_id=tenant_id)

    model_type = model_config.get("model_type", "")

    if model_type == "embedding":
        # Get the es core
        return OpenAICompatibleEmbedding(
            api_key=model_config.get("api_key", ""),
            base_url=model_config.get("base_url", ""),
            model_name=get_model_name_from_config(model_config) or "",
            embedding_dim=model_config.get("max_tokens", 1024),
            ssl_verify=model_config.get("ssl_verify", True),
        )
    elif model_type == "multi_embedding":
        return JinaEmbedding(
            api_key=model_config.get("api_key", ""),
            base_url=model_config.get("base_url", ""),
            model_name=get_model_name_from_config(model_config) or "",
            embedding_dim=model_config.get("max_tokens", 1024),
            ssl_verify=model_config.get("ssl_verify", True),
        )
    else:
        return None


class ElasticSearchService:
    @staticmethod
    async def full_delete_knowledge_base(index_name: str, vdb_core: VectorDatabaseCore, user_id: str):
        """
        Completely delete a knowledge base, including its index, associated files in MinIO,
        and all related records in Redis and PostgreSQL.
        """
        logger.debug(
            f"Starting full deletion process for knowledge base (index): {index_name}")
        try:
            # 1. Get all files associated with the index from Elasticsearch
            logger.debug(
                f"Step 1/4: Retrieving file list for index: {index_name}")
            try:
                file_list_result = await ElasticSearchService.list_files(index_name, include_chunks=False,
                                                                         vdb_core=vdb_core)
                files_to_delete = file_list_result.get("files", [])
                logger.debug(
                    f"Found {len(files_to_delete)} files to delete from MinIO for index '{index_name}'.")
            except Exception as e:
                logger.error(
                    f"Failed to retrieve file list for index '{index_name}': {str(e)}")
                # We can still proceed to delete the index itself even if listing files fails
                files_to_delete = []

            # 2. Delete files from MinIO
            minio_deletion_success_count = 0
            minio_deletion_failure_count = 0
            if files_to_delete:
                logger.debug(
                    f"Step 2/4: Starting deletion of {len(files_to_delete)} files from MinIO.")
                for file_info in files_to_delete:
                    object_name = file_info.get("path_or_url")
                    if not object_name:
                        logger.warning(
                            f"Could not find 'path_or_url' for file entry: {file_info}. Skipping deletion.")
                        minio_deletion_failure_count += 1
                        continue

                    try:
                        logger.debug(
                            f"Deleting object: '{object_name}' from MinIO for index '{index_name}'")
                        delete_result = delete_file(object_name=object_name)
                        if delete_result.get("success"):
                            logger.debug(
                                f"Successfully deleted object: '{object_name}' from MinIO.")
                            minio_deletion_success_count += 1
                        else:
                            minio_deletion_failure_count += 1
                            error_msg = delete_result.get(
                                "error", "Unknown error")
                            logger.error(
                                f"Failed to delete object: '{object_name}' from MinIO. Reason: {error_msg}")
                    except Exception as e:
                        minio_deletion_failure_count += 1
                        logger.error(
                            f"An exception occurred while deleting object: '{object_name}' from MinIO. Error: {str(e)}")

                logger.info(f"MinIO file deletion summary for index '{index_name}': "
                            f"{minio_deletion_success_count} succeeded, {minio_deletion_failure_count} failed.")
            else:
                logger.debug(
                    f"Step 2/4: No files found in index '{index_name}', skipping MinIO deletion.")

            # 3. Mark all related tasks as cancelled and clean up Redis records BEFORE deleting ES index
            # This ensures ongoing indexing tasks will detect cancellation and stop immediately
            logger.debug(
                f"Step 3/5: Marking all tasks as cancelled and cleaning up Redis records for index '{index_name}'.")
            redis_cleanup_result = {}
            try:
                from services.redis_service import get_redis_service
                redis_service = get_redis_service()
                redis_cleanup_result = redis_service.delete_knowledgebase_records(
                    index_name)
                logger.debug(f"Redis cleanup for index '{index_name}' completed. "
                             f"Deleted {redis_cleanup_result['total_deleted']} records, "
                             f"marked {redis_cleanup_result.get('tasks_cancelled', 0)} tasks as cancelled.")
            except Exception as redis_error:
                logger.error(
                    f"Redis cleanup failed for index '{index_name}': {str(redis_error)}")
                redis_cleanup_result = {"error": str(redis_error)}

            # 4. Delete Elasticsearch index and its DB record
            logger.debug(
                f"Step 4/5: Deleting Elasticsearch index '{index_name}' and its database record.")
            delete_index_result = await ElasticSearchService.delete_index(index_name, vdb_core, user_id)

            # Construct final result
            result = {
                "status": "success",
                "message": (
                    f"Index {index_name} deleted successfully. "
                    f"MinIO: {minio_deletion_success_count} files deleted, {minio_deletion_failure_count} failed. "
                    f"Redis: Cleaned up {redis_cleanup_result.get('total_deleted', 0)} records."
                ),
                "es_delete_result": delete_index_result,
                "minio_cleanup": {
                    "total_files_found": len(files_to_delete),
                    "deleted_count": minio_deletion_success_count,
                    "failed_count": minio_deletion_failure_count
                },
                "redis_cleanup": redis_cleanup_result
            }

            if "errors" in redis_cleanup_result:
                result["redis_warnings"] = redis_cleanup_result["errors"]

            logger.info(
                f"Successfully completed full deletion process for knowledge base '{index_name}'.")
            return result

        except Exception as e:
            logger.error(
                f"Error during full deletion of index '{index_name}': {str(e)}", exc_info=True)
            raise e

    @staticmethod
    def create_index(
            index_name: str = Path(...,
                                   description="Name of the index to create"),
            embedding_dim: Optional[int] = Query(
                None, description="Dimension of the embedding vectors"),
            vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
            user_id: Optional[str] = Body(
                None, description="ID of the user creating the knowledge base"),
            tenant_id: Optional[str] = Body(
                None, description="ID of the tenant creating the knowledge base"),
    ):
        try:
            if vdb_core.check_index_exists(index_name):
                raise Exception(f"Index {index_name} already exists")
            embedding_model = get_embedding_model(tenant_id)
            success = vdb_core.create_index(index_name, embedding_dim=embedding_dim or (
                embedding_model.embedding_dim if embedding_model else 1024))
            if not success:
                raise Exception(f"Failed to create index {index_name}")
            knowledge_data = {"index_name": index_name,
                              "created_by": user_id,
                              "tenant_id": tenant_id,
                              "embedding_model_name": embedding_model.model}
            create_knowledge_record(knowledge_data)
            return {"status": "success", "message": f"Index {index_name} created successfully"}
        except Exception as e:
            raise Exception(f"Error creating index: {str(e)}")

    @staticmethod
    def create_knowledge_base(
            knowledge_name: str,
            embedding_dim: Optional[int],
            vdb_core: VectorDatabaseCore,
            user_id: Optional[str],
            tenant_id: Optional[str],
            ingroup_permission: Optional[str] = None,
            group_ids: Optional[List[int]] = None,
    ):
        """
        Create a new knowledge base with a user-facing name and an internal Elasticsearch index name.

        For new data:
        - Store the user-facing name in knowledge_name column.
        - Generate index_name as ``knowledge_id + '-' + uuid`` (digits and lowercase letters only).
        - Use generated index_name as the Elasticsearch index name.

        For backward compatibility, legacy callers can still use create_index() directly
        with an explicit index_name.
        """
        try:
            embedding_model = get_embedding_model(tenant_id)

            # Create knowledge record first to obtain knowledge_id and generated index_name
            knowledge_data = {
                "knowledge_name": knowledge_name,
                "knowledge_describe": "",
                "user_id": user_id,
                "tenant_id": tenant_id,
                "embedding_model_name": embedding_model.model if embedding_model else None,
            }

            # Add group permission and group IDs if provided
            if ingroup_permission is not None:
                knowledge_data["ingroup_permission"] = ingroup_permission
            if group_ids is not None:
                knowledge_data["group_ids"] = group_ids

            record_info = create_knowledge_record(knowledge_data)
            index_name = record_info["index_name"]

            # Create Elasticsearch index with generated internal index_name
            success = vdb_core.create_index(
                index_name,
                embedding_dim=embedding_dim
                or (embedding_model.embedding_dim if embedding_model else 1024),
            )
            if not success:
                raise Exception(f"Failed to create index {index_name}")

            return {
                "status": "success",
                "message": f"Index {index_name} created successfully",
                "id": index_name,
                "knowledge_id": record_info["knowledge_id"],
                "name": record_info.get("knowledge_name", knowledge_name),
            }
        except Exception as e:
            raise Exception(f"Error creating knowledge base: {str(e)}")

    @staticmethod
    def update_knowledge_base(
            index_name: str,
            knowledge_name: Optional[str] = None,
            ingroup_permission: Optional[str] = None,
            group_ids: Optional[List[int]] = None,
            tenant_id: Optional[str] = None,
            user_id: Optional[str] = None,
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

        Returns:
            bool: Whether the update was successful

        Raises:
            ValueError: If ingroup_permission is invalid
        """
        valid_permissions = ["EDIT", "READ_ONLY", "PRIVATE"]
        if ingroup_permission is not None and ingroup_permission not in valid_permissions:
            raise ValueError(
                f"Invalid ingroup_permission. Must be one of: {valid_permissions}"
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

        # Call database update function
        result = update_knowledge_record(update_data)

        if result:
            logger.info(
                f"Knowledge base '{index_name}' updated successfully by user '{user_id}'")

        return result

    @staticmethod
    async def delete_index(
            index_name: str = Path(...,
                                   description="Name of the index to delete"),
            vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
            user_id: Optional[str] = Body(
                None, description="ID of the user delete the knowledge base"),
    ):
        try:
            # 1. Get list of files from the index
            try:
                files_to_delete = await ElasticSearchService.list_files(index_name, vdb_core=vdb_core)
                if files_to_delete and files_to_delete.get("files"):
                    # 2. Delete files from MinIO storage
                    for file_info in files_to_delete["files"]:
                        object_name = file_info.get("path_or_url")
                        source_type = file_info.get("source_type")
                        if object_name and source_type == "minio":
                            logger.info(
                                f"Deleting file {object_name} from MinIO for index {index_name}")
                            delete_file(object_name)
            except Exception as e:
                # Log the error but don't block the index deletion
                logger.error(
                    f"Error deleting associated files from MinIO for index {index_name}: {str(e)}")

            # 3. Delete the index in Elasticsearch
            success = vdb_core.delete_index(index_name)
            if not success:
                # Even if deletion fails, we proceed to database record cleanup
                logger.warning(
                    f"Index {index_name} not found in Elasticsearch or could not be deleted, but proceeding with DB cleanup.")

            # 4. Delete the knowledge base record from the database
            update_data = {
                "updated_by": user_id,
                "index_name": index_name
            }
            success = delete_knowledge_record(update_data)
            if not success:
                raise Exception(
                    f"Error deleting knowledge record for index {index_name}")

            return {"status": "success", "message": f"Index {index_name} and associated files deleted successfully"}
        except Exception as e:
            raise Exception(f"Error deleting index: {str(e)}")

    @staticmethod
    def list_indices(
            pattern: str = "*",
            include_stats: bool = False,
            target_tenant_id: str = "",
            user_id: str = "",
            vdb_core: VectorDatabaseCore | None = None
    ):
        """
        List all indices that the current user has permissions to access based on role and group permissions.

        Permission logic:
        - SU: All knowledgebases visible, all editable
        - ADMIN: Knowledgebases from same tenant visible, all editable
        - USER/DEV: Knowledgebases where user belongs to intersecting groups, permission determined by:
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

        user_role = user_tenant.get("user_role")
        user_tenant_id = user_tenant.get("tenant_id")
        # Get user group IDs from tenant_group_user_t table
        user_group_ids = query_group_ids_by_user(user_id)

        # Get all indices from Elasticsearch
        es_indices_list = vdb_core.get_user_indices(pattern)

        # Get all knowledgebase records from database (for cleanup and permission checking)
        all_db_records = get_knowledge_info_by_tenant_id(target_tenant_id)

        # Filter visible knowledgebases based on user role and permissions
        visible_knowledgebases = []
        model_name_is_none_list = []

        for record in all_db_records:
            index_name = record["index_name"]
            if record['knowledge_sources'] == 'datamate':
                continue
            # Check if index exists in Elasticsearch (skip if not found)
            if index_name not in es_indices_list:
                continue

            # Check permission based on user role
            permission = None

            # Fallback logic: if user_id equals user_tenant_id, treat as legacy admin user
            # even if user_role is None or empty
            effective_user_role = user_role
            if user_id == user_tenant_id:
                effective_user_role = "ADMIN"
                logger.info(f"User {user_id} identified as legacy admin")
            elif IS_SPEED_MODE:
                effective_user_role = "SPEED"
                logger.info("User under SPEED version is treated as admin")

            if effective_user_role in ["SU", "ADMIN", "SPEED"]:
                # SU, ADMIN and SPEED roles can see all knowledgebases
                permission = PERMISSION_EDIT
            elif effective_user_role in ["USER", "DEV"]:
                # USER/DEV need group-based permission checking
                kb_group_ids_str = record.get("group_ids")
                kb_group_ids = convert_string_to_list(kb_group_ids_str or "")
                kb_created_by = record.get("created_by")
                kb_ingroup_permission = record.get(
                    "ingroup_permission") or PERMISSION_READ

                # Check if user belongs to any of the knowledgebase groups
                # Compatibility logic for legacy data:
                # - If both kb_group_ids and user_group_ids are effectively empty (None or empty lists),
                #   consider them intersecting (backward compatibility)
                # - If either side has groups but they don't intersect, no intersection
                kb_groups_empty = kb_group_ids_str is None or (isinstance(
                    kb_group_ids_str, str) and kb_group_ids_str.strip() == "") or len(kb_group_ids) == 0
                user_groups_empty = len(user_group_ids) == 0

                if kb_groups_empty and user_groups_empty:
                    # Both are empty/None - consider intersecting for backward compatibility
                    has_group_intersection = True
                else:
                    # Normal intersection check
                    has_group_intersection = bool(
                        set(user_group_ids) & set(kb_group_ids))

                if has_group_intersection:
                    # Determine permission level
                    permission = PERMISSION_READ  # Default

                    # User is creator: creator permission
                    if kb_created_by == user_id:
                        permission = "CREATOR"
                    # Group permission allows editing
                    elif kb_ingroup_permission == PERMISSION_EDIT:
                        permission = PERMISSION_EDIT
                    # Group permission is read-only: already set
                    elif kb_ingroup_permission == PERMISSION_READ:
                        permission = PERMISSION_READ
                    # Group permission is private: not visible
                    elif kb_ingroup_permission == "PRIVATE":
                        permission = None

            # Add to visible list if permission is granted
            if permission:
                record_with_permission = dict(record)
                record_with_permission["permission"] = permission
                # Convert group_ids string to list for easier client consumption
                if record.get("group_ids"):
                    record_with_permission["group_ids"] = convert_string_to_list(
                        record["group_ids"])
                else:
                    # If no group_ids specified, use tenant default group
                    default_group_id = get_tenant_default_group_id(
                        record.get("tenant_id"))
                    record_with_permission["group_ids"] = [
                        default_group_id] if default_group_id else []
                visible_knowledgebases.append(record_with_permission)

                # Track records with missing embedding model for stats update
                if record.get("embedding_model_name") is None:
                    model_name_is_none_list.append(index_name)

        # Build response
        indices = [record["index_name"] for record in visible_knowledgebases]

        response = {
            "indices": indices,
            "count": len(indices),
        }

        if include_stats:
            stats_info = []
            if visible_knowledgebases:
                index_names = [record["index_name"]
                               for record in visible_knowledgebases]
                indice_stats = vdb_core.get_indices_detail(index_names)

                for record in visible_knowledgebases:
                    index_name = record["index_name"]
                    index_stats = indice_stats.get(index_name, {})

                    stats_info.append({
                        # Internal index name (used as ID)
                        "name": index_name,
                        # User-facing knowledge base name from PostgreSQL (fallback to index_name)
                        "display_name": record.get("knowledge_name", index_name),
                        "permission": record["permission"],
                        "group_ids": record["group_ids"],
                        # knowledge source and ingroup permission from DB record
                        "knowledge_sources": record["knowledge_sources"],
                        "ingroup_permission": record["ingroup_permission"],
                        "tenant_id": record.get("tenant_id"),
                        # Update time for sorting and display
                        "update_time": record.get("update_time"),
                        "stats": index_stats,
                    })

                    # Update model name if missing
                    if index_name in model_name_is_none_list:
                        update_model_name_by_index_name(
                            index_name,
                            index_stats.get("base_info", {}).get(
                                "embedding_model", ""),
                            record.get("tenant_id", target_tenant_id),
                            user_id
                        )

            response["indices_info"] = stats_info

        return response

    @staticmethod
    def index_documents(
            embedding_model: BaseEmbedding,
            index_name: str = Path(..., description="Name of the index"),
            data: List[Dict[str, Any]
                       ] = Body(..., description="Document List to process"),
            vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
            task_id: Optional[str] = None,
    ):
        """
        Index documents and create vector embeddings, create index if it doesn't exist

        Args:
            embedding_model: Optional embedding model to use for generating document vectors
            index_name: Index name
            data: List containing document data to be indexed
            vdb_core: VectorDatabaseCore instance

        Returns:
            IndexingResponse object containing indexing result information
        """
        try:
            if not index_name:
                raise Exception("Index name is required")

            # Create index if needed (ElasticSearchCore will handle embedding_dim automatically)
            if not vdb_core.check_index_exists(index_name):
                try:
                    ElasticSearchService.create_index(
                        index_name, vdb_core=vdb_core)
                    logger.info(f"Created new index {index_name}")
                except Exception as create_error:
                    raise Exception(
                        f"Failed to create index {index_name}: {str(create_error)}")

            # Transform indexing request results to documents
            documents = []

            for idx, item in enumerate(data):
                # All items should be dictionaries
                if not isinstance(item, dict):
                    logger.warning(f"Skipping item {idx} - not a dictionary")
                    continue

                # Extract metadata
                metadata = item.get("metadata", {})
                source = item.get("path_or_url")
                text = item.get("content", "")
                source_type = item.get("source_type")
                file_size = item.get("file_size")
                file_name = item.get("filename", os.path.basename(
                    source) if source and source_type == "local" else "")

                # Get from metadata
                title = metadata.get("title", "")
                language = metadata.get("languages", ["null"])[
                    0] if metadata.get("languages") else "null"
                author = metadata.get("author", "null")
                date = metadata.get("date", time.strftime(
                    "%Y-%m-%d", time.gmtime()))
                create_time = metadata.get("creation_date", time.strftime(
                    "%Y-%m-%dT%H:%M:%S", time.gmtime()))

                # Set embedding model name from the embedding model
                embedding_model_name = ""
                if embedding_model:
                    embedding_model_name = embedding_model.model

                # Create document
                document = {
                    "title": title,
                    "filename": file_name,
                    "path_or_url": source,
                    "source_type": source_type,
                    "language": language,
                    "author": author,
                    "date": date,
                    "content": text,
                    "process_source": "Unstructured",
                    "file_size": file_size,
                    "create_time": create_time,
                    "languages": metadata.get("languages", []),
                    "embedding_model_name": embedding_model_name
                }

                documents.append(document)

            total_submitted = len(documents)
            if total_submitted == 0:
                return {
                    "success": True,
                    "message": "No documents to index",
                    "total_indexed": 0,
                    "total_submitted": 0
                }

            # Index documents (use default batch_size and content_field)
            # Get chunk_batch from model config
            # First, get tenant_id from knowledge record
            knowledge_record = get_knowledge_record({'index_name': index_name})
            tenant_id = knowledge_record.get(
                'tenant_id') if knowledge_record else None

            if tenant_id:
                model_config = tenant_config_manager.get_model_config(
                    key="EMBEDDING_ID", tenant_id=tenant_id)
                embedding_batch_size = model_config.get("chunk_batch", 10)
                if embedding_batch_size is None:
                    embedding_batch_size = 10
            else:
                # Fallback to default if tenant_id not found
                embedding_batch_size = 10

            # Initialize progress tracking if task_id is provided
            if task_id:
                try:
                    redis_service = get_redis_service()
                    success = redis_service.save_progress_info(
                        task_id, 0, total_submitted)
                    if success:
                        logger.info(
                            f"[REDIS PROGRESS] Initialized progress tracking for task {task_id}: 0/{total_submitted}")
                    else:
                        logger.warning(
                            f"Failed to initialize progress tracking for task {task_id}")
                except Exception as e:
                    logger.warning(
                        f"Failed to initialize progress tracking for task {task_id}: {str(e)}")

            try:
                total_indexed = vdb_core.vectorize_documents(
                    index_name=index_name,
                    embedding_model=embedding_model,
                    documents=documents,
                    embedding_batch_size=embedding_batch_size,
                    progress_callback=lambda processed, total: _update_progress(
                        task_id, processed, total) if task_id else None
                )

                # Update final progress
                if task_id:
                    try:
                        redis_service = get_redis_service()
                        success = redis_service.save_progress_info(
                            task_id, total_indexed, total_submitted)
                        if success:
                            logger.info(
                                f"[REDIS PROGRESS] Updated final progress for task {task_id}: {total_indexed}/{total_submitted}")
                        else:
                            logger.warning(
                                f"[REDIS PROGRESS] Failed to update final progress for task {task_id}")
                    except Exception as e:
                        logger.warning(
                            f"[REDIS PROGRESS] Exception updating final progress for task {task_id}: {str(e)}")

                return {
                    "success": True,
                    "message": f"Successfully indexed {total_indexed} documents",
                    "total_indexed": total_indexed,
                    "total_submitted": total_submitted
                }
            except Exception as e:
                logger.error(f"Error during indexing: {str(e)}")
                _rethrow_or_plain(e)

        except Exception as e:
            logger.error(f"Error indexing documents: {str(e)}")
            _rethrow_or_plain(e)

    @staticmethod
    async def list_files(
            index_name: str = Path(..., description="Name of the index"),
            include_chunks: bool = Query(
                False, description="Whether to include text chunks for each file"),
            vdb_core: VectorDatabaseCore = Depends(get_vector_db_core)
    ):
        """
        Get file list for the specified index, including files that are not yet stored in ES

        Args:
            index_name: Name of the index
            include_chunks: Whether to include text chunks for each file
            vdb_core: VectorDatabaseCore instance

        Returns:
            Dictionary containing file list
        """
        try:
            files_map: Dict[str, Dict[str, Any]] = {}
            # Get existing files from ES
            existing_files = vdb_core.get_documents_detail(index_name)

            # Get unique celery files list and the status of each file
            celery_task_files = await get_all_files_status(index_name)

            # For files already stored in ES, add to files list
            for file_info in existing_files:
                utc_create_time_str = file_info.get('create_time', '')
                # Try to parse the create_time string, fallback to current timestamp if format is invalid
                try:
                    utc_create_timestamp = datetime.strptime(utc_create_time_str, '%Y-%m-%dT%H:%M:%S').replace(
                        tzinfo=timezone.utc).timestamp()
                except (ValueError, TypeError):
                    utc_create_timestamp = time.time()

                # Always re-query chunk count to ensure accuracy (aggregation may be stale)
                path_or_url = file_info.get('path_or_url')
                chunk_count = file_info.get('chunk_count', 0)
                try:
                    count_result = vdb_core.client.count(
                        index=index_name,
                        body={"query": {"term": {"path_or_url": path_or_url}}}
                    )
                    chunk_count = count_result.get("count", chunk_count)
                except Exception as count_err:
                    logger.warning(
                        f"Failed to get chunk count for {path_or_url}: {count_err}, using aggregation value {chunk_count}")

                file_data = {
                    'path_or_url': path_or_url,
                    'file': file_info.get('filename', ''),
                    'file_size': file_info.get('file_size', 0),
                    'create_time': int(utc_create_timestamp * 1000),
                    'status': "COMPLETED",
                    'latest_task_id': '',
                    'chunk_count': chunk_count,
                    'error_reason': None,
                    'has_error_info': False
                }
                files_map[path_or_url] = file_data

            # For files not yet stored in ES (files currently being processed)
            for path_or_url, status_info in celery_task_files.items():
                status_dict = status_info if isinstance(
                    status_info, dict) else {}

                # Get source_type and original_filename, with defaults
                source_type = status_dict.get('source_type') if status_dict.get(
                    'source_type') else 'minio'
                original_filename = status_dict.get('original_filename')

                # Determine the filename
                filename = original_filename or (
                    os.path.basename(path_or_url) if path_or_url else '')

                # Safely get file size; default to 0 on any error
                file_size = 0
                if path_or_url in files_map:
                    file_size = files_map[path_or_url].get('file_size', 0)
                else:
                    try:
                        file_size = get_file_size(
                            source_type or 'minio', path_or_url)
                    except Exception as size_err:
                        logger.error(
                            f"Failed to get file size for '{path_or_url}': {size_err}")
                        file_size = 0

                # Get progress from status_dict first, then try Redis for real-time updates
                processed_chunks = status_dict.get('processed_chunks')
                total_chunks = status_dict.get('total_chunks')
                task_id = status_dict.get('latest_task_id', '')

                # Always try to get latest progress from Redis if task_id exists
                # Redis has the most up-to-date progress during vectorization
                if task_id:
                    try:
                        redis_service = get_redis_service()
                        progress_info = redis_service.get_progress_info(
                            task_id)
                        if progress_info:
                            redis_processed = progress_info.get(
                                'processed_chunks')
                            redis_total = progress_info.get('total_chunks')
                            if redis_processed is not None:
                                processed_chunks = redis_processed
                            if redis_total is not None:
                                total_chunks = redis_total
                            logger.debug(
                                f"Retrieved progress from Redis for task {task_id}: {processed_chunks}/{total_chunks}")
                    except Exception as e:
                        logger.debug(
                            f"Failed to get progress from Redis for task {task_id}: {str(e)}")

                if path_or_url in files_map:
                    file_data = files_map[path_or_url]
                else:
                    file_data = {
                        'path_or_url': path_or_url,
                        'file': filename,
                        'file_size': file_size,
                        'create_time': int(time.time() * 1000),
                        'chunk_count': 0,
                        'error_reason': None,
                        'has_error_info': False
                    }
                    files_map[path_or_url] = file_data

                file_data['status'] = status_dict.get('state', file_data.get(
                    'status', 'UNKNOWN'))
                file_data['latest_task_id'] = task_id
                file_data['processed_chunk_num'] = processed_chunks
                file_data['total_chunk_num'] = total_chunks

                # Get error reason for failed documents
                if task_id and status_dict.get('state') in ['PROCESS_FAILED', 'FORWARD_FAILED']:
                    try:
                        redis_service = get_redis_service()
                        error_reason = redis_service.get_error_info(task_id)
                        if error_reason:
                            file_data['error_reason'] = error_reason
                            file_data['has_error_info'] = True
                    except Exception as e:
                        logger.debug(
                            f"Failed to get error info for task {task_id}: {str(e)}")

            files = list(files_map.values())

            # Unified chunks processing for all files
            if include_chunks:
                # Prepare msearch body for all completed files
                completed_files_map = {
                    f['path_or_url']: f for f in files if f['status'] == "COMPLETED"}
                msearch_body = []

                for path_or_url in completed_files_map.keys():
                    msearch_body.append({'index': index_name})
                    msearch_body.append({
                        "query": {"term": {"path_or_url": path_or_url}},
                        "size": 100,
                        "_source": ["id", "title", "content", "create_time"]
                    })

                # Initialize chunks for all files
                for file_data in files:
                    file_data['chunks'] = []
                    file_data['chunk_count'] = file_data.get('chunk_count', 0)

                if msearch_body:
                    try:
                        msearch_responses = vdb_core.multi_search(
                            body=msearch_body,
                            index_name=index_name
                        )

                        for i, file_path in enumerate(completed_files_map.keys()):
                            response = msearch_responses['responses'][i]
                            file_data = completed_files_map[file_path]

                            if 'error' in response:
                                logger.error(
                                    f"Error getting chunks for {file_data.get('path_or_url')}: {response['error']}")
                                continue

                            chunks = []
                            for hit in response["hits"]["hits"]:
                                source = hit["_source"]
                                chunks.append({
                                    "id": source.get("id"),
                                    "title": source.get("title"),
                                    "content": source.get("content"),
                                    "create_time": source.get("create_time")
                                })

                            file_data['chunks'] = chunks
                            # Get accurate chunk count using count query instead of len(chunks)
                            # because msearch may have size limits
                            try:
                                count_result = vdb_core.client.count(
                                    index=index_name,
                                    body={
                                        "query": {"term": {"path_or_url": file_path}}}
                                )
                                file_data['chunk_count'] = count_result.get(
                                    "count", len(chunks))
                            except Exception as count_err:
                                logger.warning(
                                    f"Failed to get chunk count for {file_path}: {count_err}, using len(chunks)")
                                file_data['chunk_count'] = len(chunks)

                    except Exception as e:
                        logger.error(
                            f"Error during msearch for chunks: {str(e)}")
            else:
                # When include_chunks=False, ensure chunk_count is accurate for completed files
                for file_data in files:
                    file_data['chunks'] = []
                    if file_data.get('status') == "COMPLETED":
                        # Always re-query chunk count for completed files to ensure accuracy
                        try:
                            count_result = vdb_core.client.count(
                                index=index_name,
                                body={
                                    "query": {"term": {"path_or_url": file_data.get('path_or_url')}}}
                            )
                            file_data['chunk_count'] = count_result.get(
                                "count", 0)
                        except Exception as count_err:
                            logger.warning(
                                f"Failed to get chunk count for {file_data.get('path_or_url')}: {count_err}")
                            file_data['chunk_count'] = file_data.get(
                                'chunk_count', 0)
                    else:
                        file_data['chunk_count'] = file_data.get(
                            'chunk_count', 0)

            return {"files": files}

        except Exception as e:
            raise Exception(
                f"Error getting file list for index {index_name}: {str(e)}")

    @staticmethod
    def delete_documents(
            index_name: str = Path(..., description="Name of the index"),
            path_or_url: str = Query(...,
                                     description="Path or URL of documents to delete"),
            vdb_core: VectorDatabaseCore = Depends(get_vector_db_core)
    ):
        # 1. Delete ES documents
        deleted_count = vdb_core.delete_documents(
            index_name, path_or_url)
        # 2. Delete MinIO file
        minio_result = delete_file(path_or_url)
        return {"status": "success", "deleted_es_count": deleted_count, "deleted_minio": minio_result.get("success")}

    @staticmethod
    def health_check(vdb_core: VectorDatabaseCore = Depends(get_vector_db_core)):
        """
        Check the health status of the API and Elasticsearch

        Args:
            vdb_core: VectorDatabaseCore instance

        Returns:
            Response containing health status information
        """
        try:
            # Try to list indices as a health check
            indices = vdb_core.get_user_indices()
            return {
                "status": "healthy",
                "elasticsearch": "connected",
                "indices_count": len(indices)
            }
        except Exception as e:
            raise Exception(f"Health check failed: {str(e)}")

    async def summary_index_name(self,
                                 index_name: str = Path(
                                     ..., description="Name of the index to get documents from"),
                                 batch_size: int = Query(
                                     1000, description="Number of documents to retrieve per batch"),
                                 vdb_core: VectorDatabaseCore = Depends(
                                     get_vector_db_core),
                                 user_id: Optional[str] = Body(
                                     None, description="ID of the user delete the knowledge base"),
                                 tenant_id: Optional[str] = Body(
                                     None, description="ID of the tenant"),
                                 language: str = LANGUAGE["ZH"],
                                 model_id: Optional[int] = None
                                 ):
        """
        Generate a summary for the specified index using advanced Map-Reduce approach

        New implementation:
        1. Get documents and cluster them by semantic similarity
        2. Map: Summarize each document individually
        3. Reduce: Merge document summaries into cluster summaries
        4. Return: Combined knowledge base summary

        Args:
            index_name: Name of the index to summarize
            batch_size: Number of documents to sample (default: 1000)
            vdb_core: VectorDatabaseCore instance
            user_id: ID of the user delete the knowledge base
            tenant_id: ID of the tenant
            language: Language of the summary (default: 'zh')
            model_id: Model ID for LLM summarization

        Returns:
            StreamingResponse containing the generated summary
        """
        try:
            if not tenant_id:
                raise Exception(
                    "Tenant ID is required for summary generation.")

            from utils.document_vector_utils import (
                process_documents_for_clustering,
                kmeans_cluster_documents,
                summarize_clusters_map_reduce,
                merge_cluster_summaries
            )

            # Use new Map-Reduce approach
            # Sample reasonable number of documents
            sample_count = min(batch_size // 5, 200)

            # Define a helper function to run all blocking operations in a thread pool
            def _generate_summary_sync():
                """Synchronous function that performs all blocking operations"""
                # Step 1: Get documents and calculate embeddings
                document_samples, doc_embeddings = process_documents_for_clustering(
                    index_name=index_name,
                    vdb_core=vdb_core,
                    sample_doc_count=sample_count
                )

                if not document_samples:
                    raise Exception("No documents found in index.")

                # Step 2: Cluster documents (CPU-intensive operation)
                clusters = kmeans_cluster_documents(doc_embeddings, k=None)

                # Step 3: Map-Reduce summarization (contains blocking LLM calls)
                cluster_summaries = summarize_clusters_map_reduce(
                    document_samples=document_samples,
                    clusters=clusters,
                    language=language,
                    doc_max_words=100,
                    cluster_max_words=150,
                    model_id=model_id,
                    tenant_id=tenant_id
                )

                # Step 4: Merge into final summary
                final_summary = merge_cluster_summaries(cluster_summaries)
                return final_summary

            # Run blocking operations in a thread pool to avoid blocking the event loop
            # Use get_running_loop() for better compatibility with modern asyncio
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # Fallback for edge cases
                loop = asyncio.get_event_loop()
            final_summary = await loop.run_in_executor(None, _generate_summary_sync)

            # Stream the result
            async def generate_summary():
                try:
                    # Stream the summary character by character
                    for char in final_summary:
                        yield f"data: {{\"status\": \"success\", \"message\": \"{char}\"}}\n\n"
                        await asyncio.sleep(0.01)
                    yield "data: {\"status\": \"completed\"}\n\n"
                except Exception as e:
                    yield f"data: {{\"status\": \"error\", \"message\": \"{e}\"}}\n\n"

            return StreamingResponse(
                generate_summary(),
                media_type="text/event-stream"
            )

        except Exception as e:
            logger.error(
                f"Knowledge base summary generation failed: {str(e)}", exc_info=True)
            raise Exception(f"Failed to generate summary: {str(e)}")

    @staticmethod
    def get_random_documents(
            index_name: str = Path(...,
                                   description="Name of the index to get documents from"),
            batch_size: int = Query(
                1000, description="Maximum number of documents to retrieve"),
            vdb_core: VectorDatabaseCore = Depends(get_vector_db_core)
    ):
        """
        Get random sample of documents from the specified index

        Args:
            index_name: Name of the index to get documents from
            batch_size: Maximum number of documents to retrieve, default 1000
            vdb_core: VectorDatabaseCore instance

        Returns:
            Dictionary containing total count and sampled documents
        """
        try:
            # Get total document count
            total_docs = vdb_core.count_documents(index_name)

            # Construct the random sampling query using random_score
            query = {
                "size": batch_size,  # Limit return size
                "query": {
                    "function_score": {
                        "query": {"match_all": {}},
                        "random_score": {
                            # Use current time as random seed
                            "seed": int(time.time()),
                            "field": "_seq_no"
                        }
                    }
                }
            }

            # Execute the query
            response = vdb_core.search(
                index_name=index_name,
                query=query
            )

            # Extract and process the sampled documents
            sampled_docs = []
            for hit in response['hits']['hits']:
                doc = hit['_source']
                doc['_id'] = hit['_id']  # Add document ID
                sampled_docs.append(doc)

            return {
                "total": total_docs,
                "documents": sampled_docs
            }

        except Exception as e:
            raise Exception(
                f"Error retrieving random documents from index {index_name}: {str(e)}")

    @staticmethod
    def change_summary(
            index_name: str = Path(...,
                                   description="Name of the index to get documents from"),
            summary_result: Optional[str] = Body(
                description="knowledge base summary"),
            user_id: Optional[str] = Body(
                None, description="ID of the user delete the knowledge base")
    ):
        """
        Update the summary for the specified Elasticsearch index

        Args:
            index_name: Name of the index to update
            summary_result: New summary content
            user_id: ID of the user making the update

        Returns:
            Dictionary containing status and updated summary information
        """
        try:
            update_data = {
                "knowledge_describe": summary_result,  # Set the new summary
                "updated_by": user_id,
                "index_name": index_name
            }
            update_knowledge_record(update_data)
            return {"status": "success", "message": f"Index {index_name} summary updated successfully",
                    "summary": summary_result}
        except Exception as e:
            raise Exception(f"{str(e)}")

    @staticmethod
    def get_summary(index_name: str = Path(..., description="Name of the index to get documents from")):
        """
        Get the summary for the specified Elasticsearch index

        Args:
            index_name: Name of the index to get summary from

        Returns:
            Dictionary containing status and summary information
        """
        try:
            knowledge_record = get_knowledge_record({'index_name': index_name})
            if knowledge_record:
                summary_result = knowledge_record["knowledge_describe"]
                success_msg = f"Index {index_name} summary retrieved successfully"
                return {"status": "success", "message": success_msg, "summary": summary_result}
            error_detail = f"Unable to get summary for index {index_name}"
            raise Exception(error_detail)
        except Exception as e:
            error_msg = f"Failed to get summary: {str(e)}"
            raise Exception(error_msg)

    @staticmethod
    def get_index_chunks(
        index_name: str,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
        path_or_url: Optional[str] = None,
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
    ):
        """
        Retrieve chunk records for the specified index with optional pagination.

        Args:
            index_name: Name of the index to query
            page: Page number (1-based) when paginating
            page_size: Page size when paginating
            path_or_url: Optional document filter
            vdb_core: VectorDatabaseCore instance

        Returns:
            Dictionary containing status, chunk list, total, and pagination metadata
        """
        try:
            result = vdb_core.get_index_chunks(
                index_name,
                page=page,
                page_size=page_size,
                path_or_url=path_or_url,
            )
            raw_chunks = result.get("chunks", [])
            total = result.get("total", len(raw_chunks))
            result_page = result.get("page", page)
            result_page_size = result.get("page_size", page_size)

            filtered_chunks: List[Any] = []
            for chunk in raw_chunks:
                if isinstance(chunk, dict):
                    filtered_chunks.append(
                        {
                            field: chunk.get(field)
                            for field in ALLOWED_CHUNK_FIELDS
                            if field in chunk
                        }
                    )
                else:
                    filtered_chunks.append(chunk)

            return {
                "status": "success",
                "message": f"Successfully retrieved {len(filtered_chunks)} chunks from index {index_name}",
                "chunks": filtered_chunks,
                "total": total,
                "page": result_page,
                "page_size": result_page_size
            }
        except Exception as e:
            error_msg = f"Error retrieving chunks from index {index_name}: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)

    @staticmethod
    def create_chunk(
        index_name: str,
        chunk_request: ChunkCreateRequest,
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ):
        """
        Create a manual chunk entry in the specified index.
        Automatically generates and stores embedding for semantic search.
        """
        try:
            # Get knowledge base's embedding model name
            embedding_model_name = None
            if tenant_id:
                try:
                    knowledge_record = get_knowledge_record({
                        "index_name": index_name,
                        "tenant_id": tenant_id
                    })
                    embedding_model_name = knowledge_record.get("embedding_model_name") if knowledge_record else None
                except Exception as e:
                    logger.warning(f"Failed to get embedding model name for index {index_name}: {e}")

            # Generate embedding if we have content and can get embedding model
            embedding_vector = None
            if chunk_request.content:
                try:
                    embedding_model = get_embedding_model(tenant_id, embedding_model_name) if tenant_id else None
                    if embedding_model:
                        embeddings = embedding_model.get_embeddings(chunk_request.content)
                        if embeddings and len(embeddings) > 0:
                            embedding_vector = embeddings[0]
                            logger.debug(f"Generated embedding for chunk in index {index_name}")
                        else:
                            logger.warning(f"Failed to generate embedding for chunk in index {index_name}")
                    else:
                        logger.warning(f"No embedding model available for index {index_name}")
                except Exception as e:
                    logger.warning(f"Failed to generate embedding for chunk: {e}")

            # Build chunk payload
            chunk_payload = ElasticSearchService._build_chunk_payload(
                base_fields={
                    "id": chunk_request.chunk_id or ElasticSearchService._generate_chunk_id(),
                    "title": chunk_request.title,
                    "filename": chunk_request.filename,
                    "path_or_url": chunk_request.path_or_url,
                    "content": chunk_request.content,
                    "created_by": user_id,
                },
                metadata=chunk_request.metadata,
                ensure_create_time=True,
            )

            # Add embedding if generated
            if embedding_vector:
                chunk_payload["embedding"] = embedding_vector
                if embedding_model_name:
                    chunk_payload["embedding_model_name"] = embedding_model_name

            result = vdb_core.create_chunk(index_name, chunk_payload)
            return {
                "status": "success",
                "message": f"Chunk {result.get('id')} created successfully",
                "chunk_id": result.get("id"),
            }
        except Exception as exc:
            logger.error("Error creating chunk in index %s: %s",
                         index_name, exc, exc_info=True)
            raise Exception(f"Error creating chunk: {exc}")

    @staticmethod
    def update_chunk(
        index_name: str,
        chunk_id: str,
        chunk_request: ChunkUpdateRequest,
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
        user_id: Optional[str] = None,
    ):
        """
        Update a chunk document.
        """
        try:
            update_fields = chunk_request.dict(
                exclude_unset=True, exclude={"metadata"})
            metadata = chunk_request.metadata or {}
            update_payload = ElasticSearchService._build_chunk_payload(
                base_fields={
                    **update_fields,
                    "updated_by": user_id,
                    "update_time": datetime.utcnow().strftime(
                        "%Y-%m-%dT%H:%M:%S"),
                },
                metadata=metadata,
                ensure_create_time=False,
            )

            if not update_payload:
                raise ValueError("No update fields supplied.")

            result = vdb_core.update_chunk(
                index_name, chunk_id, update_payload)
            return {
                "status": "success",
                "message": f"Chunk {result.get('id')} updated successfully",
                "chunk_id": result.get("id"),
            }
        except Exception as exc:
            logger.error("Error updating chunk %s in index %s: %s",
                         chunk_id, index_name, exc, exc_info=True)
            raise Exception(f"Error updating chunk: {exc}")

    @staticmethod
    def delete_chunk(
        index_name: str,
        chunk_id: str,
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
    ):
        """
        Delete a chunk document by id.
        """
        try:
            deleted = vdb_core.delete_chunk(index_name, chunk_id)
            if not deleted:
                raise ValueError(
                    f"Chunk {chunk_id} not found in index {index_name}")
            return {
                "status": "success",
                "message": f"Chunk {chunk_id} deleted successfully",
                "chunk_id": chunk_id,
            }
        except Exception as exc:
            logger.error("Error deleting chunk %s in index %s: %s",
                         chunk_id, index_name, exc, exc_info=True)
            raise Exception(f"Error deleting chunk: {exc}")

    @staticmethod
    def search_hybrid(
            *,
            index_names: List[str],
            query: str,
            tenant_id: str,
            top_k: int = 10,
            weight_accurate: float = 0.5,
            vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
    ):
        """
        Execute a hybrid search that blends accurate and semantic scoring.
        """
        try:
            if not tenant_id:
                raise ValueError("Tenant ID is required for hybrid search")
            if not query or not query.strip():
                raise ValueError("Query text is required for hybrid search")
            if not index_names:
                raise ValueError("At least one index name is required")
            if top_k <= 0:
                raise ValueError("top_k must be greater than 0")
            if weight_accurate < 0 or weight_accurate > 1:
                raise ValueError("weight_accurate must be between 0 and 1")

            embedding_model = get_embedding_model(tenant_id)
            if not embedding_model:
                raise ValueError(
                    "No embedding model configured for the current tenant")

            start_time = time.perf_counter()
            raw_results = vdb_core.hybrid_search(
                index_names=index_names,
                query_text=query,
                embedding_model=embedding_model,
                top_k=top_k,
                weight_accurate=weight_accurate,
            )
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)

            formatted_results = []
            for item in raw_results:
                document = dict(item.get("document", {}))
                document["score"] = item.get("score")
                document["index"] = item.get("index")
                if "scores" in item:
                    document["score_details"] = item["scores"]
                formatted_results.append(document)

            return {
                "results": formatted_results,
                "total": len(formatted_results),
                "query_time_ms": elapsed_ms,
            }
        except ValueError:
            raise
        except Exception as exc:
            logger.error(
                f"Hybrid search failed for indices {index_names}: {exc}",
                exc_info=True,
            )
            raise Exception(f"Error executing hybrid search: {str(exc)}")

    @staticmethod
    def _generate_chunk_id() -> str:
        """Generate a deterministic chunk id."""
        return f"chunk_{uuid.uuid4().hex}"

    @staticmethod
    def _build_chunk_payload(
        base_fields: Dict[str, Any],
        metadata: Optional[Dict[str, Any]],
        ensure_create_time: bool = True,
    ) -> Dict[str, Any]:
        """
        Merge and sanitize chunk payload fields.
        """
        payload = {
            key: value for key, value in (base_fields or {}).items() if value is not None
        }
        if metadata:
            for key, value in metadata.items():
                if value is not None:
                    payload[key] = value

        if ensure_create_time and "create_time" not in payload:
            payload["create_time"] = datetime.utcnow().strftime(
                "%Y-%m-%dT%H:%M:%S")

        return payload
