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
import hashlib
import inspect
import json
import logging
import os
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, Path, Query
from fastapi.responses import StreamingResponse
from nexent.core.gateway.modality import EmbeddingAdapter
from nexent.vector_database.base import VectorDatabaseCore
from nexent.vector_database.elasticsearch_core import ElasticSearchCore
from nexent.vector_database.datamate_core import DataMateCore

from consts.const import (
    ASSET_OWNER_ATTACHMENTS_PREFIX,
    ASSET_OWNER_TENANT_ID,
    DATAMATE_URL,
    DOCUMENT_DELETE_DRAIN_TIMEOUT_S,
    DOCUMENT_DELETE_RETRY_INTERVAL_S,
    ES_API_KEY,
    ES_HOST,
    IS_SPEED_MODE,
    LANGUAGE,
    PERMISSION_EDIT,
    PERMISSION_PRIVATE,
    PERMISSION_READ,
    VectorDatabaseType,
)
from consts.error_code import ErrorCode
from consts.exceptions import AppException, DuplicateError
from consts.model import ChunkCreateRequest, ChunkUpdateRequest
from database.attachment_db import delete_file, file_exists, get_file_stream
from database.knowledge_db import (
    create_knowledge_record,
    delete_knowledge_record,
    get_knowledge_record,
    update_knowledge_record,
    get_knowledge_info_by_tenant_id,
    update_model_name_by_index_name,
    update_last_doc_update_time,
    update_last_summary_time,
    update_embedding_model_by_index_name,
)
from database.knowledge_storage_object_db import list_committed_storage_objects
from database.knowledge_file_lifecycle_db import (
    create_delete_tombstone,
    delete_file_record,
    delete_file_records_for_knowledge_base,
    get_file_record,
    list_file_records,
    transition_file_record,
)
from services.knowledge_storage_service import (
    release_storage_charge,
    resolve_storage_reference,
)
from utils.str_utils import convert_list_to_string
from database.user_tenant_db import get_user_tenant_by_user_id
from database.group_db import query_group_ids_by_user
from database.model_management_db import get_model_by_display_name, get_model_by_model_id, get_model_records
from permissions.dac import ResourceAccessControl
from permissions.models import Resource
from services.redis_service import get_redis_service
from services.group_service import get_tenant_default_group_id
from services.asset_owner_visibility import postprocess_knowledge_visibility
from utils.config_utils import tenant_config_manager
from services.model_gateway_service import build_adapter_fresh
from utils.file_management_utils import get_all_files_status, get_file_size
from utils.str_utils import convert_string_to_list


_document_delete_tasks: Dict[str, asyncio.Task] = {}


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


def _get_embedding_model_display_name(model_id: Optional[int], tenant_id: str) -> str:
    """
    Get embedding model display_name from model_id.

    Args:
        model_id: The model ID to look up
        tenant_id: Tenant ID for the lookup

    Returns:
        The model's display_name if found, empty string otherwise
    """
    if model_id is None:
        return ""
    try:
        model = get_model_by_model_id(model_id, tenant_id)
        if model:
            return model.get("display_name", "")
    except Exception as e:
        logger.warning(f"Failed to get display_name for model_id {model_id}: {e}")
    return ""


def _is_multimodal_by_model_id(model_id: Optional[int], tenant_id: str) -> bool:
    """
    Determine whether an embedding model is multimodal based on model_id.

    Args:
        model_id: The embedding model ID.
        tenant_id: Tenant ID for model lookup.

    Returns:
        True when the model type is `multi_embedding`, otherwise False.
    """
    if model_id is None:
        return False
    try:
        model = get_model_by_model_id(model_id, tenant_id)
        if model:
            return model.get("model_type") == "multi_embedding"
    except Exception as e:
        logger.warning(f"Failed to determine multimodal flag for model_id {model_id}: {e}")
    return False


class KnowledgeBaseNeedsModelConfigError(Exception):
    """Exception raised when a knowledge base needs an embedding model to be configured."""
    def __init__(self, index_name: str, message: str = None):
        self.index_name = index_name
        self.message = message or f"Knowledge base '{index_name}' needs an embedding model to be configured"
        super().__init__(self.message)


def get_embedding_model_by_index_name(tenant_id: str, index_name: str) -> tuple[Optional[Any], Optional[int], dict]:
    """
    Get the embedding model for a knowledge base by its index_name.

    Args:
        tenant_id: Tenant ID
        index_name: The index name of the knowledge base

    Returns:
        Tuple of (embedding model instance or None, model_id or None, metadata dict)
        metadata contains: {
            "status": str,           # "ok" | "needs_config" | "error"
            "needs_update": bool,    # Whether the database needs to be updated
            "update_info": dict,     # Fields to update if needs_update is True
            "message": str           # Status message
        }

    Design principles:
        - Force explicit configuration: model_id must be explicitly set by user
        - No auto-fix: never automatically use tenant default model
        - Clear error guidance: return needs_config status for user action
    """
    try:
        knowledge_record = get_knowledge_record({
            "index_name": index_name,
            "tenant_id": tenant_id,
            "include_asset_owner_assets": True,
        })

        if not knowledge_record:
            return None, None, {
                "status": "error",
                "needs_update": False,
                "message": f"Knowledge base '{index_name}' not found"
            }

        model_id = knowledge_record.get("embedding_model_id")

        # Case 1: model_id exists and is valid, use it
        if model_id:
            model, _ = get_embedding_model_by_id(tenant_id, model_id)
            if model:
                return model, model_id, {
                    "status": "ok",
                    "needs_update": False,
                    "message": "Embedding model found"
                }
            # Model ID exists but model not found - fall through to error
            logger.warning(f"Model ID {model_id} specified for index '{index_name}' but model not found")

        # Case 2: model_id does not exist or is invalid
        # Design principle: Force explicit configuration, no auto-fix
        # Return needs_config to guide user to select a model
        embedding_model_name = knowledge_record.get("embedding_model_name")
        if embedding_model_name:
            # Has model_name but no valid model_id (legacy data)
            logger.warning(f"Index '{index_name}' has embedding_model_name but no valid model_id, needs explicit configuration")
        else:
            # No model configured at all
            logger.error(f"Index '{index_name}' has no embedding model configured")

        return None, None, {
            "status": "needs_config",
            "needs_update": False,
            "message": f"No embedding model configured for knowledge base '{index_name}'. Please select a model."
        }

    except Exception as e:
        logger.warning(f"Failed to get embedding model for index {index_name}: {e}")
        return None, None, {
            "status": "error",
            "needs_update": False,
            "message": str(e)
        }


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

