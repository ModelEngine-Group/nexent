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
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, Path, Query
from nexent.core.gateway.modality import EmbeddingAdapter
from nexent.vector_database.base import VectorDatabaseCore

from consts.const import (
    ASSET_OWNER_ATTACHMENTS_PREFIX,
    ASSET_OWNER_TENANT_ID,
    IS_SPEED_MODE,
    PERMISSION_PRIVATE,
)
from consts.error_code import ErrorCode
from consts.exceptions import AppException, DuplicateError
from database.attachment_db import delete_file, file_exists, get_file_stream
from database.knowledge_db import (
    create_knowledge_record,
    delete_knowledge_record,
    get_knowledge_record,
    update_knowledge_record,
    get_knowledge_info_by_tenant_id,
    update_model_name_by_index_name,
    update_last_doc_update_time,
    update_embedding_model_by_index_name,
)
from database.knowledge_storage_object_db import list_committed_storage_objects
from database.knowledge_file_lifecycle_db import (
    list_file_records,
)
from services.knowledge_storage_service import (
    release_storage_charge,
    resolve_storage_reference,
)
from utils.str_utils import convert_list_to_string
from database.user_tenant_db import get_user_tenant_by_user_id
from database.group_db import query_group_ids_by_user
from database.model_management_db import get_model_by_model_id
from permissions.dac import ResourceAccessControl
from permissions.models import Resource
from services.redis_service import get_redis_service
from services.group_service import get_tenant_default_group_id
from services.asset_owner_visibility import postprocess_knowledge_visibility
from utils.config_utils import tenant_config_manager
from management.services.model.resolver import (
    create_embedding_model, get_embedding_model_by_id, get_model_descriptor,
)
from utils.file_management_utils import get_all_files_status, get_file_size
from utils.str_utils import convert_string_to_list
from utils.storage_key_utils import build_preview_pdf_object_key



