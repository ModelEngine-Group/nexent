import base64
import logging
from http import HTTPStatus
from typing import Optional, Dict, Any, List, Annotated

from fastapi import APIRouter, Body, File, Form, Path, Path as PathParam, Query, Request, HTTPException, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse

from consts.const import ASSET_OWNER_TENANT_ID, VectorDatabaseType
from consts.exceptions import (
    LimitExceededError,
    UnauthorizedError,
)
from consts.model import ProcessParams
from services.file_management_service import (
    upload_files_impl,
    get_file_url_impl,
    get_file_stream_impl,
    check_file_access,
)
from services.northbound_service import NorthboundContext
from services.redis_service import get_redis_service
from services.vectordatabase_service import ElasticSearchService, get_vector_db_core
from utils.auth_utils import generate_session_jwt
from utils.file_management_utils import trigger_data_process

from .file_management_app import build_content_disposition_header
from .northbound_app import _get_northbound_context


logger = logging.getLogger("northbound_knowledge_app")

router = APIRouter(prefix="/nb/v1/knowledge", tags=["northbound"])

__all__ = ["router"]

RATE_LIMIT_EXCEEDED_DETAIL = "Too Many Requests: rate limit exceeded"


async def _require_asset_owner_context(request: Request) -> NorthboundContext:
    """Resolve northbound context and ensure the caller belongs to the asset-owner tenant."""
    ctx = await _get_northbound_context(request)
    if ctx.tenant_id != ASSET_OWNER_TENANT_ID:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="This endpoint is restricted to asset administrators.",
        )
    return ctx


@router.get("/indices")
async def get_list_indices(
    request: Request,
    pattern: Annotated[str, Query(description="Pattern to match index names")] = "*",
):
    """List knowledge bases visible to the asset-owner tenant.

    Restricted to asset administrators (same auth as create_new_index).
    """
    try:
        ctx = await _require_asset_owner_context(request)
        vdb_core = get_vector_db_core(db_type=VectorDatabaseType.ELASTICSEARCH)
        return ElasticSearchService.list_indices(
            pattern, True, ctx.tenant_id, ctx.user_id, vdb_core
        )
    except LimitExceededError as e:
        logger.exception("Rate limit exceeded while listing knowledge bases")
        raise HTTPException(
            status_code=HTTPStatus.TOO_MANY_REQUESTS,
            detail=RATE_LIMIT_EXCEEDED_DETAIL)
    except UnauthorizedError as e:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error listing knowledge bases")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Error listing knowledge bases")


@router.post("/indices/{index_name}")
async def create_new_index(
    request: Request,
    index_name: Annotated[str, Path(..., description="Name of the index to create")],
    embedding_dim: Annotated[
        Optional[int],
        Query(description="Dimension of the embedding vectors"),
    ] = None,
    body: Annotated[
        Optional[Dict[str, Any]],
        Body(
            description=(
                "Request body with optional fields (ingroup_permission, group_ids, embedding_model_name)"
            ),
        ),
    ] = None,
):
    """Create a new vector index and store it in the knowledge table.

    Restricted to the asset-owner tenant: only callers whose access key resolves
    to the asset-owner tenant are allowed to create knowledge bases through the
    northbound API.
    """
    try:
        ctx = await _require_asset_owner_context(request)
        vdb_core = get_vector_db_core(db_type=VectorDatabaseType.ELASTICSEARCH)

        ingroup_permission = None
        group_ids = None
        embedding_model_name = None
        if body:
            ingroup_permission = body.get("ingroup_permission")
            group_ids = body.get("group_ids")
            embedding_model_name = body.get("embedding_model_name")

        return ElasticSearchService.create_knowledge_base(
            knowledge_name=index_name,
            embedding_dim=embedding_dim,
            vdb_core=vdb_core,
            user_id=ctx.user_id,
            tenant_id=ctx.tenant_id,
            ingroup_permission=ingroup_permission,
            group_ids=group_ids,
            embedding_model_name=embedding_model_name,
        )
    except LimitExceededError as e:
        logger.exception("Rate limit exceeded while creating index")
        raise HTTPException(
            status_code=HTTPStatus.TOO_MANY_REQUESTS,
            detail=RATE_LIMIT_EXCEEDED_DETAIL)
    except UnauthorizedError as e:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error creating index")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Error creating index")