_QUOTA_LIMIT_UNSET = object()
_SKIP_INDEX_SOURCE_CLEANUP: ContextVar[bool] = ContextVar(
    "skip_index_source_cleanup", default=False
)

# A knowledge base cannot be removed while ingestion still owns a file.  The
# delete-requested state is intentionally excluded: it means the single-file
# deletion flow has already taken ownership of that file's cleanup.
KNOWLEDGE_BASE_DELETE_BLOCKING_STATUSES = frozenset({
    "UPLOADING",
    "UPLOADED",
    "PROCESSING",
    "FORWARDING",
})


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


def check_knowledge_base_exist_impl(knowledge_name: str, vdb_core: VectorDatabaseCore, user_id: str, tenant_id: str, exclude_index_name: Optional[str] = None) -> dict:
    """
    Check knowledge base existence and handle orphan cases

    Args:
        knowledge_name: Name of the knowledge base to check
        vdb_core: Elasticsearch core instance
        user_id: Current user ID
        tenant_id: Current tenant ID
        exclude_index_name: Optional index name to exclude from the check (used when updating an existing knowledge base)

    Returns:
        dict: Status information about the knowledge base
    """
    # 1. Check if knowledge_name exists in PG for the current tenant
    pg_record = get_knowledge_record(
        {"knowledge_name": knowledge_name, "tenant_id": tenant_id})

    # Case A: Knowledge base name already exists in the same tenant
    if pg_record:
        # If we're excluding a specific index and this is the one we found, consider it available
        if exclude_index_name and pg_record.get("index_name") == exclude_index_name:
            return {"status": "available"}
        return {"status": "exists_in_tenant"}

    # Case B: Name is available in this tenant
    return {"status": "available"}

def _normalize_model_type(raw_model_type: Optional[str]) -> Optional[str]:
    if raw_model_type in ["multiEmbedding", "multi_embedding"]:
        return "multi_embedding"
    if raw_model_type == "embedding":
        return "embedding"
    return None

def _build_model_config(model: dict) -> dict:
    config = {
        "model_repo": model.get("model_repo", ""),
        "model_name": model["model_name"],
        "api_key": model.get("api_key", ""),
        "base_url": model.get("base_url", ""),
        "model_type": model.get("model_type", "embedding"),
        "max_tokens": model.get("max_tokens", 1024),
        "ssl_verify": model.get("ssl_verify", True),
    }
    # Carry the vendor through so multi_embedding/embedding adapters dispatch
    # to the right provider instead of silently falling back to the default.
    if model.get("model_factory"):
        config["model_factory"] = model["model_factory"]
    return config

def _create_embedding_model(model: dict) -> Any:
    model_config = _build_model_config(model)
    model_type = model_config.get("model_type", "embedding")

    if model_type == "multi_embedding":
        modality, slot = "multi_embedding", "multiEmbedding"
    elif model_type == "embedding":
        modality, slot = "embedding", "embedding"
    else:
        raise ValueError(
            f"Invalid model_type '{model_type}' for model '{model_config.get('model_name')}'. "
            f"Expected 'embedding' or 'multi_embedding', got '{model_type}'. "
            f"Please check the model configuration in the model management page."
        )

    # Vendor dispatch (DashScope/Siliconflow/Jina/OpenAI) is resolved by the
    # adapter registry; per-vendor request-body formatting lives in the
    # embedding adapters. Built fresh (no gateway cache). Returns the adapter;
    # callers use adapter.get_embeddings / adapter.dimension_check unchanged.
    return build_adapter_fresh(model_config, modality, slot, None)

def get_embedding_model(
        tenant_id: str,
        model_name: Optional[str] = None,
        model_type: Optional[str] = None
) -> tuple[Optional[Any], Optional[int]]:
    """
    Get the embedding model for the tenant, optionally using a specific model name.

    Args:
        tenant_id: Tenant ID
        model_name: Optional display name of the embedding model to use.
                   If provided, will find the model by display_name in the tenant's model list.
        model_type: Optional model type filter. When model_name is omitted, queries tenant
                   model records by this type; when model_type is also omitted, prefers
                   embedding models, then multi_embedding models.

    Returns:
        Tuple of (embedding model instance or None, model_id or None)
    """
    if model_name:
        try:
            model_type = _normalize_model_type(model_type)
            if model_type:
                model = get_model_by_display_name(model_name, tenant_id, model_type)
            else:
                model = get_model_by_display_name(model_name, tenant_id)

            if not model or model.get("model_type") not in ["embedding", "multi_embedding"]:
                logger.warning(f"Model '{model_name}' not found or is not an embedding model")
                return None, None

            return _create_embedding_model(model), model.get("model_id")
        except Exception as e:
            logger.warning(f"Failed to get embedding model by name {model_name}: {e}")
    else:
        try:
            if model_type:
                records = get_model_records({"model_type": model_type}, tenant_id)
            else:
                records = get_model_records({"model_type": "embedding"}, tenant_id)
                if not records:
                    records = get_model_records({"model_type": "multi_embedding"}, tenant_id)

            if records:
                model = records[0]
                if model.get("model_type") in ["embedding", "multi_embedding"]:
                    return _create_embedding_model(model), model.get("model_id")
                logger.warning(
                    f"Resolved model is not an embedding model: {model.get('model_type')}"
                )
        except Exception as e:
            logger.warning(f"Failed to get default embedding model for tenant {tenant_id}: {e}")

    return None, None


def get_embedding_model_by_id(tenant_id: str, model_id: int) -> tuple[Optional[Any], Optional[int]]:
    """
    Get the embedding model by model_id.

    Args:
        tenant_id: Tenant ID
        model_id: Model ID to query

    Returns:
        Tuple of (embedding model instance or None, model_id or None)
    """
    try:
        model = get_model_by_model_id(model_id, tenant_id)
        if model and model.get("model_type") in ["embedding", "multi_embedding"]:
            return _create_embedding_model(model), model.get("model_id")
        else:
            logger.warning(f"Model with id {model_id} not found or is not an embedding model")
    except Exception as e:
        logger.warning(f"Failed to get embedding model by id {model_id}: {e}")
    return None, None


