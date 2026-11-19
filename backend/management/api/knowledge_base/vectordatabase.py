# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import asyncio
import logging
from http import HTTPStatus
from threading import Event
from time import monotonic
from typing import Annotated, Any, Dict, List, Optional
from uuid import uuid4

from contracts.constants.constants import (
    ASSET_OWNER_TENANT_ID,
    INTERNAL_INDEX_NAME_DESC,
    SUMMARY_FREQUENCY_OPTIONS_FOR_API,
    VALID_SUMMARY_FREQUENCIES,
)
from contracts.errors.exceptions import (
    AppException,
    DuplicateError,
    RuntimeServiceTimeoutError,
    TokenExpiredError,
)
from contracts.knowledge import (
    ChunkCreateRequest,
    ChunkUpdateRequest,
    HybridSearchRequest,
    IndexingResponse,
    VectorDatabaseType,
)
from contracts.roles import has_any_role
from fastapi import (
    APIRouter,
    Body,
    Depends,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
)
from fastapi.responses import JSONResponse
from management.db.knowledge_base.repository import (
    get_index_name_by_knowledge_name,
    get_knowledge_record,
)
from management.db.model.repository import get_model_by_model_id
from management.services.file.service import check_file_access
from management.services.knowledge_base.chunk_browser import KnowledgeChunkBrowser
from management.services.knowledge_base.chunk_creation import create_manual_chunk
from management.services.knowledge_base.chunk_deletion import delete_manual_chunk
from management.services.knowledge_base.chunk_update import update_manual_chunk
from management.services.knowledge_base.creation import create_knowledge_base
from management.services.knowledge_base.deletion_public import with_cleanup_summary
from management.services.knowledge_base.document_admission import (
    prepare_document_admission,
)
from management.services.knowledge_base.documents import index_documents
from management.services.knowledge_base.file_reader import read_document_error
from management.services.knowledge_base.inventory import (
    knowledge_listing_operation,
    list_knowledge_indices,
    resolve_listing_view,
)
from management.services.knowledge_base.listing import (
    merge_list_indices_results,
    merge_paginated_list_indices_results,
)
from management.services.knowledge_base.names import check_knowledge_name
from management.services.knowledge_base.service import (
    ElasticSearchService,
    KnowledgeBaseNeedsModelConfigError,
    get_vector_db_core,
)
from management.services.knowledge_base.summary_settings import (
    configure_summary_schedule,
)
from management.services.monitor.audit import record_security_event
from management.services.permission.identity.session import (
    get_current_user_context,
    get_current_user_id,
)
from management.services.tag.document_projection import project_authorized_document_tags
from management.utils.knowledge_permission import (
    require_knowledge_base_edit_permission,
    require_knowledge_base_read_permission,
)
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import DeadlineExceeded, InvalidInput, NotFound, ScopeDenied
from nexent.storage.models import OperationContext
from nexent.vector_database.base import VectorDatabaseCore

from infrastructure.agentos_identity import ServicePrincipal

router = APIRouter(prefix="/indices")
service = ElasticSearchService()
logger = logging.getLogger("vectordatabase_app")
DOCUMENT_INDEX_SECONDS = 180


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
        },
    )


@router.post("/check_exist")
async def check_knowledge_base_exist(
    request: Dict[str, str] = Body(..., description="Request body containing knowledge base name"),
    authorization: Optional[str] = Header(None),
):
    """Check if a knowledge base name exists in the current tenant."""
    try:
        knowledge_name = request.get("knowledge_name", "")
        if not knowledge_name:
            raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="Knowledge base name is required")

        user_id, tenant_id = get_current_user_id(authorization)
        return await check_knowledge_name(knowledge_name, ServicePrincipal(user_id, tenant_id))
    except (TimeoutError, DeadlineExceeded):
        return JSONResponse(status_code=HTTPStatus.GATEWAY_TIMEOUT,
                            content={"message": "Knowledge base existence check timed out"})
    except TokenExpiredError as e:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logger.error(f"Error checking knowledge base existence for '{knowledge_name}': {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error checking existence for knowledge base: {str(e)}",
        )