@router.delete("/indices/{index_name}")
async def delete_index(
    request: Request,
    index_name: Annotated[str, Path(..., description="Name of the index to delete")],
):
    """Delete a knowledge base and all related data.

    Restricted to asset administrators (same auth as create_new_index).
    """
    logger.debug("Received northbound request to delete knowledge base")
    try:
        ctx = await _require_asset_owner_context(request)
        vdb_core = get_vector_db_core(db_type=VectorDatabaseType.ELASTICSEARCH)
        return await ElasticSearchService.full_delete_knowledge_base(
            index_name, vdb_core, ctx.user_id
        )
    except LimitExceededError as e:
        logger.exception("Rate limit exceeded while deleting index")
        raise HTTPException(
            status_code=HTTPStatus.TOO_MANY_REQUESTS,
            detail=RATE_LIMIT_EXCEEDED_DETAIL)
    except UnauthorizedError as e:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error deleting index")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Error deleting index")


@router.get("/indices/{index_name}/files")
async def get_index_files(
    request: Request,
    index_name: Annotated[str, Path(..., description="Name of the index")],
):
    """Get all files from an index, including those that are not yet stored in ES.

    Restricted to asset administrators (same auth as get_list_indices).
    """
    try:
        ctx = await _require_asset_owner_context(request)
        vdb_core = get_vector_db_core(db_type=VectorDatabaseType.ELASTICSEARCH)
        logger.debug(
            "Listing files for index %s, tenant_id=%s, user_id=%s",
            index_name,
            ctx.tenant_id,
            ctx.user_id,
        )
        result = await ElasticSearchService.list_files(
            index_name, include_chunks=False, vdb_core=vdb_core
        )
        return {
            "status": "success",
            "files": result.get("files", []),
        }
    except LimitExceededError as e:
        logger.exception("Rate limit exceeded while listing files")
        raise HTTPException(
            status_code=HTTPStatus.TOO_MANY_REQUESTS,
            detail=RATE_LIMIT_EXCEEDED_DETAIL)
    except UnauthorizedError as e:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error getting files for index")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Error getting index files")


@router.delete("/indices/{index_name}/documents")
async def delete_documents(
    request: Request,
    index_name: Annotated[str, Path(..., description="Name of the index")],
    path_or_url: Annotated[str, Query(..., description="Path or URL of documents to delete")],
):
    """Delete documents by path or URL and clean up related Redis records.

    Restricted to asset administrators (same auth as get_list_indices).
    """
    try:
        ctx = await _require_asset_owner_context(request)
        vdb_core = get_vector_db_core(db_type=VectorDatabaseType.ELASTICSEARCH)
        logger.debug("Deleting documents for index %s", index_name)
        result = ElasticSearchService.delete_documents(
            index_name, path_or_url, vdb_core)

        try:
            redis_service = get_redis_service()
            redis_cleanup_result = redis_service.delete_document_records(
                index_name, path_or_url)

            result["redis_cleanup"] = redis_cleanup_result

            original_message = result.get(
                "message", "Documents deleted successfully")
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
                "Redis cleanup failed for index %s: %s",
                index_name,
                redis_error,
            )
            result["redis_cleanup_error"] = str(redis_error)
            original_message = result.get(
                "message", "Documents deleted successfully")
            result["message"] = (
                f"{original_message}, but Redis cleanup encountered an error: "
                f"{str(redis_error)}"
            )

        return result
    except LimitExceededError as e:
        logger.exception("Rate limit exceeded while deleting documents")
        raise HTTPException(
            status_code=HTTPStatus.TOO_MANY_REQUESTS,
            detail=RATE_LIMIT_EXCEEDED_DETAIL)
    except UnauthorizedError as e:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error deleting documents for index")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Error deleting documents")