def get_rerank_model(tenant_id: str, model_name: Optional[str] = None):
    """
    Get the rerank model for the tenant, optionally using a specific model name.

    Args:
        tenant_id: Tenant ID
        model_name: Optional specific model name to use (format: "model_repo/model_name" or just "model_name")
                   If provided, will try to find the model in the tenant's model list.

    Returns:
        Rerank model instance or None
    """
    # If model_name is provided, try to find it in the tenant's models
    if model_name:
        try:
            models = get_model_records({"model_type": "rerank"}, tenant_id)
            for model in models:
                model_display_name = model.get("model_repo") + "/" + model["model_name"] if model.get("model_repo") else model["model_name"]
                if model_display_name == model_name:
                    # Found the model; vendor dispatch via the adapter registry.
                    # The adapter IS the rerank implementation (protocol sunk in
                    # 67a628cad) — return it directly, not a wrapped _inner.
                    return build_adapter_fresh(
                        model, "rerank", "rerank", tenant_id
                    )
        except Exception as e:
            logger.warning(f"Failed to get rerank model by name {model_name}: {e}")

    # Fall back to default rerank model
    model_config = tenant_config_manager.get_model_config(
        key="RERANK_ID", tenant_id=tenant_id)

    model_type = model_config.get("model_type", "")

    if model_type == "rerank":
        return build_adapter_fresh(
            model_config, "rerank", "rerank", tenant_id
        )
    else:
        return None