@router.post("/{index_name}")
async def create_new_index(
    http_request: Request,
    index_name: str = Path(..., description="Name of the index to create"),
    embedding_dim: Optional[int] = Query(None, description="Dimension of the embedding vectors"),
    request: Dict[str, Any] = Body(
        None, description="Request body containing embedding_model_id and optional knowledge-base settings"
    ),
    authorization: Optional[str] = Header(None),
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
        result = await create_knowledge_base(
            knowledge_name=index_name,
            embedding_dim=embedding_dim,
            actor=ServicePrincipal(user_id, tenant_id),
            ingroup_permission=ingroup_permission,
            group_ids=group_ids,
            embedding_model_id=embedding_model_id,
            preserve_source_file=preserve_source_file,
            quota_limit_bytes=quota_limit_bytes,
            user_role=user_role,
        )
        record_security_event(
            "kb_index_create",
            request=http_request,
            user_id=user_id,
            tenant_id=tenant_id,
            details={
                "knowledge_name": index_name,
                "embedding_model_id": embedding_model_id,
                "quota_limit_bytes": quota_limit_bytes,
            },
        )
        return result
    except HTTPException:
        raise
    except AppException:
        # Keep structured knowledge-resource errors (including HTTP 429) intact.
        raise
    except DuplicateError as e:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail=str(e),
        ) from e
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))
    except TokenExpiredError as e:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error creating index: {str(e)}")


@router.get("/{index_name}/bound_agents")
async def get_knowledge_base_bound_agents(
    index_name: str = Path(..., min_length=1, pattern=r".*\S.*"),
    authorization: Optional[str] = Header(None),
    tenant_id: Optional[str] = Query(None, description="Tenant ID for filtering (uses auth if not provided)"),
):
    """List agents bound to this knowledge base for deletion confirmation."""
    try:
        user_id, auth_tenant_id, role = get_current_user_context(authorization)
    except TokenExpiredError as exc:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc)) from exc
    target_tenant_id = tenant_id or auth_tenant_id
    if target_tenant_id != auth_tenant_id and not has_any_role(role, {'SU'}):
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="Not authorized to access this tenant")
    try:
        require_knowledge_base_read_permission(index_name, user_id, target_tenant_id)
    except HTTPException as exc:
        if exc.status_code != HTTPStatus.NOT_FOUND:
            raise
        return JSONResponse(status_code=HTTPStatus.OK, content={"agents": []})
    preview = await run_blocking(
        "preview-kb-deletion", ElasticSearchService.get_bound_agents, [index_name],
        tenant_id=target_tenant_id,
        lane="control-io", owner="management.api.knowledge_base.vectordatabase",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=preview)


@router.delete("/{index_name}")
async def delete_index(
    http_request: Request,
    index_name: str = Path(..., description="Name of the index to delete"),
    authorization: Optional[str] = Header(None),
):
    """Delete an index and all its related data by calling the centralized service."""
    logger.debug(f"Received request to delete knowledge base: {index_name}")
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        require_knowledge_base_edit_permission(index_name, user_id, tenant_id)
        # Call the centralized full deletion service
        result = await ElasticSearchService.delete_knowledge_base(index_name, requested_by=user_id, tenant_id=tenant_id)
        record_security_event(
            "kb_index_delete",
            request=http_request,
            user_id=user_id,
            tenant_id=tenant_id,
            details={"index_name": index_name},
        )
        return result
    except AppException:
        # Preserve the EDS code/details for the common application handler.
        raise
    except ScopeDenied as exc:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail='No permission to modify this knowledge base') from exc
    except HTTPException:
        raise
    except TokenExpiredError as e:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logger.error(f"Error during API call to delete index '{index_name}': {str(e)}", exc_info=True)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error deleting index: {str(e)}")


@router.patch("/{index_name}")
async def update_index(
    index_name: str = Path(..., description="Name of the index to update"),
    request: Dict[str, Any] = Body(
        ..., description="Update payload with knowledge_name, ingroup_permission, group_ids, and/or tenant_id"
    ),
    authorization: Optional[str] = Header(None),
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
                content={"message": "Knowledge base updated successfully", "status": "success"},
            )
        else:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=f"Knowledge base '{index_name}' not found")
    except ValueError as exc:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc))
    except HTTPException:
        raise
    except TokenExpiredError as exc:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc))
    except Exception as exc:
        logger.error(f"Error updating index '{index_name}': {str(exc)}", exc_info=True)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error updating index: {str(exc)}")


