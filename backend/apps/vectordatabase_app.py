import logging
import json
from http import HTTPStatus
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Path, Query
from fastapi.responses import JSONResponse
import re

from consts.const import ASSET_OWNER_TENANT_ID
from consts.error_code import ErrorCode
from consts.exceptions import (
    AppException,
    DuplicateError,
    TokenExpiredError,
)
from consts.model import ChunkCreateRequest, ChunkUpdateRequest, HybridSearchRequest, IndexingResponse
from consts.scheduler import VALID_SUMMARY_FREQUENCIES, SUMMARY_FREQUENCY_OPTIONS_FOR_API
from nexent.vector_database.base import VectorDatabaseCore
from management.services.model.resolver import get_embedding_model_by_id
from management.services.knowledge_base.service import (
    ElasticSearchService,
    get_vector_db_core,
    check_knowledge_base_exist_impl,
    KnowledgeBaseNeedsModelConfigError,
)
from services.file_management_service import check_file_access
from services.quota_service import QuotaService
from services.redis_service import get_redis_service
from utils.auth_utils import get_current_user_context, get_current_user_id
from utils.file_management_utils import get_all_files_status
from database.knowledge_db import get_index_name_by_knowledge_name, get_knowledge_record
from database.model_management_db import get_model_by_model_id
from apps.permission_utils import (
    require_knowledge_base_edit_permission,
    require_knowledge_base_read_permission,
)

router = APIRouter(prefix="/indices")
service = ElasticSearchService()
logger = logging.getLogger("vectordatabase_app")

INTERNAL_INDEX_NAME_DESC = "Internal index_name from knowledge_record_t"


@router.get("/summary_frequency_options")
async def get_summary_frequency_options():
    """
    Get valid summary frequency options for frontend.
    Frontend should call this API to get the list of valid frequencies.
    """
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={
            "options": SUMMARY_FREQUENCY_OPTIONS_FOR_API,
            "valid_values": VALID_SUMMARY_FREQUENCIES,
        }
    )


@router.post("/check_exist")
async def check_knowledge_base_exist(
        request: Dict[str, str] = Body(
            ..., description="Request body containing knowledge base name"),
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
        authorization: Optional[str] = Header(None)
):
    """Check if a knowledge base name exists in the current tenant."""
    try:
        knowledge_name = request.get("knowledge_name", "")
        if not knowledge_name:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST, detail="Knowledge base name is required")

        user_id, tenant_id = get_current_user_id(authorization)
        return check_knowledge_base_exist_impl(knowledge_name=knowledge_name, vdb_core=vdb_core, user_id=user_id, tenant_id=tenant_id)
    except TokenExpiredError as e:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logger.error(
            f"Error checking knowledge base existence for '{knowledge_name}': {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error checking existence for knowledge base: {str(e)}")


@router.post("/{index_name}")
def create_new_index(
        index_name: str = Path(..., description="Name of the index to create"),
        embedding_dim: Optional[int] = Query(
            None, description="Dimension of the embedding vectors"),
        request: Dict[str, Any] = Body(
            None, description="Request body containing embedding_model_id and optional knowledge-base settings"),
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
        authorization: Optional[str] = Header(None)
):
    """Create a new vector index and store it in the knowledge table"""
    try:
        user_id, tenant_id, user_role = get_current_user_context(authorization)

        # Extract optional fields from request body
        ingroup_permission = None
        group_ids = None
        embedding_model_id: Optional[int] = None
        preserve_source_file: Optional[bool] = None
        quota_limit_bytes: Optional[int] = None
        if request:
            ingroup_permission = request.get("ingroup_permission")
            group_ids = request.get("group_ids")
            embedding_model_id = request.get("embedding_model_id")
            preserve_source_file = request.get("preserve_source_file")
            quota_limit_bytes = request.get("quota_limit_bytes")

        if isinstance(embedding_model_id, bool) or not isinstance(embedding_model_id, int):
            raise ValueError("embedding_model_id must be an integer")

        # Treat path parameter as user-facing knowledge base name for new creations
        return ElasticSearchService.create_knowledge_base(
            knowledge_name=index_name,
            embedding_dim=embedding_dim,
            vdb_core=vdb_core,
            user_id=user_id,
            tenant_id=tenant_id,
            ingroup_permission=ingroup_permission,
            group_ids=group_ids,
            embedding_model_id=embedding_model_id,
            preserve_source_file=preserve_source_file,
            quota_limit_bytes=quota_limit_bytes,
            user_role=user_role,
        )
    except HTTPException:
        raise
    except DuplicateError as e:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail=str(e),
        ) from e
    except (TypeError, ValueError) as e:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except TokenExpiredError as e:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error creating index: {str(e)}")