class ElasticSearchService:
    CREATOR_PERMISSION = "CREATOR"

    @staticmethod
    def resolve_knowledge_base_permission(
        index_name: str,
        user_id: str,
        tenant_id: Optional[str] = None,
    ) -> Optional[str]:
        """Resolve the current user's permission for one knowledge base."""
        record = get_knowledge_record({"index_name": index_name})
        if not record:
            raise ValueError(f"Knowledge base '{index_name}' not found")

        user_tenant = get_user_tenant_by_user_id(user_id)
        if not user_tenant and not IS_SPEED_MODE:
            return None

        user_role = (user_tenant or {}).get("user_role")
        user_tenant_id = str((user_tenant or {}).get("tenant_id") or tenant_id or "")
        effective_user_role = user_role
        if user_id == user_tenant_id:
            effective_user_role = "ADMIN"
            logger.info(f"User {user_id} identified as legacy admin")
        elif IS_SPEED_MODE and not user_role:
            effective_user_role = "SPEED"
            logger.info("User under SPEED version is treated as admin")

        role = (effective_user_role or "").upper()
        if IS_SPEED_MODE and not user_tenant_id:
            # Speed mode may run without a user_tenant_t row; keep the legacy
            # behavior where the caller's tenant is trusted for the check.
            user_tenant_id = str(record.get("tenant_id") or tenant_id or "")

        user_group_ids = query_group_ids_by_user(user_id)
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
            role=role,
            user_groups=user_group_ids,
            user_tenant_id=user_tenant_id,
            asset_owner_tenant_id=ASSET_OWNER_TENANT_ID,
        )
        return access.permission_label

    @staticmethod
    def require_knowledge_base_edit_permission(
        index_name: str,
        user_id: str,
        tenant_id: Optional[str] = None,
    ) -> str:
        """Raise when the current user cannot modify the knowledge base."""
        permission = ElasticSearchService.resolve_knowledge_base_permission(
            index_name=index_name,
            user_id=user_id,
            tenant_id=tenant_id,
        )
        if permission not in {PERMISSION_EDIT, ElasticSearchService.CREATOR_PERMISSION}:
            raise PermissionError("No permission to modify this knowledge base")
        return permission

    @staticmethod
    def require_knowledge_base_read_permission(
        index_name: str,
        user_id: str,
        tenant_id: Optional[str] = None,
    ) -> str:
        """Raise when the current user cannot read the knowledge base.

        Accepts any non-None permission level (READ_ONLY, EDIT, or CREATOR).
        """
        permission = ElasticSearchService.resolve_knowledge_base_permission(
            index_name=index_name,
            user_id=user_id,
            tenant_id=tenant_id,
        )
        if permission is None:
            raise PermissionError("No permission to access this knowledge base")
        return permission

    @staticmethod
    def filter_accessible_indices(
        index_names: List[str],
        user_id: str,
        tenant_id: Optional[str] = None,
    ) -> List[str]:
        """Return only the indices the user has at least read access to.

        Indices whose knowledge base record cannot be found, or whose permission
        check fails for any reason, are treated as inaccessible and dropped.
        Order of the accessible subset is preserved.
        """
        accessible: List[str] = []
        for index_name in index_names:
            try:
                permission = ElasticSearchService.resolve_knowledge_base_permission(
                    index_name=index_name,
                    user_id=user_id,
                    tenant_id=tenant_id,
                )
            except ValueError:
                # Knowledge base record not found in the DB - treat as inaccessible.
                logger.warning(
                    "Knowledge base '%s' not found during permission check, skipping",
                    index_name,
                )
                continue
            except Exception as e:
                logger.warning(
                    "Permission check failed for knowledge base '%s': %s", index_name, e
                )
                continue

            if permission is not None:
                accessible.append(index_name)
        return accessible

    @staticmethod
    async def full_delete_knowledge_base(index_name: str, vdb_core: VectorDatabaseCore, user_id: str):
        """
        Completely delete a knowledge base, including its index, associated files in MinIO,
        and all related records in Redis and PostgreSQL.
        """
        logger.debug(
            f"Starting full deletion process for knowledge base (index): {index_name}")

        # Check the durable lifecycle table before mutating any external
        # system.  This closes the race where a processing task can recreate
        # data after the index/source cleanup has started.
        lifecycle_rows = ElasticSearchService._assert_knowledge_base_delete_allowed(index_name)

        lifecycle_fence_cleanup = {"cleared_count": 0, "failed_count": 0}
        try:
            minio_cleanup = await ElasticSearchService._delete_kb_source_objects(
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
                delete_index_result = await ElasticSearchService.delete_index(
                    index_name, vdb_core, user_id
                )
            finally:
                _SKIP_INDEX_SOURCE_CLEANUP.reset(cleanup_token)

            lifecycle_cleanup = {"deleted_count": 0}
            if lifecycle_rows:
                try:
                    lifecycle_cleanup["deleted_count"] = delete_file_records_for_knowledge_base(
                        index_name=index_name,
                    )
                    logger.info(
                        "Deleted %d lifecycle records for knowledge base '%s'",
                        lifecycle_cleanup["deleted_count"],
                        index_name,
                    )
                except Exception as lifecycle_error:
                    logger.error(
                        "Failed to delete lifecycle records for knowledge base '%s': %s",
                        index_name,
                        lifecycle_error,
                        exc_info=True,
                    )
                    lifecycle_cleanup["error"] = str(lifecycle_error)

            # A file deletion request may already have scheduled a local
            # retry task and installed a Redis fence.  The knowledge-base
            # index has now been removed, so those per-file coordinators must
            # not keep retrying against a deleted index or leave stale fences.
            for lifecycle_row in lifecycle_rows:
                file_id = lifecycle_row.get("file_id")
                if not file_id:
                    continue
                pending_delete_task = _document_delete_tasks.pop(str(file_id), None)
                if pending_delete_task and not pending_delete_task.done():
                    pending_delete_task.cancel()
                try:
                    if get_redis_service().clear_document_delete_fence(file_id=file_id):
                        lifecycle_fence_cleanup["cleared_count"] += 1
                except Exception as fence_error:
                    lifecycle_fence_cleanup["failed_count"] += 1
                    logger.warning(
                        "Failed to clear deletion fence for file %s after knowledge-base deletion: %s",
                        file_id,
                        fence_error,
                    )

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
                "redis_cleanup": redis_cleanup_result,
                "lifecycle_cleanup": lifecycle_cleanup,
                "lifecycle_fence_cleanup": lifecycle_fence_cleanup,
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
    def _assert_knowledge_base_delete_allowed(index_name: str) -> List[Dict[str, Any]]:
        """Raise an EDS conflict when files are still being ingested.

        Lifecycle rows are the durable source of truth for this precondition.
        ``DELETE_REQUESTED`` and ``DELETED`` rows are deliberately ignored:
        they are already owned by the deletion path and must not block a
        broader knowledge-base deletion. The rows are returned so the caller
        can clean up lifecycle records after external deletion succeeds.
        """
        try:
            lifecycle_rows = list_file_records(
                index_name=index_name,
                include_hidden=True,
            )
        except Exception as exc:
            logger.exception(
                "Failed to read lifecycle records before deleting knowledge base '%s'",
                index_name,
            )
            raise AppException(
                ErrorCode.SYSTEM_DATABASE_ERROR,
                details={
                    "operation": "knowledge_base_delete_guard",
                    "index_name": index_name,
                },
            ) from exc

        blocking_files = []
        for row in lifecycle_rows:
            status = str(row.get("status") or "").upper()
            if status not in KNOWLEDGE_BASE_DELETE_BLOCKING_STATUSES:
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
            logger.info(
                "Blocking deletion of knowledge base '%s': %d file(s) are still being processed",
                index_name,
                len(blocking_files),
            )
            raise AppException(
                ErrorCode.KNOWLEDGE_DELETE_BLOCKED,
                details={
                    "index_name": index_name,
                    "blocking_files": blocking_files,
                },
            )

        return lifecycle_rows

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
            file_list_result = await ElasticSearchService.list_files(
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

        targets, invalid_entries = ElasticSearchService._collect_kb_source_targets(
            ledger_objects,
            files_to_delete,
        )

        deleted_count = 0
        failed_count = invalid_entries
        for target in targets.values():
            if ElasticSearchService._delete_kb_source_target(
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

            embedding_model = _create_embedding_model(model)
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
                    await ElasticSearchService._delete_kb_source_objects(
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

    @staticmethod
    def _apply_read_only_to_asset_indices_info(result: Dict[str, Any]) -> Dict[str, Any]:
        indices_info = result.get("indices_info")
        if not indices_info:
            return result
        normalized = dict(result)
        normalized["indices_info"] = [
            {**info, "permission": PERMISSION_READ} for info in indices_info
        ]
        return normalized

    @staticmethod
    def merge_list_indices_results(
            primary: Dict[str, Any],
            asset_owner: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Merge non-paginated tenant and asset-owner results."""
        asset_owner = ElasticSearchService._apply_read_only_to_asset_indices_info(asset_owner)
        merged_indices = primary.get("indices", []) + asset_owner.get("indices", [])
        result: Dict[str, Any] = {
            "indices": merged_indices,
            "count": len(merged_indices),
        }
        if "indices_info" in primary or "indices_info" in asset_owner:
            result["indices_info"] = (
                primary.get("indices_info", []) + asset_owner.get("indices_info", [])
            )
        return result

    @staticmethod
    def merge_paginated_list_indices_results(
            primary: Dict[str, Any],
            asset_owner: Dict[str, Any],
            offset: int,
            limit: int,
    ) -> Dict[str, Any]:
        """Merge two database-ordered tenant prefixes and return one global page."""
        asset_owner = ElasticSearchService._apply_read_only_to_asset_indices_info(asset_owner)
        primary_info = primary.get("indices_info", [])
        asset_info = asset_owner.get("indices_info", [])
        combined_info: List[Dict[str, Any]] = []
        primary_index = asset_index = 0

        def sort_key(item: Dict[str, Any]) -> tuple[str, str, str]:
            return (
                str(item.get("update_time") or ""),
                str(item.get("knowledge_id") or "").zfill(20),
                str(item.get("name") or ""),
            )

        while primary_index < len(primary_info) and asset_index < len(asset_info):
            if sort_key(primary_info[primary_index]) >= sort_key(asset_info[asset_index]):
                combined_info.append(primary_info[primary_index])
                primary_index += 1
            else:
                combined_info.append(asset_info[asset_index])
                asset_index += 1
        combined_info.extend(primary_info[primary_index:])
        combined_info.extend(asset_info[asset_index:])

        page_info = combined_info[offset:offset + limit]
        combined_indices = primary.get("indices", []) + asset_owner.get("indices", [])
        page_indices = (
            [item["name"] for item in page_info]
            if combined_info
            else combined_indices[offset:offset + limit]
        )
        total = int(primary.get("total", primary.get("count", 0))) + int(
            asset_owner.get("total", asset_owner.get("count", 0))
        )
        next_offset = offset + len(page_indices)
        source_facets = set(primary.get("facets", {}).get("sources", []))
        source_facets.update(asset_owner.get("facets", {}).get("sources", []))
        model_facets = set(primary.get("facets", {}).get("models", []))
        model_facets.update(asset_owner.get("facets", {}).get("models", []))
        result = {
            "indices": page_indices,
            "count": len(page_indices),
            "total": total,
            "next_offset": next_offset if next_offset < total else None,
            "facets": {
                "sources": sorted(source_facets),
                "models": sorted(model_facets),
            },
            "estimated_row_height": 112,
            "estimated_item_heights": None,
        }
        if "indices_info" in primary or "indices_info" in asset_owner:
            result["indices_info"] = page_info
        return result

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

        visible_knowledgebases, pagination = ElasticSearchService._prepare_indices_page(
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
                    embedding_model_display_name = _get_embedding_model_display_name(model_id, tenant_id)
                    is_multimodal = _is_multimodal_by_model_id(model_id, tenant_id)

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
                    ElasticSearchService.create_index(
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
                    ElasticSearchService._compute_source_available(file_data)
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
    def _preview_pdf_cache_object_name(object_name: str) -> str:
        """Object key for Office-to-PDF preview cache (matches file_management_service)."""
        name_without_ext = (
            object_name.rsplit(".", 1)[0] if "." in object_name else object_name
        )
        hash_suffix = hashlib.md5(object_name.encode()).hexdigest()[:8]
        return f"preview/converted/{name_without_ext}_{hash_suffix}.pdf"

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
            preview_key = ElasticSearchService._preview_pdf_cache_object_name(
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

    @staticmethod
    async def _assert_source_only_deletable(
            index_name: str, path_or_url: str
    ) -> None:
        celery_task_files = await get_all_files_status(index_name)
        status_info = celery_task_files.get(path_or_url)
        if not status_info or not isinstance(status_info, dict):
            return
        state = status_info.get("state") or ""
        if state and state != "COMPLETED":
            raise ValueError(
                f"Cannot delete source file while document is in state '{state}'. "
                "Wait until processing completes or use scope=full to remove the document."
            )

    @staticmethod
    def _mark_file_delete_requested(
            index_name: str,
            path_or_url: str,
            requested_by: Optional[str] = None,
            file_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Install the durable PG/Redis deletion fence before cleanup."""
        try:
            knowledge = get_knowledge_record({"index_name": index_name}) or {}
            tenant_id = knowledge.get("tenant_id")
            knowledge_id = knowledge.get("knowledge_id")
            record = get_file_record(
                file_id=file_id,
                tenant_id=tenant_id,
                index_name=index_name,
                object_name=path_or_url if not file_id else None,
                include_hidden=True,
            )
            if record:
                if str(record.get("status") or "").upper() not in {"DELETE_REQUESTED", "DELETED"}:
                    record = transition_file_record(
                        record["file_id"],
                        status="DELETE_REQUESTED",
                        stage="DELETE",
                        expected_statuses=(
                            "UPLOADING", "UPLOADED", "PROCESSING", "FORWARDING", "FAILED", "COMPLETED"
                        ),
                        updated_by=requested_by,
                    ) or record
            elif tenant_id is not None and knowledge_id is not None:
                record = create_delete_tombstone(
                    tenant_id=str(tenant_id),
                    knowledge_id=int(knowledge_id),
                    index_name=index_name,
                    object_name=path_or_url,
                    requested_by=requested_by,
                    file_id=file_id,
                )

            try:
                fence_ok = get_redis_service().mark_document_delete_requested(
                    file_id=(record or {}).get("file_id") or file_id,
                    requested_by=requested_by,
                )
                if not fence_ok:
                    logger.warning(
                        "Redis deletion fence unavailable; PG status remains the fallback index=%s path=%s",
                        index_name,
                        path_or_url,
                    )
            except Exception as fence_exc:
                logger.warning("Failed to install Redis deletion fence: %s", fence_exc)
            return record
        except Exception as lifecycle_exc:
            logger.warning(
                "Failed to write deletion tombstone for index=%s path=%s: %s",
                index_name,
                path_or_url,
                lifecycle_exc,
            )
            return None

    @staticmethod
    def _mark_file_deleted(
            index_name: str,
            path_or_url: str,
            file_id: Optional[str] = None,
            updated_by: Optional[str] = None,
    ) -> None:
        try:
            knowledge = get_knowledge_record({"index_name": index_name}) or {}
            record = get_file_record(
                file_id=file_id,
                tenant_id=knowledge.get("tenant_id"),
                index_name=index_name,
                object_name=path_or_url if not file_id else None,
                include_hidden=True,
            )
            if record:
                delete_file_record(
                    record["file_id"],
                    expected_statuses=("DELETE_REQUESTED", "DELETED"),
                )
        except Exception as lifecycle_exc:
            logger.warning(
                "Failed to finalize deletion tombstone for index=%s path=%s: %s",
                index_name,
                path_or_url,
                lifecycle_exc,
            )

    @staticmethod
    def _cancel_document_tasks(
            *,
            lifecycle_record: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Revoke the Celery tasks recorded for one lifecycle file."""
        task_ids = {
            lifecycle_record.get(field)
            for field in ("process_task_id", "forward_task_id", "parent_task_id")
            if lifecycle_record and lifecycle_record.get(field)
        }
        file_id = (lifecycle_record or {}).get("file_id")

        try:
            from data_process.app import app as celery_app

            inspector = celery_app.control.inspect(timeout=0.5)
            for method_name in ("active", "reserved"):
                try:
                    workers = getattr(inspector, method_name)() or {}
                except Exception as inspect_exc:
                    logger.debug("Unable to inspect %s Celery tasks: %s", method_name, inspect_exc)
                    continue
                for worker_tasks in workers.values():
                    for task in worker_tasks or []:
                        kwargs = task.get("kwargs") or {}
                        if isinstance(kwargs, str):
                            try:
                                kwargs = json.loads(kwargs)
                            except Exception:
                                kwargs = {}
                        if not isinstance(kwargs, dict):
                            kwargs = {}
                        task_matches = bool(file_id and kwargs.get("file_id") == file_id)
                        if task_matches and task.get("id"):
                            task_ids.add(task["id"])
        except Exception as inspect_exc:
            logger.debug("Celery task inspection unavailable during document deletion: %s", inspect_exc)

        cancelled = []
        redis_service = None
        try:
            redis_service = get_redis_service()
        except Exception:
            pass
        try:
            from data_process.app import app as celery_app
        except Exception:
            celery_app = None
        for task_id in sorted(task_ids):
            if redis_service:
                try:
                    redis_service.mark_task_cancelled(task_id)
                except Exception as cancel_exc:
                    logger.debug("Unable to mark task %s cancelled: %s", task_id, cancel_exc)
            if celery_app:
                try:
                    celery_app.control.revoke(task_id, terminate=False)
                except Exception as revoke_exc:
                    logger.debug("Unable to revoke task %s: %s", task_id, revoke_exc)
            cancelled.append(task_id)
        return {"task_ids": cancelled, "cancelled_count": len(cancelled)}

    @staticmethod
    def _wait_for_document_tasks(
            *,
            index_name: str,
            path_or_url: str,
            lifecycle_record: Dict[str, Any],
            timeout_seconds: float,
            poll_interval_seconds: float = 0.2,
    ) -> bool:
        """Wait for the file's real Celery chain to reach a terminal state.

        The lifecycle row stores the ID returned by
        ``submit_process_forward_chain``.  Waiting on that result is more
        reliable than inspecting only active/reserved workers: a task may be
        queued in the broker or may already have handed work to a chord while
        being absent from both inspection snapshots.
        """
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        task_id = lifecycle_record.get("parent_task_id")
        if not task_id:
            lifecycle_status = str(lifecycle_record.get("status") or "").upper()
            if lifecycle_status in KNOWLEDGE_BASE_DELETE_BLOCKING_STATUSES:
                logger.warning(
                    "Cannot drain file task without parent_task_id status=%s file_id=%s",
                    lifecycle_status,
                    lifecycle_record.get("file_id"),
                )
                return False
            return True

        while True:
            try:
                # The config service does not install Celery. Read the same
                # result-backend record directly instead of importing the
                # data-process Celery application across service boundaries.
                task_data = get_redis_service().backend_client.get(
                    f"celery-task-meta-{task_id}"
                )
                if task_data:
                    if isinstance(task_data, bytes):
                        task_data = task_data.decode("utf-8")
                    task_meta = json.loads(task_data)
                    task_state = str(
                        task_meta.get("status") or task_meta.get("state") or ""
                    ).upper()
                    if task_state in {"SUCCESS", "FAILURE", "REVOKED"}:
                        logger.info(
                            "Celery task chain reached terminal state task_id=%s state=%s",
                            task_id,
                            task_state,
                        )
                        return True
                else:
                    task_state = "PENDING"
                logger.debug(
                    "Waiting for Celery task chain task_id=%s state=%s",
                    task_id,
                    task_state,
                )
            except (TypeError, ValueError, json.JSONDecodeError) as result_exc:
                logger.warning(
                    "Unable to parse Celery task result task_id=%s: %s",
                    task_id,
                    result_exc,
                )
                return False
            except Exception as result_exc:
                logger.warning(
                    "Unable to read Celery task result task_id=%s: %s",
                    task_id,
                    result_exc,
                )
                return False

            if time.monotonic() >= deadline:
                logger.warning(
                    "Timed out waiting for Celery task chain index=%s path=%s task_id=%s",
                    index_name,
                    path_or_url,
                    task_id,
                )
                return False
            time.sleep(max(0.01, float(poll_interval_seconds)))

    @staticmethod
    async def _finalize_document_delete(
            *,
            index_name: str,
            path_or_url: str,
            scope: str,
            vdb_core: VectorDatabaseCore,
            lifecycle_record: Optional[Dict[str, Any]],
            requested_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Finish one deletion after the file task chain has terminated."""
        file_id = (lifecycle_record or {}).get("file_id")
        legacy_mode = lifecycle_record is None or not lifecycle_record.get("object_name")
        if lifecycle_record is None or not lifecycle_record.get("object_name"):
            # A legacy deployment may not have a lifecycle row at all.  Keep
            # the historical path-based delete contract in that case.
            drained = True
        else:
            drained = await asyncio.to_thread(
                ElasticSearchService._wait_for_document_tasks,
                index_name=index_name,
                path_or_url=path_or_url,
                lifecycle_record=lifecycle_record,
                timeout_seconds=DOCUMENT_DELETE_DRAIN_TIMEOUT_S,
            )
            if not drained:
                return {
                    "status": "pending",
                    "scope": scope,
                    "deletion_pending": True,
                    "lifecycle_status": "DELETE_REQUESTED",
                    "source_available": True,
                    "message": "Deletion requested; waiting for Celery tasks to stop.",
                }

        if scope == "source_only":
            try:
                knowledge = get_knowledge_record({"index_name": index_name}) or {}
            except Exception:
                knowledge = {}
            minio_part = ElasticSearchService.delete_source_file(
                path_or_url,
                tenant_id=knowledge.get("tenant_id"),
                updated_by=requested_by,
            )
            result = {
                "status": "success" if minio_part.get("deleted_minio") else "failed",
                "scope": scope,
                "deleted_es_count": 0,
                "deleted_minio": bool(minio_part.get("deleted_minio")),
                "source_available": not bool(minio_part.get("deleted_minio")),
                "message": "Source file deleted; index chunks and vectors preserved.",
            }
        else:
            try:
                result = ElasticSearchService.delete_documents(index_name, path_or_url, vdb_core)
            except Exception as external_exc:
                logger.warning(
                    "External document cleanup failed index=%s path=%s: %s",
                    index_name,
                    path_or_url,
                    external_exc,
                )
                return {
                    "status": "pending",
                    "scope": scope,
                    "deletion_pending": True,
                    "lifecycle_status": "DELETE_REQUESTED",
                    "source_available": True,
                    "external_delete_error": str(external_exc),
                    "message": "Deletion requested; external cleanup will be retried.",
                }
            result["scope"] = scope
            result["source_available"] = not result.get("deleted_minio", False)

        if scope == "full":
            try:
                redis_cleanup = get_redis_service().delete_document_records(index_name, path_or_url)
                result["redis_cleanup"] = redis_cleanup
                if redis_cleanup.get("errors") and not legacy_mode:
                    return {
                        **result,
                        "status": "pending",
                        "deletion_pending": True,
                        "lifecycle_status": "DELETE_REQUESTED",
                        "redis_warnings": redis_cleanup["errors"],
                        "message": "External data deleted; waiting for Redis task cleanup.",
                    }
            except Exception as redis_exc:
                logger.warning("Redis document cleanup failed index=%s path=%s: %s", index_name, path_or_url, redis_exc)
                if not legacy_mode:
                    return {
                        **result,
                        "status": "pending",
                        "deletion_pending": True,
                        "lifecycle_status": "DELETE_REQUESTED",
                        "redis_cleanup_error": str(redis_exc),
                        "message": "External data deleted; waiting for Redis task cleanup.",
                    }

        try:
            if file_id and not legacy_mode:
                delete_file_record(file_id, expected_statuses=("DELETE_REQUESTED", "DELETED"))
            else:
                if requested_by is None:
                    ElasticSearchService._mark_file_deleted(index_name, path_or_url)
                else:
                    ElasticSearchService._mark_file_deleted(
                        index_name, path_or_url, updated_by=requested_by
                    )
        except Exception as lifecycle_exc:
            logger.warning(
                "Lifecycle hard delete failed index=%s path=%s file_id=%s: %s",
                index_name,
                path_or_url,
                file_id,
                lifecycle_exc,
            )
            return {
                **result,
                "status": "pending",
                "deletion_pending": True,
                "lifecycle_status": "DELETE_REQUESTED",
                "lifecycle_delete_error": str(lifecycle_exc),
                "message": "External data deleted; waiting for lifecycle cleanup.",
            }
        try:
            fence_service = get_redis_service()
            fence_service.clear_document_delete_fence(
                file_id=file_id,
            )
            if fence_service.is_document_delete_requested(
                file_id=file_id,
            ):
                if not legacy_mode:
                    return {
                        **result,
                        "status": "pending",
                        "deletion_pending": True,
                        "lifecycle_status": "DELETE_REQUESTED",
                        "message": "External data deleted; waiting for deletion fence cleanup.",
                    }
        except Exception as fence_exc:
            logger.warning("Failed to clear deletion fence index=%s path=%s: %s", index_name, path_or_url, fence_exc)
            if not legacy_mode:
                return {
                    **result,
                    "status": "pending",
                    "deletion_pending": True,
                    "lifecycle_status": "DELETE_REQUESTED",
                    "fence_cleanup_error": str(fence_exc),
                    "message": "External data deleted; waiting for deletion fence cleanup.",
                }
        result["lifecycle_deleted"] = True
        return result

    @staticmethod
    async def _retry_document_delete(
            *,
            index_name: str,
            path_or_url: str,
            scope: str,
            vdb_core: VectorDatabaseCore,
            lifecycle_record: Optional[Dict[str, Any]],
            requested_by: Optional[str] = None,
    ) -> None:
        file_id = (lifecycle_record or {}).get("file_id") or path_or_url
        try:
            while True:
                try:
                    result = await ElasticSearchService._finalize_document_delete(
                        index_name=index_name,
                        path_or_url=path_or_url,
                        scope=scope,
                        vdb_core=vdb_core,
                        lifecycle_record=lifecycle_record,
                        requested_by=requested_by,
                    )
                    if result.get("status") != "pending":
                        return
                except Exception as exc:
                    # External dependencies can be temporarily unavailable.
                    # Keep the durable row/fence and retry instead of
                    # abandoning the deletion.
                    logger.warning(
                        "Background deletion finalizer iteration failed for index=%s path=%s: %s",
                        index_name,
                        path_or_url,
                        exc,
                    )
                await asyncio.sleep(max(0.2, DOCUMENT_DELETE_RETRY_INTERVAL_S))
        except asyncio.CancelledError:
            raise
        finally:
            _document_delete_tasks.pop(str(file_id), None)

    @staticmethod
    def _schedule_document_delete_retry(
            *,
            index_name: str,
            path_or_url: str,
            scope: str,
            vdb_core: VectorDatabaseCore,
            lifecycle_record: Optional[Dict[str, Any]],
            requested_by: Optional[str] = None,
    ) -> None:
        key = str((lifecycle_record or {}).get("file_id") or path_or_url)
        existing = _document_delete_tasks.get(key)
        if existing and not existing.done():
            return
        _document_delete_tasks[key] = asyncio.create_task(
            ElasticSearchService._retry_document_delete(
                index_name=index_name,
                path_or_url=path_or_url,
                scope=scope,
                vdb_core=vdb_core,
                lifecycle_record=lifecycle_record,
                requested_by=requested_by,
            )
        )

    @staticmethod
    def delete_lifecycle_record_without_object(
            lifecycle_record: Dict[str, Any],
            requested_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Delete a lifecycle row when no storage object was ever created."""
        file_id = lifecycle_record.get("file_id") if lifecycle_record else None
        object_name = lifecycle_record.get("object_name") if lifecycle_record else None
        if not file_id or object_name:
            raise ValueError("A lifecycle file ID without an object path is required")

        tenant_id = lifecycle_record.get("tenant_id")
        index_name = lifecycle_record.get("index_name")
        current_status = str(lifecycle_record.get("status") or "").upper()
        try:
            get_redis_service().mark_document_delete_requested(
                file_id=file_id,
                requested_by=requested_by,
            )
        except Exception as fence_exc:
            logger.debug("Unable to install no-object deletion fence for %s: %s", file_id, fence_exc)
        try:
            ElasticSearchService._cancel_document_tasks(
                lifecycle_record=lifecycle_record,
            )
        except Exception as cancel_exc:
            logger.debug("Unable to cancel no-object deletion tasks for %s: %s", file_id, cancel_exc)
        deleteable_statuses = (
            "UPLOADING",
            "UPLOADED",
            "PROCESSING",
            "FORWARDING",
            "FAILED",
            "COMPLETED",
        )

        if current_status == "DELETED":
            delete_file_record(file_id, expected_statuses=("DELETE_REQUESTED", "DELETED"))
            try:
                get_redis_service().clear_document_delete_fence(
                    file_id=file_id,
                )
            except Exception:
                pass
            return {
                "status": "success",
                "scope": "full",
                "deleted_es_count": 0,
                "deleted_minio": False,
                "source_available": False,
                "lifecycle_deleted": True,
                "message": "Lifecycle record already deleted; no storage object was created.",
            }

        if current_status != "DELETE_REQUESTED":
            requested = transition_file_record(
                file_id,
                status="DELETE_REQUESTED",
                stage="DELETE",
                expected_statuses=deleteable_statuses,
                updated_by=requested_by,
            )
            if requested is None:
                latest = get_file_record(
                    file_id=file_id,
                    tenant_id=tenant_id,
                    index_name=index_name,
                    include_hidden=True,
                )
                if latest and str(latest.get("status") or "").upper() == "DELETED":
                    current_status = "DELETED"
                elif latest and str(latest.get("status") or "").upper() == "DELETE_REQUESTED":
                    current_status = "DELETE_REQUESTED"
                else:
                    raise ValueError("Lifecycle file record could not be deleted")

        deleted = delete_file_record(
            file_id,
            expected_statuses=("DELETE_REQUESTED", "DELETED"),
        )
        if not deleted:
            latest = get_file_record(
                file_id=file_id,
                tenant_id=tenant_id,
                index_name=index_name,
                include_hidden=True,
            )
            if latest is not None:
                raise ValueError("Lifecycle file record could not be finalized")

        try:
            get_redis_service().clear_document_delete_fence(
                file_id=file_id,
            )
        except Exception:
            logger.debug("Unable to clear no-object deletion fence for %s", file_id)

        return {
            "status": "success",
            "scope": "full",
            "deleted_es_count": 0,
            "deleted_minio": False,
            "source_available": False,
            "lifecycle_deleted": True,
            "message": "Lifecycle record deleted; no storage object was created.",
        }

    @staticmethod
    async def delete_document_by_scope(
            index_name: str,
            path_or_url: str,
            scope: str,
            vdb_core: VectorDatabaseCore,
            file_id: Optional[str] = None,
            requested_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        if scope not in ElasticSearchService.DOCUMENT_DELETE_SCOPES:
            raise ValueError(
                f"Invalid scope '{scope}'. "
                f"Must be one of: {ElasticSearchService.DOCUMENT_DELETE_SCOPES}"
            )

        if scope == "source_only":
            await ElasticSearchService._assert_source_only_deletable(
                index_name, path_or_url
            )
        if file_id is None and requested_by is None:
            lifecycle_record = ElasticSearchService._mark_file_delete_requested(
                index_name,
                path_or_url,
            )
        else:
            lifecycle_record = ElasticSearchService._mark_file_delete_requested(
                index_name,
                path_or_url,
                requested_by=requested_by,
                file_id=file_id,
            )
        cancellation = ElasticSearchService._cancel_document_tasks(
            lifecycle_record=lifecycle_record,
        )
        result = await ElasticSearchService._finalize_document_delete(
            index_name=index_name,
            path_or_url=path_or_url,
            scope=scope,
            vdb_core=vdb_core,
            lifecycle_record=lifecycle_record,
            requested_by=requested_by,
        )
        result["cancelled_tasks"] = cancellation
        if result.get("status") == "pending":
            ElasticSearchService._schedule_document_delete_retry(
                index_name=index_name,
                path_or_url=path_or_url,
                scope=scope,
                vdb_core=vdb_core,
                lifecycle_record=lifecycle_record,
                requested_by=requested_by,
            )
        return result

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
        if minio_result.get("success"):
            try:
                knowledge = get_knowledge_record({"index_name": index_name}) or {}
                tenant_id = knowledge.get("tenant_id")
                reference = resolve_storage_reference(path_or_url)
                if tenant_id and reference:
                    release_storage_charge(
                        tenant_id=tenant_id,
                        bucket_name=reference.bucket_name,
                        object_name=reference.object_name,
                    )
            except Exception:
                logger.exception(
                    "Failed to reconcile storage ledger after deleting '%s'",
                    path_or_url,
                )

        # Update last_doc_update_time for auto-summary tracking
        update_last_doc_update_time(index_name)

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
            # Update last_summary_time for auto-summary tracking
            update_last_summary_time(index_name)
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
            # Get knowledge base's embedding model by model_id
            embedding_model_id = None
            if tenant_id:
                try:
                    knowledge_record = get_knowledge_record({
                        "index_name": index_name,
                        "tenant_id": tenant_id
                    })
                    embedding_model_id = knowledge_record.get("embedding_model_id") if knowledge_record else None
                except Exception as e:
                    logger.warning(f"Failed to get embedding model id for index {index_name}: {e}")

            # Generate embedding if we have content and can get embedding model
            embedding_vector = None
            if chunk_request.content:
                try:
                    embedding_model = get_embedding_model_by_id(tenant_id, embedding_model_id)[0] if tenant_id and embedding_model_id else None
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
                if embedding_model_id:
                    chunk_payload["embedding_model_id"] = embedding_model_id

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
        tenant_id: Optional[str] = None,
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
                    "update_time": datetime.now(timezone.utc).strftime(
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
            weight_accurate: Optional[float] = None,
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
            if weight_accurate and (
                weight_accurate < 0 or weight_accurate > 1
            ):
                raise ValueError("weight_accurate must be between 0 and 1")

            # Preserve the REST API's historical 0.5 default for ordinary
            # queries. When the caller has not supplied a preference, give
            # digit-containing identifiers more accurate-search influence.
            effective_weight_accurate = weight_accurate
            if effective_weight_accurate is None:
                effective_weight_accurate = (
                    0.7 if any(char.isdigit() for char in query) else 0.5
                )

            # Get embedding model from the first index's knowledge base record
            if not index_names:
                raise ValueError("At least one index name is required")

            embedding_model, model_id, meta = get_embedding_model_by_index_name(tenant_id, index_names[0])

            if not embedding_model:
                if meta.get("status") == "needs_config":
                    # Return a clear error indicating model needs to be configured
                    raise KnowledgeBaseNeedsModelConfigError(
                        index_name=index_names[0],
                        message=f"Knowledge base '{index_names[0]}' does not have an embedding model configured. Please select a model in the knowledge base settings."
                    )
                else:
                    raise ValueError(
                        f"No embedding model found for index '{index_names[0]}'. "
                        f"Please configure an embedding model for this knowledge base.")

            start_time = time.perf_counter()
            raw_results = vdb_core.hybrid_search(
                index_names=index_names,
                query_text=query,
                embedding_model=embedding_model,
                top_k=top_k,
                weight_accurate=effective_weight_accurate,
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
        except KnowledgeBaseNeedsModelConfigError:
            raise
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
            payload["create_time"] = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S")

        return payload