@router.patch("/{index_name}/summary_frequency")
async def update_summary_frequency_endpoint(
    index_name: Annotated[str, Path(..., description="Name of the index to update")],
    request: Annotated[Dict[str, Any], Body(..., description="Update payload with summary_frequency")],
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Update the auto-summary frequency for a knowledge base."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        summary_frequency = request.get("summary_frequency")
        await configure_summary_schedule(
            index_name=index_name, summary_frequency=summary_frequency, tenant_id=tenant_id, user_id=user_id
        )
        return JSONResponse(status_code=HTTPStatus.OK,
                            content={"message": "Summary frequency updated successfully", "status": "success"})
    except HTTPException:
        raise
    except TokenExpiredError as exc:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc))
    except NotFound:
        raise HTTPException(status_code=404, detail=f"Knowledge base '{index_name}' not found") from None
    except ScopeDenied:
        raise HTTPException(status_code=403, detail="No permission to modify this knowledge base") from None
    except InvalidInput:
        raise HTTPException(status_code=400,
            detail=f"Invalid summary_frequency. Must be one of: {VALID_SUMMARY_FREQUENCIES}") from None
    except DeadlineExceeded:
        raise HTTPException(status_code=500, detail="Error updating summary frequency: timed out") from None
    except Exception as exc:
        logger.exception("Error updating summary frequency")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error updating summary frequency: {str(exc)}"
        )


@router.get("/{index_name}/embedding-model-status")
def get_embedding_model_status(
    index_name: str = Path(..., description="Name of the index to check"), authorization: Optional[str] = Header(None)
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
        knowledge_record = get_knowledge_record(
            {
                "index_name": index_name,
                "tenant_id": tenant_id,
                "include_asset_owner_assets": True,
            }
        )

        if not knowledge_record:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=f"Knowledge base '{index_name}' not found")

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
        logger.error(f"Error getting embedding model status for '{index_name}': {e}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error checking embedding model status: {str(e)}"
        )


@router.put("/{index_name}/embedding-model")
def update_embedding_model(
    http_request: Request,
    index_name: str = Path(..., description="Internal index name of the knowledge base to update"),
    request: Dict[str, Any] = Body(..., description="Update payload with model_id"),
    authorization: Optional[str] = Header(None),
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
            raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="model_id is required")

        result = ElasticSearchService.update_embedding_model(
            index_name=index_name,
            model_id=model_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )

        record_security_event(
            "kb_embedding_model_change",
            request=http_request,
            user_id=user_id,
            tenant_id=tenant_id,
            details={"index_name": index_name, "model_id": model_id},
        )

        return JSONResponse(status_code=HTTPStatus.OK, content=result)

    except ValueError as exc:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(exc))
    except HTTPException:
        raise
    except TokenExpiredError as exc:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc))
    except Exception as exc:
        logger.error(f"Error updating embedding model for '{index_name}': {exc}", exc_info=True)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error updating embedding model: {str(exc)}"
        )


@router.get("")
async def get_list_indices(
    pattern: str = Query("*", description="Pattern to match index names"),
    include_stats: bool = Query(False, description="Whether to include index stats"),
    tenant_id: Optional[str] = Query(None, description="Tenant ID for filtering (uses auth if not provided)"),
    offset: int = Query(0, ge=0, description="Number of visible knowledge bases to skip"),
    limit: Optional[int] = Query(None, ge=1, le=100, description="Maximum knowledge bases to return"),
    keyword: Optional[str] = Query(None, description="Search knowledge base name and description"),
    sources: Optional[List[str]] = Query(None, description="Knowledge base sources to include"),
    models: Optional[List[str]] = Query(None, description="Embedding model names to include"),
    authorization: Optional[str] = Header(None),
    request: Request = None,
):
    """List all user indices with optional stats"""
    try:
        async with knowledge_listing_operation() as context:
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
            actor = ServicePrincipal(user_id, auth_tenant_id)
            view = await resolve_listing_view(actor, request, context=context)
            if view == 'inventory':
                authorized_tenant = auth_tenant_id
                return await list_knowledge_indices(
                    actor, authorized_tenant, pattern=pattern, include_stats=include_stats, context=context,
                    inventory_read=True, **pagination_args,
                )
            if tenant_id is None:
                if limit is not None and auth_tenant_id != ASSET_OWNER_TENANT_ID:
                    prefix_limit = offset + limit
                    result = await list_knowledge_indices(
                        actor, auth_tenant_id, pattern=pattern, include_stats=include_stats, context=context,
                        pagination_enabled=True,
                        offset=0,
                        limit=prefix_limit,
                        keyword=keyword,
                        sources=sources,
                        models=models,
                    )
                    asset_result = await list_knowledge_indices(
                        actor, ASSET_OWNER_TENANT_ID, pattern=pattern, include_stats=include_stats, context=context,
                        pagination_enabled=True,
                        offset=0,
                        limit=prefix_limit,
                        keyword=keyword,
                        sources=sources,
                        models=models,
                    )
                    return merge_paginated_list_indices_results(result, asset_result, offset, limit)
                result = await list_knowledge_indices(
                    actor, auth_tenant_id, pattern=pattern, include_stats=include_stats, context=context, **pagination_args
                )
                if auth_tenant_id != ASSET_OWNER_TENANT_ID:
                    asset_result = await list_knowledge_indices(
                        actor, ASSET_OWNER_TENANT_ID, pattern=pattern, include_stats=include_stats, context=context, **pagination_args
                    )
                    return merge_list_indices_results(result, asset_result)
                return result
            return await list_knowledge_indices(
                actor, tenant_id, pattern=pattern, include_stats=include_stats, context=context, **pagination_args
            )
    except ScopeDenied as e:
        raise HTTPException(status_code=403, detail="No permission to list knowledge bases") from e
    except (TimeoutError, DeadlineExceeded, RuntimeServiceTimeoutError):
        return JSONResponse(status_code=504, content={"message": "Knowledge base list timed out"})
    except TokenExpiredError as e:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error get index: {str(e)}")