@router.delete("/{index_name}")
async def delete_index(
        index_name: str = Path(..., description="Name of the index to delete"),
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
        authorization: Optional[str] = Header(None)
):
    """Delete an index and all its related data by calling the centralized service."""
    logger.debug(f"Received request to delete knowledge base: {index_name}")
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        require_knowledge_base_edit_permission(index_name, user_id, tenant_id)
        # Call the centralized full deletion service
        result = await ElasticSearchService.full_delete_knowledge_base(index_name, vdb_core, user_id)
        return result
    except HTTPException:
        raise
    except TokenExpiredError as e:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logger.error(
            f"Error during API call to delete index '{index_name}': {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error deleting index: {str(e)}")


@router.patch("/{index_name}")
async def update_index(
        index_name: str = Path(..., description="Name of the index to update"),
        request: Dict[str, Any] = Body(...,
                                       description="Update payload with knowledge_name, ingroup_permission, group_ids, and/or tenant_id"),
        authorization: Optional[str] = Header(None)
):
    """Update knowledge base information (name, group permission, group assignments)."""
    try:
        user_id, auth_tenant_id, user_role = get_current_user_context(authorization)
        # Use explicit tenant_id if provided, otherwise fall back to auth tenant_id
        tenant_id = request.get("tenant_id") or auth_tenant_id
        require_knowledge_base_edit_permission(index_name, user_id, auth_tenant_id)

        # Extract update fields
        knowledge_name = request.get("knowledge_name")
        ingroup_permission = request.get("ingroup_permission")
        group_ids = request.get("group_ids")
        # Call service layer to update knowledge base
        update_kwargs = {
            "index_name": index_name,
            "knowledge_name": knowledge_name,
            "ingroup_permission": ingroup_permission,
            "group_ids": group_ids,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "user_role": user_role,
        }
        if "quota_limit_bytes" in request:
            update_kwargs["quota_limit_bytes"] = request["quota_limit_bytes"]

        result = ElasticSearchService.update_knowledge_base(**update_kwargs)

        if result:
            return JSONResponse(
                status_code=HTTPStatus.OK,
                content={
                    "message": "Knowledge base updated successfully", "status": "success"}
            )
        else:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail=f"Knowledge base '{index_name}' not found"
            )
    except ValueError as exc:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(exc)
        )
    except HTTPException:
        raise
    except TokenExpiredError as exc:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc))
    except Exception as exc:
        logger.error(
            f"Error updating index '{index_name}': {str(exc)}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error updating index: {str(exc)}")