@router.post("/file/upload")
async def upload_files(
    request: Request,
    file: Annotated[List[UploadFile], File(..., alias="file")],
    index_name: str = Form(..., description="Knowledge base index"),
):
    """Upload files to MinIO and trigger knowledge base data processing.

    Uses chunking_strategy=basic. Restricted to asset administrators
    (same auth as create_new_index).
    """
    try:
        ctx = await _require_asset_owner_context(request)
        destination = "minio"
        if not file:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="No files in the request",
            )

        errors, uploaded_file_paths, uploaded_filenames = await upload_files_impl(
            destination, file, None, index_name, ctx.user_id, uploader_tenant_id=ctx.tenant_id
        )

        if uploaded_file_paths:
            files = [
                {"path_or_url": path, "filename": name}
                for path, name in zip(uploaded_file_paths, uploaded_filenames)
            ]
            # Internal data-process / ES indexing expects JWT, not northbound API key
            internal_jwt = generate_session_jwt(ctx.user_id)
            process_params = ProcessParams(
                chunking_strategy="basic",
                source_type="minio",
                index_name=index_name,
                authorization=internal_jwt,
            )
            process_result = await trigger_data_process(files, process_params)

            if process_result is None or (
                isinstance(process_result, dict)
                and process_result.get("status") == "error"
            ):
                error_message = "Data process service failed"
                if isinstance(process_result, dict) and "message" in process_result:
                    error_message = process_result["message"]
                raise HTTPException(
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    detail=error_message,
                )

            return JSONResponse(
                status_code=HTTPStatus.CREATED,
                content={
                    "message": (
                        "Files uploaded and processing triggered successfully"
                    ),
                    "uploaded_filenames": uploaded_filenames,
                    "uploaded_file_paths": uploaded_file_paths,
                    "errors": errors,
                    "process_tasks": process_result,
                },
            )
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="No valid files uploaded",
        )
    except LimitExceededError as e:
        logger.exception("Rate limit exceeded while uploading files")
        raise HTTPException(
            status_code=HTTPStatus.TOO_MANY_REQUESTS,
            detail=RATE_LIMIT_EXCEEDED_DETAIL)
    except UnauthorizedError as e:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception("File upload error")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="File upload error.")


@router.get("/file/download/{object_name:path}")
async def get_storage_file(
    request: Request,
    object_name: str = PathParam(..., description="File object name"),
    download: str = Query(
        "ignore",
        description=(
            "How to get the file: "
            "'ignore' (default, return file info), "
            "'stream' (return file stream), "
            "'redirect' (redirect to download URL), "
            "'base64' (return base64-encoded content for images)."
        ),
    ),
    expires: int = Query(86400, description="URL validity period (seconds)"),
    filename: Optional[str] = Query(
        None, description="Original filename for download (optional)"),
):
    """Get file information, download link, or file stream.

    Restricted to asset administrators (same auth as create_new_index).
    """
    try:
        ctx = await _require_asset_owner_context(request)

        if not check_file_access(object_name, ctx.user_id, ctx.tenant_id):
            logger.warning(
                "[get_storage_file] Access denied: user_id=%s",
                ctx.user_id,
            )
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail="You don't have permission to access this file",
            )

        logger.info(
            "[get_storage_file] download=%s",
            download,
        )
        if download == "redirect":
            result = await get_file_url_impl(
                object_name=object_name, expires=expires)
            return RedirectResponse(url=result["url"])
        if download == "stream":
            file_stream, content_type = await get_file_stream_impl(
                object_name=object_name)
            logger.info(
                "Streaming file: object_name=%s, content_type=%s",
                object_name,
                content_type,
            )

            download_filename = filename
            if not download_filename:
                download_filename = (
                    object_name.split("/")[-1]
                    if "/" in object_name
                    else object_name
                )

            content_disposition = build_content_disposition_header(
                download_filename)

            return StreamingResponse(
                file_stream,
                media_type=content_type,
                headers={
                    "Content-Disposition": content_disposition,
                    "Cache-Control": "public, max-age=3600",
                    "ETag": f'"{object_name}"',
                },
            )
        if download == "base64":
            file_stream, content_type = await get_file_stream_impl(
                object_name=object_name)
            try:
                data = file_stream.read()
            except Exception as exc:
                logger.error(
                    "Failed to read file stream for base64: %s", str(exc))
                raise HTTPException(
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    detail="Failed to read file content for base64 encoding",
                )

            base64_content = base64.b64encode(data).decode("utf-8")
            return JSONResponse(
                status_code=HTTPStatus.OK,
                content={
                    "success": True,
                    "base64": base64_content,
                    "content_type": content_type,
                    "object_name": object_name,
                },
            )
        return await get_file_url_impl(
            object_name=object_name, expires=expires)
    except LimitExceededError as e:
        logger.error(
            "%s: %s",
            RATE_LIMIT_EXCEEDED_DETAIL,
            str(e),
            exc_info=e,
        )
        raise HTTPException(
            status_code=HTTPStatus.TOO_MANY_REQUESTS,
            detail=RATE_LIMIT_EXCEEDED_DETAIL)
    except UnauthorizedError as e:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to get file")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to get file.")