# Document Operations


def _prepare_document_admission(index_name, data, actor, *, context):
    """Map current-reader DAC errors while the service owns SI quota policy."""
    try:
        prepare_document_admission(index_name, data, actor, context=context)
    except ScopeDenied as error:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN,
                            detail="No permission to modify this knowledge base") from error
    except ValueError as error:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(error)) from error


@router.post("/{index_name}/documents", response_model=IndexingResponse)
async def create_index_documents(
    index_name: str = Path(..., description="Name of the index"),
    data: List[Dict[str, Any]] = Body(..., description="Document List to process"),
    authorization: Optional[str] = Header(None),
    task_id: Optional[str] = Header(None, alias="X-Task-Id", description="Task ID for progress tracking"),
    large_mode: bool = Query(
        False, description="Force large-batch path when current request chunk count is below threshold"
    ),
):
    """Index documents through AgentOS while retaining the public request contract."""
    cancelled = Event()
    context = OperationContext("knowledge-documents-public-" + uuid4().hex,
                               monotonic() + DOCUMENT_INDEX_SECONDS, cancelled=cancelled)
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        actor = ServicePrincipal(user_id, tenant_id)
        logger.info("knowledge_documents_public index_name=%r task_id=%r large_mode=%s", index_name, task_id, large_mode)
        async with asyncio.timeout(context.remaining()):
            await run_blocking("knowledge-documents-admission", _prepare_document_admission, index_name, data, actor,
                               context=context, lane="control-io", owner="management.knowledge_base")
            return await index_documents(index_name, data, actor, context=context)
    except AppException:
        raise
    except HTTPException:
        raise
    except TokenExpiredError as error:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(error)) from error
    except (TimeoutError, DeadlineExceeded, RuntimeServiceTimeoutError) as error:
        logger.warning("knowledge_documents_public_timeout operation_id=%s threshold_seconds=%s exception_type=%s",
                       context.operation_id, DOCUMENT_INDEX_SECONDS, type(error).__name__)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail=f"Error indexing documents: {error!s}") from error
    except Exception as error:
        logger.error("Error indexing documents: %s", error)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail=f"Error indexing documents: {error!s}") from error
    finally:
        cancelled.set()


@router.get("/{index_name}/files")
async def get_index_files(
    index_name: str = Path(..., description="Name of the index"),
    authorization: Optional[str] = Header(None),
):
    """Get all files from an index, including those that are not yet stored in ES"""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        from management.services.knowledge_base.file_listing import list_knowledge_files

        result = await list_knowledge_files(index_name, ServicePrincipal(user_id, tenant_id))

        # The read permission check above authorized this page; project tags in
        # one batch so each row never issues its own assignment request.
        files = await project_authorized_document_tags(
            result.get("files", []),
            index_name=index_name,
            actor=ServicePrincipal(user_id, tenant_id),
        )
        # Transform result to match frontend expectations
        return {"status": "success", "files": files}
    except ScopeDenied as error:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN,
                            detail="No permission to access this knowledge base") from error
    except HTTPException:
        raise
    except TokenExpiredError as e:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except (TimeoutError, DeadlineExceeded) as exc:
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error indexing documents: {exc}") from None
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error indexing documents: {error_msg}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error indexing documents: {error_msg}"
        )


