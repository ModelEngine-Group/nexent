import logging
import os
from http import HTTPStatus
from typing import List, Optional

from fastapi import APIRouter, Body, File, Form, Header, HTTPException, Path as PathParam, Query, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse

from consts.model import ProcessParams
from services.file_management_service import upload_to_minio, upload_files_impl, \
    get_file_url_impl, get_file_stream_impl, delete_file_impl, list_files_impl, \
    preprocess_files_generator
from utils.auth_utils import get_current_user_info
from utils.file_management_utils import trigger_data_process

logger = logging.getLogger("file_management_app")

# Create API router
router = APIRouter(prefix="/file")


# Handle preflight requests
@router.options("/{full_path:path}")
async def options_route(full_path: str):
    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={"detail": "OK"},
    )


@router.post("/upload")
async def upload_files(
        file: List[UploadFile] = File(..., alias="file"),
        destination: str = Form(...,
                                description="Upload destination: 'local' or 'minio'"),
        folder: str = Form(
            "attachments", description="Storage folder path for MinIO (optional)"),
        index_name: Optional[str] = Form(
            None, description="Knowledge base index for conflict resolution")
):
    if not file:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST,
                            detail="No files in the request")

    errors, uploaded_file_paths, uploaded_filenames = await upload_files_impl(destination, file, folder, index_name)

    if uploaded_file_paths:
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "message": f"Files uploaded successfully to {destination}, ready for processing.",
                "uploaded_filenames": uploaded_filenames,
                "uploaded_file_paths": uploaded_file_paths,
                "errors": errors
            }
        )
    else:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST,
                            detail="No valid files uploaded")


@router.post("/process")
async def process_files(
        files: List[dict] = Body(
            ..., description="List of file details to process, including path_or_url and filename"),
        chunking_strategy: Optional[str] = Body("basic"),
        index_name: str = Body(...),
        destination: str = Body(...),
        authorization: Optional[str] = Header(None)
):
    """
    Trigger data processing for a list of uploaded files.
    files: List of dicts, each with "path_or_url" and "filename"
    chunking_strategy: chunking strategy, could be chosen from basic/by_title/none
    index_name: index name in elasticsearch
    destination: 'local' or 'minio'
    """
    process_params = ProcessParams(
        chunking_strategy=chunking_strategy,
        source_type=destination,
        index_name=index_name,
        authorization=authorization
    )

    process_result = await trigger_data_process(files, process_params)

    if process_result is None or (isinstance(process_result, dict) and process_result.get("status") == "error"):
        error_message = "Data process service failed"
        if isinstance(process_result, dict) and "message" in process_result:
            error_message = process_result["message"]
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=error_message)

    return JSONResponse(
        status_code=HTTPStatus.CREATED,
        content={
            "message": "Files processing triggered successfully",
            "process_tasks": process_result
        }
    )


@router.post("/storage")
async def storage_upload_files(
    files: List[UploadFile] = File(..., description="List of files to upload"),
    folder: str = Form(
        "attachments", description="Storage folder path (optional)")
):
    """
    Upload one or more files to MinIO storage

    - **files**: List of files to upload
    - **folder**: Storage folder path (optional, defaults to 'attachments')

    Returns upload results including file information and access URLs
    """
    results = await upload_to_minio(files=files, folder=folder)

    # Return upload results for all files
    return {
        "message": f"Processed {len(results)} files",
        "success_count": sum(1 for r in results if r.get("success", False)),
        "failed_count": sum(1 for r in results if not r.get("success", False)),
        "results": results
    }


@router.get("/storage")
async def get_storage_files(
    prefix: str = Query("", description="File prefix filter"),
    limit: int = Query(100, description="Maximum number of files to return"),
    include_urls: bool = Query(
        True, description="Whether to include presigned URLs")
):
    """
    Get list of files from MinIO storage

    - **prefix**: File prefix filter (optional)
    - **limit**: Maximum number of files to return (default 100)
    - **include_urls**: Whether to include presigned URLs (default True)

    Returns file list and metadata
    """
    try:
        files = await list_files_impl(prefix, limit)
        # Remove URLs if not needed
        if not include_urls:
            for file in files:
                if "url" in file:
                    del file["url"]

        return {
            "total": len(files),
            "files": files
        }
    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to get file list: {str(e)}"
        )


