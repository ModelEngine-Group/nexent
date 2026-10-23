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
import json
import logging
from contextvars import ContextVar
from typing import Any, Optional

from nexent.vector_database.base import VectorDatabaseCore
from nexent.vector_database.elasticsearch_core import ElasticSearchCore
from nexent.vector_database.datamate_core import DataMateCore

from consts.const import (
    DATAMATE_URL,
    ES_API_KEY,
    ES_HOST,
    VectorDatabaseType,
)
from database.knowledge_db import (
    get_knowledge_record,
)
from services.redis_service import get_redis_service
from utils.config_utils import tenant_config_manager
from management.services.model.resolver import (
    get_embedding_model_by_id,
)


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