@router.patch("/{index_name}/summary_frequency")
async def update_summary_frequency_endpoint(
        index_name: Annotated[str, Path(..., description="Name of the index to update")],
        request: Annotated[Dict[str, Any], Body(..., description="Update payload with summary_frequency")],
        authorization: Annotated[Optional[str], Header()] = None,
):
    """Update the auto-summary frequency for a knowledge base."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        require_knowledge_base_edit_permission(index_name, user_id, tenant_id)
        summary_frequency = request.get("summary_frequency")

        valid_frequencies = VALID_SUMMARY_FREQUENCIES
        if summary_frequency not in valid_frequencies:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail=f"Invalid summary_frequency. Must be one of: {valid_frequencies}"
            )

        from database.knowledge_db import update_summary_frequency
        success = update_summary_frequency(
            index_name=index_name,
            summary_frequency=summary_frequency,
            _tenant_id=tenant_id,
            user_id=user_id
        )

        if success:
            return JSONResponse(
                status_code=HTTPStatus.OK,
                content={
                    "message": "Summary frequency updated successfully", "status": "success"}
            )
        else:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail=f"Knowledge base '{index_name}' not found"
            )
    except HTTPException:
        raise
    except TokenExpiredError as exc:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc))
    except Exception as exc:
        logger.exception("Error updating summary frequency")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error updating summary frequency: {str(exc)}"
        )


@router.get("/{index_name}/embedding-model-status")
def get_embedding_model_status(
        index_name: str = Path(..., description="Name of the index to check"),
        authorization: Optional[str] = Header(None)
):
    """
    Check the embedding model status of a knowledge base.
    Returns information about whether a model is configured and if an update is needed.

    This endpoint is used by the frontend to determine whether to show
    a dialog prompting the user to select an embedding model for knowledge bases
    that were created before the model ID feature was added.

    Note: The path parameter is the internal index_name.
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        require_knowledge_base_read_permission(index_name, user_id, tenant_id)

        # Get the knowledge base record by index_name
        knowledge_record = get_knowledge_record({
            "index_name": index_name,
            "tenant_id": tenant_id,
            "include_asset_owner_assets": True,
        })

        if not knowledge_record:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail=f"Knowledge base '{index_name}' not found"
            )

        # Check if model_id exists
        model_id = knowledge_record.get("embedding_model_id")
        embedding_model_name = knowledge_record.get("embedding_model_name")

        # Get model info if model_id exists
        model_info = None
        if model_id:
            model = get_model_by_model_id(model_id, tenant_id)
            if model:
                model_info = {
                    "model_id": model.get("model_id"),
                    "model_name": model.get("model_name"),
                    "display_name": model.get("display_name"),
                    "model_type": model.get("model_type"),
                }

        # Determine status
        if model_id and model_info:
            status = "configured"
            message = f"Embedding model '{model_info.get('display_name', model_info.get('model_name'))}' is configured"
            needs_config = False
        elif embedding_model_name:
            # Has model name but no model_id (legacy data)
            status = "legacy"
            message = "This knowledge base was created with an older version. Please select an embedding model to ensure proper functionality."
            needs_config = True
        else:
            # No model configured at all
            status = "missing"
            message = "No embedding model configured. Please select an embedding model."
            needs_config = True

        # Get actual internal index_name from the database record
        actual_index_name = knowledge_record.get("index_name")

        return {
            "status": status,
            "needs_config": needs_config,
            "index_name": actual_index_name,
            "knowledge_name": knowledge_record.get("knowledge_name"),
            "model_id": model_id,
            "embedding_model_name": embedding_model_name,
            "model_info": model_info,
            "message": message,
        }

    except HTTPException:
        raise
    except TokenExpiredError as e:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logger.error(
            f"Error getting embedding model status for '{index_name}': {e}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error checking embedding model status: {str(e)}"
        )