@router.delete("/{index_name}/documents")
async def delete_documents(
    http_request: Request,
    index_name: str = Path(..., description="Name of the index"),
    path_or_url: Optional[str] = Query(None, description="Legacy object path to delete"),
    file_id: Optional[str] = Query(None, description="Durable lifecycle file ID (preferred for new clients)"),
    scope: str = Query(
        "full",
        description=(
            "source_only: delete MinIO source only, keep ES chunks/vectors; "
            "full: delete ES documents, MinIO source, and Redis task records"
        ),
    ),
    authorization: Optional[str] = Header(None),
):
    """Delete a document by scope: source file only or full removal from the index."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        require_knowledge_base_edit_permission(index_name, user_id, tenant_id)
        if not path_or_url and not file_id:
            raise ValueError("Either path_or_url or file_id is required")
        result = await ElasticSearchService.delete_document_by_scope(
            index_name, path_or_url, scope, requested_by=user_id, tenant_id=tenant_id,
            file_id=file_id, remove_tags=True,
        )
        if scope == "full" and not result.get("deletion_pending"):
            result = with_cleanup_summary(result)

        record_security_event(
            "kb_document_delete",
            request=http_request,
            user_id=user_id,
            tenant_id=tenant_id,
            details={"index_name": index_name, "path_or_url": path_or_url, "file_id": file_id, "scope": scope},
        )
        return result

    except ValueError as exc:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc))
    except (PermissionError, ScopeDenied) as exc:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail=str(exc))
    except HTTPException:
        raise
    except TokenExpiredError as e:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except (TimeoutError, DeadlineExceeded) as exc:
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(exc)) from None
    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error delete indexing documents: {e}",
        )


@router.get("/{index_name}/documents/error-info")
async def get_document_error_info_by_query(
    index_name: str = Path(..., description="Name of the index"),
    path_or_url: str = Query(..., min_length=1, description="Path or URL of the document"),
    file_id: Optional[str] = Query(None, description="Durable lifecycle file ID"),
    authorization: Optional[str] = Header(None),
):
    """Look up an opaque document identifier without putting it in the route path."""
    return await get_document_error_info(index_name, path_or_url, file_id, authorization)


@router.get("/{index_name}/documents/{path_or_url:path}/error-info")
async def get_document_error_info(
    index_name: str = Path(..., description="Name of the index"),
    path_or_url: str = Path(..., description="Path or URL of the document"),
    file_id: Optional[str] = Query(None, description="Durable lifecycle file ID"),
    authorization: Optional[str] = Header(None),
):
    """Get persisted error information under the current reader's KB permission."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        return await read_document_error(index_name, path_or_url, ServicePrincipal(user_id, tenant_id), file_id=file_id)
    except ValueError as exc:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(exc)) from None
    except NotFound:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND,
                            detail=f"Document {path_or_url} not found in index {index_name}") from None
    except ScopeDenied:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="No permission to access this knowledge base") from None
    except (TimeoutError, DeadlineExceeded):
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                            detail="Error getting error info: Knowledge file lookup timed out") from None
    except HTTPException:
        raise
    except TokenExpiredError as e:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logger.error("Knowledge file error lookup failed error_type=%s", type(e).__name__)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error getting error info: {str(e)}")


# Health check
@router.get("/health")
def health_check(vdb_core: VectorDatabaseCore = Depends(get_vector_db_core)):
    """Check API and Elasticsearch health"""
    try:
        # Try to list indices as a health check
        return ElasticSearchService.health_check(vdb_core)
    except Exception as e:
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"{str(e)}")