@router.get("/storage/{path}/{object_name}")
async def get_storage_file(
    object_name: str = PathParam(..., description="File object name"),
    download: str = Query("ignore", description="How to get the file"),
    expires: int = Query(3600, description="URL validity period (seconds)")
):
    """
    Get information, download link, or file stream for a single file

    - **object_name**: File object name
    - **download**: Download mode: ignore (default, return file info), stream (return file stream), redirect (redirect to download URL)
    - **expires**: URL validity period in seconds (default 3600)

    Returns file information, download link, or file content
    """
    try:
        if download == "redirect":
            # return a redirect download URL
            result = await get_file_url_impl(object_name=object_name, expires=expires)
            return RedirectResponse(url=result["url"])
        elif download == "stream":
            # return a readable file stream
            file_stream, content_type = await get_file_stream_impl(object_name=object_name)
            return StreamingResponse(
                file_stream,
                media_type=content_type,
                headers={
                    "Content-Disposition": f'inline; filename="{object_name}"'
                }
            )
        else:
            # return file metadata
            return await get_file_url_impl(object_name=object_name, expires=expires)
    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to get file information: {str(e)}"
        )


@router.delete("/storage/{object_name:path}")
async def remove_storage_file(
    object_name: str = PathParam(..., description="File object name to delete")
):
    """
    Delete file from MinIO storage

    - **object_name**: File object name to delete

    Returns deletion operation result
    """
    try:
        await delete_file_impl(object_name=object_name)
        return {
            "success": True,
            "message": f"File {object_name} successfully deleted"
        }
    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete file: {str(e)}"
        )


@router.post("/storage/batch-urls")
async def get_storage_file_batch_urls(
    request_data: dict = Body(...,
                              description="JSON containing list of file object names"),
    expires: int = Query(3600, description="URL validity period (seconds)")
):
    """
    Batch get download URLs for multiple files (JSON request)

    - **request_data**: JSON request body containing object_names list
    - **expires**: URL validity period in seconds (default 3600)

    Returns URL and status information for each file
    """
    # Extract object_names from request body
    object_names = request_data.get("object_names", [])
    if not object_names or not isinstance(object_names, list):
        raise HTTPException(
            status_code=400, detail="Request body must contain object_names array")

    results = []

    for object_name in object_names:
        try:
            # Get file URL
            result = get_file_url_impl(
                object_name=object_name, expires=expires)
            results.append({
                "object_name": object_name,
                "success": result["success"],
                "url": result.get("url"),
                "error": result.get("error")
            })
        except Exception as e:
            results.append({
                "object_name": object_name,
                "success": False,
                "error": str(e)
            })

    return {
        "total": len(results),
        "success_count": sum(1 for r in results if r.get("success", False)),
        "failed_count": sum(1 for r in results if not r.get("success", False)),
        "results": results
    }


@router.post("/preprocess")
async def agent_preprocess_api(
        request: Request, query: str = Form(...),
        files: List[UploadFile] = File(...),
        authorization: Optional[str] = Header(None)
):
    """
    Preprocess uploaded files and return streaming response
    """
    try:
        # Pre-read and cache all file contents
        user_id, tenant_id, language = get_current_user_info(
            authorization, request)
        file_cache = []
        for file in files:
            try:
                content = await file.read()
                file_cache.append({
                    "filename": file.filename or "",
                    "content": content,
                    "ext": os.path.splitext(file.filename or "")[1].lower()
                })
            except Exception as e:
                file_cache.append({
                    "filename": file.filename or "",
                    "error": str(e)
                })

        # Generate unique task ID for this preprocess operation
        import uuid
        task_id = str(uuid.uuid4())
        conversation_id = request.query_params.get("conversation_id")
        if conversation_id:
            conversation_id = int(conversation_id)
        else:
            conversation_id = -1  # Default for cases without conversation_id

        # Call service layer to generate streaming response
        return StreamingResponse(
            preprocess_files_generator(
                query=query,
                file_cache=file_cache,
                tenant_id=tenant_id,
                language=language,
                task_id=task_id,
                conversation_id=conversation_id
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive"
            }
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"File preprocessing error: {str(e)}")