@router.put("/{index_name}/embedding-model")
def update_embedding_model(
        index_name: str = Path(
            ..., description="Internal index name of the knowledge base to update"),
        request: Dict[str, Any] = Body(...,
                                       description="Update payload with model_id"),
        authorization: Optional[str] = Header(None)
):
    """
    Update the embedding model for a knowledge base.
    This is used when a user selects an embedding model from the dialog
    for knowledge bases that don't have a model configured.
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        require_knowledge_base_edit_permission(index_name, user_id, tenant_id)

        model_id = request.get("model_id")
        if not model_id:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="model_id is required"
            )

        result = ElasticSearchService.update_embedding_model(
            index_name=index_name,
            model_id=model_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )

        return JSONResponse(
            status_code=HTTPStatus.OK,
            content=result
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(exc)
        )
    except HTTPException:
        raise
    except TokenExpiredError as exc:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc))
    except Exception as exc:
        logger.error(
            f"Error updating embedding model for '{index_name}': {exc}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error updating embedding model: {str(exc)}"
        )


@router.get("")
def get_list_indices(
        pattern: str = Query("*", description="Pattern to match index names"),
        include_stats: bool = Query(
            False, description="Whether to include index stats"),
        tenant_id: Optional[str] = Query(
            None, description="Tenant ID for filtering (uses auth if not provided)"),
        offset: int = Query(0, ge=0, description="Number of visible knowledge bases to skip"),
        limit: Optional[int] = Query(None, ge=1, le=100, description="Maximum knowledge bases to return"),
        keyword: Optional[str] = Query(None, description="Search knowledge base name and description"),
        sources: Optional[List[str]] = Query(None, description="Knowledge base sources to include"),
        models: Optional[List[str]] = Query(None, description="Embedding model names to include"),
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
        authorization: Optional[str] = Header(None),
):
    """List all user indices with optional stats"""
    try:
        user_id, auth_tenant_id = get_current_user_id(authorization)
        pagination_enabled = limit is not None
        pagination_args = {}
        if limit is not None or keyword or sources or models:
            pagination_args = {
                "pagination_enabled": pagination_enabled,
                "offset": offset,
                "limit": limit,
                "keyword": keyword,
                "sources": sources,
                "models": models,
            }
        if tenant_id is None:
            if limit is not None and auth_tenant_id != ASSET_OWNER_TENANT_ID:
                prefix_limit = offset + limit
                result = ElasticSearchService.list_indices(
                    pattern, include_stats, auth_tenant_id, user_id, vdb_core,
                    pagination_enabled=True, offset=0, limit=prefix_limit,
                    keyword=keyword, sources=sources, models=models,
                )
                asset_result = ElasticSearchService.list_indices(
                    pattern, include_stats, ASSET_OWNER_TENANT_ID, user_id, vdb_core,
                    pagination_enabled=True, offset=0, limit=prefix_limit,
                    keyword=keyword, sources=sources, models=models,
                )
                return ElasticSearchService.merge_paginated_list_indices_results(
                    result, asset_result, offset, limit
                )
            result = ElasticSearchService.list_indices(
                pattern, include_stats, auth_tenant_id, user_id, vdb_core, **pagination_args
            )
            if auth_tenant_id != ASSET_OWNER_TENANT_ID:
                asset_result = ElasticSearchService.list_indices(
                    pattern, include_stats, ASSET_OWNER_TENANT_ID, user_id, vdb_core, **pagination_args
                )
                return ElasticSearchService.merge_list_indices_results(
                    result, asset_result
                )
            return result
        return ElasticSearchService.list_indices(
            pattern, include_stats, tenant_id, user_id, vdb_core, **pagination_args
        )
    except TokenExpiredError as e:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error get index: {str(e)}")


# Document Operations


def _check_personal_kb_quota_before_indexing(
    data: List[Dict[str, Any]],
    knowledge_record: Optional[Dict[str, Any]],
    tenant_id: str,
    user_id: str,
) -> None:
    """Validate personal quota before indexing documents into a private KB."""
    if not knowledge_record or knowledge_record.get("ingroup_permission") != "PRIVATE":
        return

    try:
        quota_service = QuotaService(tenant_id, user_id)
        quota_service.check_personal_kb_quota(
            user_id,
            quota_service.get_pending_personal_upload_bytes(
                data, knowledge_record
            ),
            kb_record=knowledge_record,
        )
    except AppException:
        raise
    except Exception as exc:
        logger.exception("Personal KB quota check failed")
        raise AppException(
            ErrorCode.TENANT_PERSONAL_KB_QUOTA_UNAVAILABLE,
            f"Personal KB quota service unavailable: {str(exc)}",
        ) from exc


@router.post("/{index_name}/documents", response_model=IndexingResponse)
def create_index_documents(
        index_name: str = Path(..., description="Name of the index"),
        data: List[Dict[str, Any]
                   ] = Body(..., description="Document List to process"),
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
        authorization: Optional[str] = Header(None),
        task_id: Optional[str] = Header(
            None, alias="X-Task-Id", description="Task ID for progress tracking"),
        large_mode: bool = Query(
            False, description="Force large-batch path when current request chunk count is below threshold"),
):
    """
    Index documents with embeddings, creating the index if it doesn't exist.
    Accepts a document list from data processing.
    """
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        require_knowledge_base_edit_permission(index_name, user_id, tenant_id)

        # Get the knowledge base record to retrieve the saved embedding model
        knowledge_record = get_knowledge_record({'index_name': index_name})
        saved_embedding_model_id = None
        if knowledge_record:
            saved_embedding_model_id = knowledge_record.get(
                'embedding_model_id')

        _check_personal_kb_quota_before_indexing(
            data,
            knowledge_record,
            tenant_id,
            user_id,
        )

        # Use the saved model from knowledge base by model_id
        embedding_model, _ = get_embedding_model_by_id(
            tenant_id, saved_embedding_model_id) if saved_embedding_model_id else (None, None)

        return ElasticSearchService.index_documents(
            embedding_model=embedding_model,
            index_name=index_name,
            data=data,
            vdb_core=vdb_core,
            task_id=task_id,
            large_mode=large_mode,
            model_id=saved_embedding_model_id,
        )
    except AppException:
        raise
    except HTTPException:
        raise
    except TokenExpiredError as e:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error indexing documents: {error_msg}")

        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error indexing documents: {error_msg}"
        )


@router.get("/{index_name}/files")
async def get_index_files(
        index_name: str = Path(..., description="Name of the index"),
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
        authorization: Optional[str] = Header(None),
):
    """Get all files from an index, including those that are not yet stored in ES"""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        require_knowledge_base_read_permission(index_name, user_id, tenant_id)
        result = await ElasticSearchService.list_files(index_name, include_chunks=False, vdb_core=vdb_core)
        # Transform result to match frontend expectations
        return {
            "status": "success",
            "files": result.get("files", [])
        }
    except HTTPException:
        raise
    except TokenExpiredError as e:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error indexing documents: {error_msg}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error indexing documents: {error_msg}")


@router.delete("/{index_name}/documents")
async def delete_documents(
        index_name: str = Path(..., description="Name of the index"),
        path_or_url: Optional[str] = Query(None,
                                           description="Legacy object path to delete"),
        file_id: Optional[str] = Query(
            None, description="Durable lifecycle file ID (preferred for new clients)"),
        scope: str = Query(
            "full",
            description=(
                "source_only: delete MinIO source only, keep ES chunks/vectors; "
                "full: delete ES documents, MinIO source, and Redis task records"
            ),
        ),
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
        authorization: Optional[str] = Header(None),
):
    """Delete a document by scope: source file only or full removal from the index."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        require_knowledge_base_edit_permission(index_name, user_id, tenant_id)
        if file_id:
            try:
                from database.knowledge_file_lifecycle_db import get_file_record

                lifecycle_record = get_file_record(
                    file_id=file_id,
                    index_name=index_name,
                    tenant_id=tenant_id,
                    include_hidden=True,
                )
            except Exception as lifecycle_exc:
                logger.warning("Lifecycle file ID lookup unavailable: %s", lifecycle_exc)
                lifecycle_record = None
            if lifecycle_record and lifecycle_record.get("object_name"):
                path_or_url = lifecycle_record["object_name"]
            elif lifecycle_record and not lifecycle_record.get("object_name"):
                if scope != "full":
                    raise HTTPException(
                        status_code=HTTPStatus.BAD_REQUEST,
                        detail="A file without a storage object can only use full deletion",
                    )
                return ElasticSearchService.delete_lifecycle_record_without_object(
                    lifecycle_record,
                    requested_by=user_id,
                )
        if not path_or_url:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="Either path_or_url or file_id is required",
            )
        result = await ElasticSearchService.delete_document_by_scope(
            index_name, path_or_url, scope, vdb_core
        )

        if scope == "full":
            try:
                redis_service = get_redis_service()
                redis_cleanup_result = redis_service.delete_document_records(
                    index_name, path_or_url
                )
                result["redis_cleanup"] = redis_cleanup_result
                original_message = result.get(
                    "message", "Documents deleted successfully"
                )
                result["message"] = (
                    f"{original_message}. "
                    f"Cleaned up {redis_cleanup_result['total_deleted']} Redis records "
                    f"({redis_cleanup_result['celery_tasks_deleted']} tasks, "
                    f"{redis_cleanup_result['cache_keys_deleted']} cache keys)."
                )
                if redis_cleanup_result.get("errors"):
                    result["redis_warnings"] = redis_cleanup_result["errors"]
            except Exception as redis_error:
                logger.warning(
                    "Redis cleanup failed for document %s in index %s: %s",
                    path_or_url,
                    index_name,
                    redis_error,
                )
                result["redis_cleanup_error"] = str(redis_error)
                original_message = result.get(
                    "message", "Documents deleted successfully"
                )
                result["message"] = (
                    f"{original_message}, but Redis cleanup encountered an error: "
                    f"{str(redis_error)}"
                )

        return result

    except ValueError as exc:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail=str(exc)
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail=str(exc)
        )
    except HTTPException:
        raise
    except TokenExpiredError as e:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error delete indexing documents: {e}",
        )