from management.services.knowledge_base.common import (
    _QUOTA_LIMIT_UNSET,
    _SKIP_INDEX_SOURCE_CLEANUP,
    _update_progress,
    get_vector_db_core,
    _rethrow_or_plain,
    logger,
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

class KnowledgeBaseManagementService:
    # A knowledge base cannot be removed while ingestion still owns a file.
    # DELETE_REQUESTED is intentionally excluded: that state means the
    # single-file deletion flow already owns cleanup for that file.
    KNOWLEDGE_BASE_DELETE_BLOCKING_STATUSES = frozenset({
        "UPLOADING",
        "UPLOADED",
        "PROCESSING",
        "FORWARDING",
    })

    CREATOR_PERMISSION = CREATOR_PERMISSION
    resolve_knowledge_base_permission = staticmethod(resolve_knowledge_base_permission)
    require_knowledge_base_edit_permission = staticmethod(require_knowledge_base_edit_permission)
    require_knowledge_base_read_permission = staticmethod(require_knowledge_base_read_permission)
    filter_accessible_indices = staticmethod(filter_accessible_indices)

    @staticmethod
    def _assert_knowledge_base_delete_allowed(index_name: str) -> None:
        """Reject KB deletion while a durable lifecycle row is still ingesting."""
        try:
            lifecycle_rows = list_file_records(index_name=index_name, include_hidden=True)
        except Exception as lifecycle_exc:
            raise AppException(
                ErrorCode.SYSTEM_DATABASE_ERROR,
                details={
                    "operation": "knowledge_base_delete_guard",
                    "index_name": index_name,
                },
            ) from lifecycle_exc

        blocking_files = []
        for row in lifecycle_rows or []:
            status = str(row.get("status") or "").upper()
            if status not in KnowledgeBaseManagementService.KNOWLEDGE_BASE_DELETE_BLOCKING_STATUSES:
                continue
            blocking_files.append({
                "file_id": row.get("file_id"),
                "file_name": (
                    row.get("original_filename")
                    or row.get("object_name")
                    or row.get("file_id")
                    or "unknown"
                ),
                "status": status,
            })

        if blocking_files:
            raise AppException(
                ErrorCode.KNOWLEDGE_DELETE_BLOCKED,
                details={
                    "index_name": index_name,
                    "blocking_files": blocking_files,
                },
            )

    @staticmethod
    async def full_delete_knowledge_base(index_name: str, vdb_core: VectorDatabaseCore, user_id: str):
        """
        Completely delete a knowledge base, including its index, associated files in MinIO,
        and all related records in Redis and PostgreSQL.
        """
        logger.debug(
            f"Starting full deletion process for knowledge base (index): {index_name}")
        try:
            # Check the durable lifecycle table before mutating any external
            # system.  This closes the race where an ingestion task can write
            # after knowledge-base deletion has started.
            KnowledgeBaseManagementService._assert_knowledge_base_delete_allowed(index_name)

            minio_cleanup = await KnowledgeBaseManagementService._delete_kb_source_objects(
                index_name=index_name,
                vdb_core=vdb_core,
                updated_by=user_id,
            )

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
            cleanup_token = _SKIP_INDEX_SOURCE_CLEANUP.set(True)
            try:
                delete_index_result = await KnowledgeBaseManagementService.delete_index(
                    index_name, vdb_core, user_id
                )
            finally:
                _SKIP_INDEX_SOURCE_CLEANUP.reset(cleanup_token)

            # Construct final result
            result = {
                "status": "success",
                "message": (
                    f"Index {index_name} deleted successfully. "
                    f"MinIO: {minio_cleanup['deleted_count']} files deleted, "
                    f"{minio_cleanup['failed_count']} failed. "
                    f"Redis: Cleaned up {redis_cleanup_result.get('total_deleted', 0)} records."
                ),
                "es_delete_result": delete_index_result,
                "minio_cleanup": minio_cleanup,
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
    async def _delete_kb_source_objects(
        index_name: str,
        vdb_core: VectorDatabaseCore,
        updated_by: Optional[str] = None,
    ) -> Dict[str, int]:
        """Delete the canonical union of ES references and active ledger objects."""
        try:
            knowledge = get_knowledge_record({"index_name": index_name}) or {}
        except Exception:
            logger.exception(
                "Failed to retrieve knowledge record for index '%s'",
                index_name,
            )
            knowledge = {}
        tenant_id = knowledge.get("tenant_id")
        knowledge_id = knowledge.get("knowledge_id")

        ledger_objects: List[Dict[str, Any]] = []
        if tenant_id and knowledge_id is not None:
            try:
                ledger_objects = list_committed_storage_objects(
                    tenant_id=tenant_id,
                    knowledge_id=knowledge_id,
                ) or []
            except Exception:
                logger.exception(
                    "Failed to retrieve active storage ledger objects for index '%s'",
                    index_name,
                )

        try:
            file_list_result = await KnowledgeBaseManagementService.list_files(
                index_name,
                include_chunks=False,
                vdb_core=vdb_core,
            )
            files_to_delete = file_list_result.get("files", [])
        except Exception:
            logger.exception(
                "Failed to retrieve file list for index '%s'",
                index_name,
            )
            files_to_delete = []

        targets, invalid_entries = KnowledgeBaseManagementService._collect_kb_source_targets(
            ledger_objects,
            files_to_delete,
        )

        deleted_count = 0
        failed_count = invalid_entries
        for target in targets.values():
            if KnowledgeBaseManagementService._delete_kb_source_target(
                target=target,
                tenant_id=tenant_id,
                updated_by=updated_by,
            ):
                deleted_count += 1
            else:
                failed_count += 1

        logger.info(
            "MinIO file deletion summary for index '%s': %s succeeded, %s failed.",
            index_name,
            deleted_count,
            failed_count,
        )
        return {
            "total_files_found": len(targets) + invalid_entries,
            "deleted_count": deleted_count,
            "failed_count": failed_count,
        }

    @staticmethod
    def _collect_kb_source_targets(
        ledger_objects: List[Dict[str, Any]],
        es_files: List[Dict[str, Any]],
    ) -> tuple[Dict[tuple, Dict[str, str]], int]:
        """Build canonical deletion targets and skip ambiguous ES references."""
        targets: Dict[tuple, Dict[str, str]] = {}
        ledger_aliases = set()
        for row in ledger_objects:
            bucket_name = row.get("bucket_name")
            object_name = row.get("object_name")
            if not bucket_name or not object_name:
                continue
            identity = (bucket_name, object_name)
            targets[identity] = {
                "bucket_name": bucket_name,
                "object_name": object_name,
            }
            ledger_aliases.update({
                object_name,
                f"s3://{bucket_name}/{object_name}",
                f"/{bucket_name}/{object_name}",
            })

        invalid_entries = 0
        for file_info in es_files:
            raw_path = file_info.get("path_or_url")
            if not raw_path or raw_path in ledger_aliases:
                invalid_entries += int(not raw_path)
                continue
            reference = resolve_storage_reference(raw_path)
            if reference is None:
                invalid_entries += 1
                logger.warning("Skipping non-canonical KB source reference during deletion")
                continue
            identity = (reference.bucket_name, reference.object_name)
            targets.setdefault(identity, {
                "bucket_name": reference.bucket_name,
                "object_name": reference.object_name,
            })
        return targets, invalid_entries

    @staticmethod
    def _delete_kb_source_target(
        *,
        target: Dict[str, str],
        tenant_id: Optional[str],
        updated_by: Optional[str],
    ) -> bool:
        """Delete one canonical source target and release its ledger charge."""
        object_name = target["object_name"]
        bucket_name = target["bucket_name"]
        try:
            delete_result = delete_file(object_name=object_name, bucket=bucket_name)
            if not delete_result.get("success"):
                logger.error("Failed to delete a canonical KB source object from MinIO")
                return False
        except Exception:
            logger.exception("Failed to delete a canonical KB source object from MinIO")
            return False

        if tenant_id:
            try:
                release_storage_charge(
                    tenant_id=tenant_id,
                    bucket_name=bucket_name,
                    object_name=object_name,
                    updated_by=updated_by,
                )
            except Exception:
                logger.exception("Failed to release a deleted KB source object's charge")
        return True

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
            model_id: Optional[int] = Body(
                None, description="ID of the embedding model to use"),
    ):
        try:
            if vdb_core.check_index_exists(index_name):
                raise Exception(f"Index {index_name} already exists")

            # Get embedding model by model_id if provided
            if model_id:
                embedding_model, actual_model_id = get_embedding_model_by_id(tenant_id, model_id)
            else:
                embedding_model, actual_model_id = None, None

            success = vdb_core.create_index(index_name, embedding_dim=embedding_dim or (
                embedding_model.embedding_dim if embedding_model else 1024))
            if not success:
                raise Exception(f"Failed to create index {index_name}")
            knowledge_data = {"index_name": index_name,
                              "created_by": user_id,
                              "tenant_id": tenant_id,
                              "embedding_model_name": embedding_model.model if embedding_model else None,
                              "embedding_model_id": actual_model_id}
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
            embedding_model_id: Optional[int] = None,
            preserve_source_file: Optional[bool] = None,
            quota_limit_bytes: Optional[int] = None,
            user_role: Optional[str] = None,
    ):
        """
        Create a new knowledge base with a user-facing name and an internal Elasticsearch index name.

        For new data:
        - Store the user-facing name in knowledge_name column.
        - Generate index_name as ``knowledge_id + '-' + uuid`` (digits and lowercase letters only).
        - Use generated index_name as the Elasticsearch index name.

        Args:
            knowledge_name: User-facing knowledge base name
            embedding_dim: Dimension of the embedding vectors (optional)
            vdb_core: VectorDatabaseCore instance
            user_id: User ID who creates the knowledge base
            tenant_id: Tenant ID
            ingroup_permission: Permission level (optional)
            group_ids: List of group IDs (optional)
            embedding_model_id: Unique ID of the selected embedding model.
            preserve_source_file: Whether to preserve uploaded source documents after
                                   vectorization (optional; defaults to True when omitted).
            user_role: Normalized user role. USER callers are forced to PRIVATE.

        For backward compatibility, legacy callers can still use create_index() directly
        with an explicit index_name.
        """
        try:
            knowledge_name = knowledge_name.strip()
            if not knowledge_name:
                raise ValueError("Knowledge base name is required")
            if embedding_model_id is None:
                raise ValueError("embedding_model_id is required")

            model = get_model_by_model_id(embedding_model_id, tenant_id)
            if not model:
                raise ValueError(f"Embedding model with id {embedding_model_id} not found")
            if model.get("model_type") not in ["embedding", "multi_embedding"]:
                raise ValueError(
                    f"Model with id {embedding_model_id} is not an embedding model"
                )

            embedding_model = create_embedding_model(model)
            saved_embedding_model_name = model.get("display_name") or model.get("model_name")

            # Create knowledge record first to obtain knowledge_id and generated index_name
            knowledge_data = {
                "knowledge_name": knowledge_name,
                "knowledge_describe": "",
                "user_id": user_id,
                "tenant_id": tenant_id,
                "embedding_model_name": saved_embedding_model_name,
                "embedding_model_id": embedding_model_id,
            }

            # Add group permission and group IDs if provided.
            if str(user_role or "").upper() == "USER":
                knowledge_data["ingroup_permission"] = PERMISSION_PRIVATE
                knowledge_data["group_ids"] = None
            else:
                if ingroup_permission is not None:
                    knowledge_data["ingroup_permission"] = ingroup_permission
                if group_ids is not None:
                    knowledge_data["group_ids"] = group_ids
            if preserve_source_file is not None:
                knowledge_data["preserve_source_file"] = preserve_source_file
            if quota_limit_bytes is not None:
                knowledge_data["quota_limit_bytes"] = quota_limit_bytes

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
                "embedding_model_name": saved_embedding_model_name,
                "model_type": model.get("model_type"),
                "knowledge_id": record_info["knowledge_id"],
                "name": record_info.get("knowledge_name", knowledge_name),
            }
        except (DuplicateError, ValueError):
            raise
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
        if ingroup_permission is not None and ingroup_permission not in valid_permissions:
            raise ValueError(
                f"Invalid ingroup_permission. Must be one of: {valid_permissions}"
            )

        if str(user_role or "").upper() == "USER":
            record = get_knowledge_record({"index_name": index_name})
            if not record:
                raise ValueError(f"Knowledge base '{index_name}' not found")
            if str(record.get("ingroup_permission") or "").upper() != PERMISSION_PRIVATE:
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
                f"Knowledge base '{index_name}' updated successfully by user '{user_id}'")

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
                user_id=user_id or ""
            )

            if not success:
                raise Exception(f"Failed to update embedding model for index '{index_name}'")

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
                "message": f"Embedding model updated successfully to '{model_display_name}'"
            }

        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Failed to update embedding model for index '{index_name}': {e}")
            raise Exception(f"Failed to update embedding model: {str(e)}")

    @staticmethod
    async def delete_index(
            index_name: str = Path(...,
                                   description="Name of the index to delete"),
            vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
            user_id: Optional[str] = Body(
                None, description="ID of the user delete the knowledge base"),
    ):
        try:
            if not _SKIP_INDEX_SOURCE_CLEANUP.get():
                try:
                    await KnowledgeBaseManagementService._delete_kb_source_objects(
                        index_name=index_name,
                        vdb_core=vdb_core,
                        updated_by=user_id,
                    )
                except Exception as e:
                    logger.error(
                        f"Error deleting associated files from MinIO for index {index_name}: {str(e)}")

            # Delete the index in Elasticsearch
            success = vdb_core.delete_index(index_name)
            if not success:
                # Even if deletion fails, we proceed to database record cleanup
                logger.warning(
                    f"Index {index_name} not found in Elasticsearch or could not be deleted, but proceeding with DB cleanup.")

            # Delete the knowledge base record from the database
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
            "sources": sorted({
                str(record.get("knowledge_sources"))
                for record in visible_knowledgebases
                if record.get("knowledge_sources")
            }),
            "models": sorted({
                str(record.get("embedding_model_name"))
                for record in visible_knowledgebases
                if record.get("embedding_model_name")
            }),
        }
        normalized_keyword = (keyword or "").strip().lower()
        selected_sources = {source for source in (sources or []) if source}
        selected_models = {model for model in (models or []) if model}
        filtered = [
            record for record in visible_knowledgebases
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
        page = filtered[offset:offset + limit]
        next_offset = offset + len(page)
        return page, {
            "total": total,
            "next_offset": next_offset if next_offset < total else None,
            "facets": facets,
        }

    _apply_read_only_to_asset_indices_info = staticmethod(apply_read_only_to_asset_indices_info)
    merge_list_indices_results = staticmethod(merge_list_indices_results)
    merge_paginated_list_indices_results = staticmethod(merge_paginated_list_indices_results)

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
    ):
        """
        List all indices that the current user has permissions to access based on role and group permissions.

        Permission logic:
        - SU: All knowledgebases visible, all editable
        - ADMIN: Knowledgebases from same tenant visible, all editable
        - DEV on ASSET_OWNER-scoped records: all visible, read-only (READ_ONLY)
        - SU/ADMIN/SPEED cross-tenant view of ASSET_OWNER records: read-only
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

        user_role = user_tenant.get("user_role")
        user_tenant_id = str(user_tenant.get("tenant_id") or target_tenant_id or "")
        # Get user group IDs from tenant_group_user_t table
        user_group_ids = query_group_ids_by_user(user_id)

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
            if record['knowledge_sources'] == 'datamate':
                continue
            # Check if index exists in Elasticsearch (skip if not found)
            if index_name not in es_indices_list:
                continue

            # Fallback logic: if user_id equals user_tenant_id, treat as legacy admin user
            # even if user_role is None or empty
            effective_user_role = user_role
            if user_id == user_tenant_id:
                effective_user_role = "ADMIN"
                logger.info(f"User {user_id} identified as legacy admin")
            elif IS_SPEED_MODE and not user_role:
                effective_user_role = "SPEED"
                logger.info("User under SPEED version is treated as admin")

            # SPEED mode may run without a user_tenant_t row; trust the
            # requested tenant for the check in that legacy deployment.
            effective_user_tenant_id = user_tenant_id or str(
                record.get("tenant_id") or ""
            )
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
                role=(effective_user_role or "").upper(),
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
        visible_knowledgebases = postprocess_knowledge_visibility(
            visible_knowledgebases,
            caller_role=user_role,
            caller_tenant_id=target_tenant_id,
        )

        visible_knowledgebases, pagination = KnowledgeBaseManagementService._prepare_indices_page(
            visible_knowledgebases=visible_knowledgebases,
            pagination_enabled=pagination_enabled,
            offset=offset,
            limit=limit,
            keyword=keyword,
            sources=sources,
            models=models,
        )

        indices = [record["index_name"] for record in visible_knowledgebases]

        response = {
            "indices": indices,
            "count": len(indices),
            "index_permissions": {
                record["index_name"]: record["permission"]
                for record in visible_knowledgebases
            },
        }
        if pagination_enabled:
            response.update({
                **pagination,
                "estimated_row_height": 112,
                "estimated_item_heights": None,
            })

        if include_stats:
            stats_info = []
            if visible_knowledgebases:
                index_names = [record["index_name"]
                               for record in visible_knowledgebases]
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

                    stats_info.append({
                        "knowledge_id": record.get("knowledge_id"),
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
                        "embedding_model_name": embedding_model_display_name or record.get("embedding_model_name", ""),
                        "embedding_model_id": model_id,
                        # Update time for sorting and display
                        "update_time": record.get("update_time"),
                        # Auto-summary settings
                        "summary_frequency": record.get("summary_frequency"),
                        "last_summary_time": record.get("last_summary_time"),
                        "preserve_source_file": record.get("preserve_source_file", True),
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
            embedding_model: EmbeddingAdapter,
            index_name: str = Path(..., description="Name of the index"),
            data: List[Dict[str, Any]
                       ] = Body(..., description="Document List to process"),
            vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
            task_id: Optional[str] = None,
            model_id: Optional[int] = Body(
                None, description="ID of the embedding model to use"),
            large_mode: bool = False,
    ):
        """
        Index documents and create vector embeddings, create index if it doesn't exist

        Args:
            embedding_model: Optional embedding model to use for generating document vectors
            index_name: Index name
            data: List containing document data to be indexed
            vdb_core: VectorDatabaseCore instance
            task_id: Optional task ID for progress tracking
            model_id: Optional model ID for the embedding model

        Returns:
            IndexingResponse object containing indexing result information
        """
        try:
            if not index_name:
                raise Exception("Index name is required")

            # Create index if needed (ElasticSearchCore will handle embedding_dim automatically)
            if not vdb_core.check_index_exists(index_name):
                try:
                    KnowledgeBaseManagementService.create_index(
                        index_name, vdb_core=vdb_core, model_id=model_id)
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
                    "process_source": metadata.get("process_source", "Unstructured"),
                    "file_size": file_size,
                    "create_time": create_time,
                    "languages": metadata.get("languages", []),
                    "embedding_model_name": embedding_model_name
                }
                
                image_url = metadata.get("image_url", "")
                if len(image_url) > 0:
                    # Fetch image bytes from MinIO (supports s3://bucket/key or /bucket/key)
                    try:
                        file_stream = get_file_stream(
                            object_name=image_url)
                        if file_stream is None:
                            raise FileNotFoundError(
                                f"Unable to fetch file from URL: {image_url}")
                        document["image_bytes"] = file_stream.read()
                    except Exception as e:
                        logger.error(
                            f"Failed to fetch file from {image_url}: {e}")
                        raise

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
                model_type = "EMBEDDING_ID" if embedding_model.model_type == "embedding" else "MULTI_EMBEDDING_ID"
                model_config = tenant_config_manager.get_model_config(
                    key=model_type, tenant_id=tenant_id)
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
                    large_mode=large_mode,
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

                # Update last_doc_update_time for auto-summary tracking
                update_last_doc_update_time(index_name)

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
            total_start_time = time.time()

            logger.info(f"[list_files] index={index_name}, include_chunks={include_chunks}")

            # Step 1: Get existing files from ES (includes chunk_count via aggregation)
            step1_start = time.time()
            existing_files = vdb_core.get_documents_detail(index_name)
            step1_duration = time.time() - step1_start
            logger.info(f"[list_files:step1] ES get_documents_detail: {len(existing_files)} files in {step1_duration:.3f}s")

            # Step 2: Get celery task statuses from external service
            step2_start = time.time()
            celery_task_files = await get_all_files_status(index_name)
            step2_duration = time.time() - step2_start
            logger.info(f"[list_files:step2] Celery task status: {len(celery_task_files)} tasks in {step2_duration:.3f}s")

            # Step 3: Build files_map from ES data
            step3_start = time.time()
            for file_info in existing_files:
                utc_create_time_str = file_info.get('create_time', '')
                try:
                    utc_create_timestamp = datetime.strptime(utc_create_time_str, '%Y-%m-%dT%H:%M:%S').replace(
                        tzinfo=timezone.utc).timestamp()
                except (ValueError, TypeError):
                    utc_create_timestamp = time.time()

                path_or_url = file_info.get('path_or_url')
                file_data = {
                    'path_or_url': path_or_url,
                    'file': file_info.get('filename', ''),
                    'file_size': file_info.get('file_size', 0),
                    'create_time': int(utc_create_timestamp * 1000),
                    'status': "COMPLETED",
                    'latest_task_id': '',
                    'chunk_count': file_info.get('chunk_count', 0),
                    'error_reason': None,
                    'has_error_info': False
                }
                files_map[path_or_url] = file_data
            step3_duration = time.time() - step3_start
            logger.info(f"[list_files:step3] Build files_map from ES: {len(existing_files)} files in {step3_duration:.3f}s")

            # Step 4: Merge celery task data (Redis progress already fetched in get_all_files_status)
            step4_start = time.time()
            celery_file_count = 0
            for path_or_url, status_info in celery_task_files.items():
                celery_file_count += 1
                status_dict = status_info if isinstance(status_info, dict) else {}

                source_type = status_dict.get('source_type') if status_dict.get('source_type') else 'minio'
                original_filename = status_dict.get('original_filename')
                filename = original_filename or (os.path.basename(path_or_url) if path_or_url else '')

                file_size = 0
                if path_or_url in files_map:
                    file_size = files_map[path_or_url].get('file_size', 0)
                else:
                    try:
                        file_size = get_file_size(source_type or 'minio', path_or_url)
                    except Exception as size_err:
                        logger.error(f"Failed to get file size for '{path_or_url}': {size_err}")
                        file_size = 0

                # Get progress from celery_task_files (already includes Redis batch data)
                processed_chunks = status_dict.get('processed_chunks')
                total_chunks = status_dict.get('total_chunks')
                task_id = status_dict.get('latest_task_id', '')

                if path_or_url in files_map:
                    file_data = files_map[path_or_url]
                else:
                    legacy_created_at = status_dict.get("created_at")
                    try:
                        if isinstance(legacy_created_at, (int, float)):
                            legacy_timestamp = (
                                float(legacy_created_at) / 1000
                                if legacy_created_at > 10_000_000_000
                                else float(legacy_created_at)
                            )
                        else:
                            legacy_timestamp = datetime.fromisoformat(
                                str(legacy_created_at).replace("Z", "+00:00")
                            ).timestamp()
                    except (TypeError, ValueError, OverflowError):
                        legacy_timestamp = time.time()
                    file_data = {
                        'path_or_url': path_or_url,
                        'file': filename,
                        'file_size': file_size,
                        'create_time': int(legacy_timestamp * 1000),
                        'chunk_count': 0,
                        'error_reason': None,
                        'has_error_info': False
                    }
                    files_map[path_or_url] = file_data

                file_data['status'] = status_dict.get('state', file_data.get('status', 'UNKNOWN'))
                file_data['latest_task_id'] = task_id
                file_data['processed_chunk_num'] = processed_chunks
                file_data['total_chunk_num'] = total_chunks

                # Get error reason for failed documents (fetch from Redis batch if needed)
                if task_id and status_dict.get('state') in ['PROCESS_FAILED', 'FORWARD_FAILED']:
                    try:
                        redis_service = get_redis_service()
                        error_reason = redis_service.get_error_info(task_id)
                        if error_reason:
                            file_data['error_reason'] = error_reason
                            file_data['has_error_info'] = True
                    except Exception:
                        pass  # Error info is optional, don't fail the request
            step4_duration = time.time() - step4_start
            logger.info(f"[list_files:step4] Merge celery tasks: {celery_file_count} tasks in {step4_duration:.3f}s")

            # Durable lifecycle rows are authoritative for upload failures,
            # timestamps, and deletion tombstones. If the migration is not
            # present yet, retain the legacy ES/Redis result unchanged.
            try:
                knowledge_record = get_knowledge_record({"index_name": index_name}) or {}
                lifecycle_rows = list_file_records(
                    index_name=index_name,
                    tenant_id=knowledge_record.get("tenant_id"),
                    include_hidden=True,
                )
                hidden_paths = {
                    row.get("object_name")
                    for row in lifecycle_rows
                    if row.get("status") in {"DELETE_REQUESTED", "DELETED"}
                    and row.get("object_name")
                }
                for hidden_path in hidden_paths:
                    files_map.pop(hidden_path, None)

                status_map = {
                    "UPLOADING": "WAIT_FOR_PROCESSING",
                    "UPLOADED": "WAIT_FOR_PROCESSING",
                    "PROCESSING": "PROCESSING",
                    "FORWARDING": "FORWARDING",
                    "COMPLETED": "COMPLETED",
                }
                for row in lifecycle_rows:
                    if row.get("status") in {"DELETE_REQUESTED", "DELETED"}:
                        continue
                    path_or_url = row.get("object_name")
                    row_key = path_or_url or f"lifecycle:{row.get('file_id')}"
                    existing = files_map.get(path_or_url) if path_or_url else None
                    timestamp_value = row.get("uploaded_at") or row.get("create_time")
                    try:
                        timestamp = datetime.fromisoformat(
                            str(timestamp_value).replace("Z", "+00:00")
                        ).timestamp()
                    except (TypeError, ValueError, OverflowError):
                        timestamp = time.time()
                    lifecycle_status = row.get("status") or "UPLOADING"
                    if lifecycle_status == "FAILED":
                        lifecycle_status = (
                            "FORWARD_FAILED"
                            if str(row.get("error_stage") or row.get("stage") or "").upper() in {"FORWARD", "FORWARDING"}
                            else "PROCESS_FAILED"
                        )
                    # Keep the pre-lifecycle display contract for rows that still
                    # have an ES/Redis name. New rows synchronize the same effective
                    # name into PG after conflict resolution; PG is the fallback when
                    # no legacy name is available (for example after Redis expiry).
                    lifecycle_filename = row.get("original_filename") or ""
                    legacy_filename = (existing or {}).get("file") or ""
                    display_filename = legacy_filename or lifecycle_filename
                    file_data = existing or {
                        "path_or_url": path_or_url,
                        "file": display_filename,
                        "file_size": row.get("file_size") or 0,
                        "create_time": int(timestamp * 1000),
                        "chunk_count": 0,
                        "error_reason": None,
                        "has_error_info": False,
                    }
                    file_data.update({
                        "path_or_url": path_or_url,
                        "file": display_filename or file_data.get("file", ""),
                        "file_size": row.get("file_size") if row.get("file_size") is not None else file_data.get("file_size", 0),
                        "create_time": int(timestamp * 1000),
                        "status": status_map.get(lifecycle_status, lifecycle_status),
                        "latest_task_id": row.get("forward_task_id") or row.get("process_task_id") or "",
                        "file_id": row.get("file_id"),
                        "error_reason": row.get("error_message") or row.get("error_code"),
                        "error_code": row.get("error_code"),
                        "error_stage": row.get("error_stage") or row.get("stage"),
                        "failed_at": row.get("failed_at"),
                        "has_error_info": bool(row.get("error_message") or row.get("error_code")),
                    })
                    files_map[row_key] = file_data
            except Exception as lifecycle_exc:
                logger.warning(
                    "[list_files] Lifecycle table unavailable; using legacy ES/Redis data: %s",
                    lifecycle_exc,
                )

            files = list(files_map.values())
            logger.info(f"[list_files:step4] Total files built: {len(files)}")

            # Unified chunks processing for all files
            if include_chunks:
                step5_start = time.time()
                completed_files_map = {
                    f['path_or_url']: f for f in files if f['status'] == "COMPLETED"}
                completed_count = len(completed_files_map)
                msearch_body = []

                for path_or_url in completed_files_map.keys():
                    msearch_body.append({'index': index_name})
                    msearch_body.append({
                        "query": {"term": {"path_or_url": path_or_url}},
                        "size": 100,
                        "_source": ["id", "title", "content", "create_time"]
                    })

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
                            # chunk_count from aggregation is already accurate
                            # no need for additional count queries

                    except Exception as e:
                        logger.error(
                            f"Error during msearch for chunks: {str(e)}")
                step5_duration = time.time() - step5_start
                logger.info(f"[list_files:step5] ES msearch chunks: {completed_count} files in {step5_duration:.3f}s")
            else:
                # When include_chunks=False, chunk_count is already accurate from ES aggregation
                # No need for additional count queries - doc_count from terms aggregation is accurate
                for file_data in files:
                    file_data['chunks'] = []
                    # chunk_count is already set from ES aggregation (doc_count)
                    file_data['chunk_count'] = file_data.get('chunk_count', 0)

            for file_data in files:
                file_data["source_available"] = (
                    KnowledgeBaseManagementService._compute_source_available(file_data)
                )

            total_duration = time.time() - total_start_time
            logger.info(f"[list_files:complete] index={index_name}, total_files={len(files)}, "
                       f"total_duration={total_duration:.3f}s")

            return {"files": files}

        except Exception as e:
            raise Exception(
                f"Error getting file list for index {index_name}: {str(e)}")

    DOCUMENT_DELETE_SCOPES = ("source_only", "full")


    @staticmethod
    def _compute_source_available(file_data: Dict[str, Any]) -> bool:
        path_or_url = file_data.get("path_or_url") or ""
        status = file_data.get("status", "")
        if status != "COMPLETED":
            return True
        if path_or_url.startswith((
            "knowledge_base/",
            f"{ASSET_OWNER_ATTACHMENTS_PREFIX}/",
        )):
            return file_exists(path_or_url)
        return True

    @staticmethod
    def delete_source_file(
        path_or_url: str,
        tenant_id: Optional[str] = None,
        updated_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Remove MinIO source (and preview cache); does not touch Elasticsearch."""
        minio_result = delete_file(path_or_url)
        deleted_minio = bool(minio_result.get("success"))

        if deleted_minio and tenant_id:
            reference = resolve_storage_reference(path_or_url)
            if reference:
                try:
                    release_storage_charge(
                        tenant_id=tenant_id,
                        bucket_name=reference.bucket_name,
                        object_name=reference.object_name,
                        updated_by=updated_by,
                    )
                except Exception:
                    logger.exception(
                        "Failed to release storage charge after deleting '%s'",
                        path_or_url,
                    )

        if path_or_url.startswith("knowledge_base/"):
            preview_key = build_preview_pdf_object_key(
                path_or_url
            )
            try:
                if file_exists(preview_key):
                    delete_file(preview_key)
            except Exception as exc:
                logger.warning(
                    "Failed to delete preview cache for '%s': %s",
                    path_or_url,
                    exc,
                )

        return {"deleted_minio": deleted_minio}