@router.post("/{index_name}/chunks")
async def get_index_chunks(
    index_name: str = Path(..., description=INTERNAL_INDEX_NAME_DESC),
    page: int = Query(None, description="Page number (1-based) for pagination"),
    page_size: int = Query(None, description="Number of records per page for pagination"),
    path_or_url: Optional[str] = Query(None, description="Filter chunks by document path_or_url"),
    vdb_core: VectorDatabaseCore = Depends(get_vector_db_core),
    authorization: Optional[str] = Header(None),
    db_type: VectorDatabaseType = Query(VectorDatabaseType.ELASTICSEARCH),
):
    """Get chunks from the specified index, with optional pagination support"""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        if db_type == VectorDatabaseType.DATAMATE:
            await run_blocking('knowledge-external-chunks-authorize', require_knowledge_base_read_permission,
                index_name, user_id, tenant_id, lane='control-io', owner='management.knowledge_base')

        if path_or_url is not None and not check_file_access(path_or_url, user_id, tenant_id):
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail="You don't have permission to access this file",
            )

        if db_type == VectorDatabaseType.DATAMATE:
            result = await run_blocking('knowledge-external-file-chunks', ElasticSearchService.get_external_file_chunks,
                index_name=index_name, page=page, page_size=page_size, path_or_url=path_or_url,
                vdb_core=vdb_core, lane='control-io', owner='management.knowledge_base')
        else:
            result = await KnowledgeChunkBrowser().browse(index_name, ServicePrincipal(user_id, tenant_id),
                page=page, page_size=page_size, path_or_url=path_or_url)
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except HTTPException:
        raise
    except ScopeDenied:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="You don't have permission to access this knowledge base") from None
    except TokenExpiredError as e:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except Exception as e:
        error_msg = str(e)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error getting chunks: {error_msg}")


@router.post("/{index_name}/chunk")
async def create_chunk(
    index_name: str = Path(..., description=INTERNAL_INDEX_NAME_DESC),
    payload: ChunkCreateRequest = Body(..., description="Chunk data"),
    authorization: Optional[str] = Header(None),
):
    """Create a manual chunk."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = await create_manual_chunk(index_name, payload, ServicePrincipal(user_id, tenant_id))
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except HTTPException:
        raise
    except ScopeDenied:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="No permission to modify this knowledge base") from None
    except DeadlineExceeded:
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Error creating chunk: storage operation timed out") from None
    except TokenExpiredError as exc:
        logger.warning("Session expired")
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=str(exc))
    except Exception as exc:
        logger.error("Error creating chunk for index %s: %s", index_name, exc, exc_info=True)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(exc))


@router.put("/{index_name}/chunk/{chunk_id}")
async def update_chunk(
    index_name: str = Path(..., description=INTERNAL_INDEX_NAME_DESC),
    chunk_id: str = Path(..., description="Chunk identifier"),
    payload: ChunkUpdateRequest = Body(..., description="Chunk update payload"),
    authorization: Optional[str] = Header(None),
):
    """Update an existing chunk."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = await update_manual_chunk(index_name, chunk_id, payload, ServicePrincipal(user_id, tenant_id))
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except HTTPException:
        raise
    except ScopeDenied:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="No permission to modify this knowledge base") from None
    except DeadlineExceeded:
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Error updating chunk: storage operation timed out") from None
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
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(exc))


@router.delete("/{index_name}/chunk/{chunk_id}")
async def delete_chunk(
    index_name: str = Path(..., description=INTERNAL_INDEX_NAME_DESC),
    chunk_id: str = Path(..., description="Chunk identifier"),
    authorization: Optional[str] = Header(None),
):
    """Delete a chunk."""
    try:
        user_id, tenant_id = get_current_user_id(authorization)
        result = await delete_manual_chunk(index_name, chunk_id, ServicePrincipal(user_id, tenant_id))
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except ValueError as e:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=str(e))
    except HTTPException:
        raise
    except ScopeDenied:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="No permission to modify this knowledge base") from None
    except DeadlineExceeded:
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Error deleting chunk: storage operation timed out") from None
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
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(exc))


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
                resolved_name = get_index_name_by_knowledge_name(requested_name, tenant_id)
            except Exception:
                resolved_name = requested_name
            # Enforce per-KB read permission before searching. The permission layer
            # maps ValueError (KB not found) -> 404 and PermissionError (no access) -> 403.
            require_knowledge_base_read_permission(
                index_name=resolved_name,
                user_id=user_id,
                tenant_id=tenant_id,
            )
            resolved_index_names.append(resolved_name)
        search_kwargs = {
            "index_names": resolved_index_names,
            "query": payload.query,
            "tenant_id": tenant_id,
            "top_k": payload.top_k,
            "weight_accurate": payload.weight_accurate,
            "vdb_core": vdb_core,
        }
        if payload.tag_predicates:
            search_kwargs["tag_predicates"] = payload.tag_predicates
        result = ElasticSearchService.search_hybrid(**search_kwargs)
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except KnowledgeBaseNeedsModelConfigError as exc:
        # Return a specific error that frontend can detect to show the config dialog
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail={
                "error_type": "KNOWLEDGE_BASE_NEEDS_MODEL_CONFIG",
                "index_name": exc.index_name,
                "message": exc.message,
                "suggestion": "Please select an embedding model for this knowledge base before searching.",
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(exc))
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