@router.get("/{index_name}/documents/{path_or_url:path}/error-info")
async def get_document_error_info(
        index_name: str = Path(..., description="Name of the index"),
        path_or_url: str = Path(...,
                                description="Path or URL of the document"),
        file_id: Optional[str] = Query(None, description="Durable lifecycle file ID"),
        authorization: Optional[str] = Header(None)
):
    """Get error information for a document"""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        require_knowledge_base_read_permission(index_name, user_id, tenant_id)
        try:
            from database.knowledge_file_lifecycle_db import get_file_record

            lifecycle_record = get_file_record(
                file_id=file_id,
                index_name=index_name,
                tenant_id=tenant_id,
                object_name=None if file_id else path_or_url,
                include_hidden=True,
            )
        except Exception as lifecycle_exc:
            logger.warning("Lifecycle error lookup unavailable: %s", lifecycle_exc)
            lifecycle_record = None
        lifecycle_has_error = bool(
            lifecycle_record
            and any(
                lifecycle_record.get(field)
                for field in ("error_code", "error_message", "error_stage", "failed_at")
            )
        )
        lifecycle_stage = (
            (lifecycle_record.get("error_stage") or lifecycle_record.get("stage"))
            if lifecycle_record
            else None
        )
        if lifecycle_has_error:
            return {
                "status": "success",
                "error_code": lifecycle_record.get("error_code"),
                "error_message": lifecycle_record.get("error_message"),
                "error_stage": lifecycle_record.get("error_stage") or lifecycle_record.get("stage"),
                "failed_at": lifecycle_record.get("failed_at"),
            }
        celery_task_files = await get_all_files_status(index_name)
        file_status = celery_task_files.get(path_or_url)

        if not file_status:
            if lifecycle_record:
                return {
                    "status": "success",
                    "error_code": None,
                    "error_message": None,
                    "error_stage": lifecycle_stage,
                    "failed_at": lifecycle_record.get("failed_at") if lifecycle_record else None,
                }
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail=f"Document {path_or_url} not found in index {index_name}"
            )

        task_id = file_status.get('latest_task_id', '')
        if not task_id:
            return {
                "status": "success",
                "error_code": None,
                "error_message": None,
                "error_stage": lifecycle_stage,
                "failed_at": lifecycle_record.get("failed_at") if lifecycle_record else None,
            }

        redis_service = get_redis_service()
        raw_error = redis_service.get_error_info(task_id)
        error_code = None

        if raw_error:
            # Try to parse JSON (new format with error_code only)
            try:
                parsed = json.loads(raw_error)
                if isinstance(parsed, dict) and "error_code" in parsed:
                    error_code = parsed.get("error_code")
            except Exception:
                # Fallback: regex extraction if JSON parsing fails
                try:
                    match = re.search(
                        r'["\']error_code["\']\s*:\s*["\']([^"\']+)["\']', raw_error)
                    if match:
                        error_code = match.group(1)
                except Exception:
                    pass

        return {
            "status": "success",
            "error_code": error_code,
            "error_message": raw_error,
            "error_stage": file_status.get("stage") or lifecycle_stage,
            "failed_at": lifecycle_record.get("failed_at") if lifecycle_record else None,
        }
    except HTTPException:
        raise
    except TokenExpiredError as e:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logger.error(
            f"Error getting error info for document {path_or_url}: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error getting error info: {str(e)}"
        )


# Health check
@router.get("/health")
def health_check(vdb_core: VectorDatabaseCore = Depends(get_vector_db_core)):
    """Check API and Elasticsearch health"""
    try:
        # Try to list indices as a health check
        return ElasticSearchService.health_check(vdb_core)
    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"{str(e)}")


@router.post("/{index_name}/chunks")
def get_index_chunks(
        index_name: str = Path(...,
                               description=INTERNAL_INDEX_NAME_DESC),
        page: int = Query(
            None, description="Page number (1-based) for pagination"),
        page_size: int = Query(
            None, description="Number of records per page for pagination"),
        path_or_url: Optional[str] = Query(
            None, description="Filter chunks by document path_or_url"),
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
        authorization: Optional[str] = Header(None)
):
    """Get chunks from the specified index, with optional pagination support"""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        require_knowledge_base_read_permission(index_name, user_id, tenant_id)

        if path_or_url is not None and not check_file_access(
            path_or_url, user_id, tenant_id
        ):
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail="You don't have permission to access this file",
            )

        result = ElasticSearchService.get_index_chunks(
            index_name=index_name,
            page=page,
            page_size=page_size,
            path_or_url=path_or_url,
            vdb_core=vdb_core,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except ValueError as e:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(e)
        )
    except HTTPException:
        raise
    except TokenExpiredError as e:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except Exception as e:
        error_msg = str(e)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error getting chunks: {error_msg}")


@router.post("/{index_name}/chunk")
def create_chunk(
        index_name: str = Path(...,
                               description=INTERNAL_INDEX_NAME_DESC),
        payload: ChunkCreateRequest = Body(..., description="Chunk data"),
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
        authorization: Optional[str] = Header(None),
):
    """Create a manual chunk."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        require_knowledge_base_edit_permission(index_name, user_id, tenant_id)
        result = ElasticSearchService.create_chunk(
            index_name=index_name,
            chunk_request=payload,
            vdb_core=vdb_core,
            user_id=user_id,
            tenant_id=tenant_id,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except ValueError as e:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(e)
        )
    except HTTPException:
        raise
    except TokenExpiredError as exc:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc))
    except Exception as exc:
        logger.error(
            "Error creating chunk for index %s: %s", index_name, exc, exc_info=True
        )
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(exc)
        )


@router.put("/{index_name}/chunk/{chunk_id}")
def update_chunk(
        index_name: str = Path(...,
                               description=INTERNAL_INDEX_NAME_DESC),
        chunk_id: str = Path(..., description="Chunk identifier"),
        payload: ChunkUpdateRequest = Body(...,
                                           description="Chunk update payload"),
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
        authorization: Optional[str] = Header(None),
):
    """Update an existing chunk."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        require_knowledge_base_edit_permission(index_name, user_id, tenant_id)
        result = ElasticSearchService.update_chunk(
            index_name=index_name,
            chunk_id=chunk_id,
            chunk_request=payload,
            vdb_core=vdb_core,
            user_id=user_id,
            tenant_id=tenant_id,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except ValueError as e:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(e)
        )
    except HTTPException:
        raise
    except TokenExpiredError as exc:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc))
    except Exception as exc:
        logger.error(
            "Error updating chunk %s for index %s: %s",
            chunk_id,
            index_name,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(exc)
        )


@router.delete("/{index_name}/chunk/{chunk_id}")
def delete_chunk(
        index_name: str = Path(...,
                               description=INTERNAL_INDEX_NAME_DESC),
        chunk_id: str = Path(..., description="Chunk identifier"),
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
        authorization: Optional[str] = Header(None),
):
    """Delete a chunk."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        require_knowledge_base_edit_permission(index_name, user_id, tenant_id)
        result = ElasticSearchService.delete_chunk(
            index_name=index_name,
            chunk_id=chunk_id,
            vdb_core=vdb_core,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except ValueError as e:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=str(e)
        )
    except HTTPException:
        raise
    except TokenExpiredError as exc:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc))
    except Exception as exc:
        logger.error(
            "Error deleting chunk %s for index %s: %s",
            chunk_id,
            index_name,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(exc)
        )


@router.post("/search/hybrid")
async def hybrid_search(
        payload: HybridSearchRequest,
        vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
        authorization: Optional[str] = Header(None),
):
    """Run a hybrid (accurate + semantic) search across indices."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        resolved_index_names: List[str] = []
        for requested_name in payload.index_names:
            try:
                resolved_name = get_index_name_by_knowledge_name(
                    requested_name, tenant_id
                )
            except Exception:
                resolved_name = requested_name
            # Enforce per-KB read permission before searching. The permission layer
            # maps ValueError (KB not found) -> 404 and PermissionError (no access) -> 403.
            require_knowledge_base_read_permission(
                index_name=resolved_name, user_id=user_id, tenant_id=tenant_id,
            )
            resolved_index_names.append(resolved_name)
        result = ElasticSearchService.search_hybrid(
            index_names=resolved_index_names,
            query=payload.query,
            tenant_id=tenant_id,
            top_k=payload.top_k,
            weight_accurate=payload.weight_accurate,
            vdb_core=vdb_core,
        )
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except KnowledgeBaseNeedsModelConfigError as exc:
        # Return a specific error that frontend can detect to show the config dialog
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail={
                "error_type": "KNOWLEDGE_BASE_NEEDS_MODEL_CONFIG",
                "index_name": exc.index_name,
                "message": exc.message,
                "suggestion": "Please select an embedding model for this knowledge base before searching."
            }
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail=str(exc))
    except HTTPException:
        # Re-raise HTTP exceptions (e.g. 403 from permission check) as-is
        raise
    except TokenExpiredError as exc:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc))
    except Exception as exc:
        logger.error(f"Hybrid search failed: {exc}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error executing hybrid search: {str(exc)}",
        )
