import asyncio
import os
import json
from pathlib import Path
from typing import List, Optional
from io import BytesIO
import requests
import logging
import httpx

from utils.auth_utils import get_current_user_info
from fastapi import UploadFile, File, HTTPException, Form, APIRouter, Query, Path as PathParam, Body, Header, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse

from consts.model import ProcessParams
from consts.const import MAX_CONCURRENT_UPLOADS, UPLOAD_FOLDER
from utils.file_management_utils import save_upload_file, trigger_data_process
from utils.attachment_utils import convert_image_to_text, convert_long_text_to_text
from database.attachment_db import (
    upload_fileobj, delete_file, get_file_url, list_files, get_file_stream, get_content_type
)

logger = logging.getLogger("file_management_app")

# Create upload directory
upload_dir = Path(UPLOAD_FOLDER)
upload_dir.mkdir(exist_ok=True)

# Concurrency control
upload_semaphore = asyncio.Semaphore(MAX_CONCURRENT_UPLOADS)

# Create API router
router = APIRouter(prefix="/file")


# Handle preflight requests
@router.options("/{full_path:path}")
async def options_route(full_path: str):
    return JSONResponse(
        status_code=200,
        content={"detail": "OK"},
    )


async def _upload_to_minio(files: List[UploadFile], folder: str) -> List[dict]:
    """Helper function to upload files to MinIO and return results."""
    results = []
    for f in files:
        try:
            # Read file content
            file_content = await f.read()

            # Convert file content to BytesIO object
            file_obj = BytesIO(file_content)

            # Upload file
            result = upload_fileobj(
                file_obj=file_obj,
                file_name=f.filename or "",
                prefix=folder,
                metadata={
                    "original-filename": str(f.filename or ""),
                    "content-type": str(f.content_type or "application/octet-stream"),
                    "folder": str(folder)
                }
            )

            # Reset file pointer for potential re-reading
            await f.seek(0)
            results.append(result)

        except Exception as e:
            # Log single file upload failure but continue processing other files
            logger.error(f"Failed to upload file {f.filename}: {e}", exc_info=True)
            results.append({
                "success": False,
                "file_name": f.filename,
                "error": "An error occurred while processing the file."
            })
    return results


@router.post("/upload")
async def upload_files(
        file: List[UploadFile] = File(..., alias="file"),
        destination: str = Form(..., description="Upload destination: 'local' or 'minio'"),
        folder: str = Form("attachments", description="Storage folder path for MinIO (optional)")
):
    if not file:
        raise HTTPException(status_code=400, detail="No files in the request")

    uploaded_filenames = []
    uploaded_file_paths = []
    errors = []

    if destination == "local":
        async with upload_semaphore:
            for f in file:
                if not f:
                    continue

                safe_filename = os.path.basename(f.filename or "")
                upload_path = upload_dir / safe_filename
                absolute_path = upload_path.absolute()

                # Save file
                if await save_upload_file(f, upload_path):
                    uploaded_filenames.append(safe_filename)
                    uploaded_file_paths.append(str(absolute_path))
                    logger.info(f"Successfully saved file: {safe_filename}")
                else:
                    errors.append(f"Failed to save file: {f.filename}")

    elif destination == "minio":
        minio_results = await _upload_to_minio(files=file, folder=folder)
        for result in minio_results:
            if result.get("success"):
                uploaded_filenames.append(result.get("file_name"))
                uploaded_file_paths.append(result.get("object_name"))
            else:
                file_name = result.get('file_name')
                error_msg = result.get('error', 'Unknown error')
                errors.append(f"Failed to upload {file_name}: {error_msg}")
    else:
        raise HTTPException(status_code=400, detail="Invalid destination. Must be 'local' or 'minio'.")


    if uploaded_file_paths:
        return JSONResponse(
            status_code=200,
            content={
                "message": f"Files uploaded successfully to {destination}, ready for processing.",
                "uploaded_filenames": uploaded_filenames,
                "uploaded_file_paths": uploaded_file_paths,
                "errors": errors
            }
        )
    else:
        return JSONResponse(
            status_code=400,
            content={
                "error": "No valid files uploaded",
                "errors": errors
            }
        )


@router.post("/process")
async def process_files(
        files: List[dict] = Body(..., description="List of file details to process, including path_or_url and filename"),
        chunking_strategy: Optional[str] = Body("basic"),
        index_name: str = Body(...),
        destination: str = Body(...)
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
        index_name=index_name
    )

    process_result = await trigger_data_process(files, process_params)

    if process_result is None or (isinstance(process_result, dict) and process_result.get("status") == "error"):
        error_message = "Data process service failed"
        if isinstance(process_result, dict) and "message" in process_result:
            error_message = process_result["message"]
        return JSONResponse(
            status_code=500,
            content={
                "error": error_message
            }
        )

    return JSONResponse(
        status_code=201,
        content={
            "message": "Files processing triggered successfully",
            "process_tasks": process_result
        }
    )


@router.post("/storage")
async def storage_upload_files(
    files: List[UploadFile] = File(..., description="List of files to upload"),
    folder: str = Form("attachments", description="Storage folder path (optional)")
):
    """
    Upload one or more files to MinIO storage

    - **files**: List of files to upload
    - **folder**: Storage folder path (optional, defaults to 'attachments')

    Returns upload results including file information and access URLs
    """
    results = await _upload_to_minio(files=files, folder=folder)

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
    include_urls: bool = Query(True, description="Whether to include presigned URLs")
):
    """
    Get list of files from MinIO storage

    - **prefix**: File prefix filter (optional)
    - **limit**: Maximum number of files to return (default 100)
    - **include_urls**: Whether to include presigned URLs (default True)

    Returns file list and metadata
    """
    try:
        # Get file list
        files = list_files(prefix=prefix)

        # Limit return count
        files = files[:limit]

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
            status_code=500,
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
            result = get_file_url(object_name=object_name, expires=expires)
            if not result["success"]:
                raise HTTPException(
                    status_code=404,
                    detail=f"File does not exist or cannot be accessed: {result.get('error', 'Unknown error')}"
                )
            return RedirectResponse(url=result["url"])
        elif download == "stream":
            # return a readable file stream
            file_stream = get_file_stream(object_name=object_name)
            if file_stream is None:
                raise HTTPException(
                    status_code=404,
                    detail="File not found or failed to read from storage"
                )
            content_type = get_content_type(object_name)
            return StreamingResponse(
                file_stream,
                media_type=content_type,
                headers={
                    "Content-Disposition": f'inline; filename="{object_name}"'
                }
            )
        else:
            # return file metadata
            result = get_file_url(object_name=object_name, expires=expires)
            if not result["success"]:
                raise HTTPException(
                    status_code=404,
                    detail=f"File does not exist or cannot be accessed: {result.get('error', 'Unknown error')}"
                )
            return result
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(
            status_code=500,
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
        # Delete file
        result = delete_file(object_name=object_name)

        if not result["success"]:
            raise HTTPException(
                status_code=404,
                detail=f"File does not exist or deletion failed: {result.get('error', 'Unknown error')}"
            )

        return {
            "success": True,
            "message": f"File {object_name} successfully deleted"
        }

    except Exception as e:
        if isinstance(e, HTTPException):
            raise e

        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete file: {str(e)}"
        )


@router.post("/storage/batch-urls")
async def get_storage_file_batch_urls(
    request_data: dict = Body(..., description="JSON containing list of file object names"),
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
        raise HTTPException(status_code=400, detail="Request body must contain object_names array")
    
    results = []

    for object_name in object_names:
        try:
            # Get file URL
            result = get_file_url(object_name=object_name, expires=expires)
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
async def agent_preprocess_api(request: Request, query: str = Form(...), files: List[UploadFile] = File(...), authorization: Optional[str] = Header(None)):
    """
    Preprocess uploaded files and return streaming response
    """
    try:
        # Pre-read and cache all file contents
        user_id, tenant_id, language = get_current_user_info(authorization, request)
        file_cache = []
        for file in files:
            import time
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

        async def generate():
            file_descriptions = []
            total_files = len(file_cache)

            for index, file_data in enumerate(file_cache):
                progress = int((index / total_files) * 100)

                progress_message = json.dumps({
                    "type": "progress",
                    "progress": progress,
                    "message": f"Parsing file {index + 1}/{total_files}: {file_data['filename']}"
                }, ensure_ascii=False)
                yield f"data: {progress_message}\n\n"
                await asyncio.sleep(0.1)

                try:
                    # Check if file already has an error
                    if "error" in file_data:
                        raise Exception(file_data["error"])

                    if file_data["ext"] in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
                        description = await process_image_file(query, file_data["filename"], file_data["content"], tenant_id, language)
                    else:
                        description = await process_text_file(query, file_data["filename"], file_data["content"], tenant_id, language)
                    file_descriptions.append(description)

                    # Send processing result for each file
                    file_message = json.dumps({
                        "type": "file_processed",
                        "filename": file_data["filename"],
                        "description": description
                    }, ensure_ascii=False)
                    yield f"data: {file_message}\n\n"
                    await asyncio.sleep(0.1)
                except Exception as e:
                    error_description = f"Error parsing file {file_data['filename']}: {str(e)}"
                    file_descriptions.append(error_description)
                    error_message = json.dumps({
                        "type": "error",
                        "filename": file_data["filename"],
                        "message": error_description
                    }, ensure_ascii=False)
                    yield f"data: {error_message}\n\n"
                    await asyncio.sleep(0.1)

            # Send completion message
            complete_message = json.dumps({
                "type": "complete",
                "progress": 100,
                "final_query": query
            }, ensure_ascii=False)
            yield f"data: {complete_message}\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive"
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"File preprocessing error: {str(e)}")


async def process_image_file(query, filename, file_content, tenant_id: str, language: str = 'zh') -> str:
    """
    Process image file, convert to text using external API
    """
    image_stream = BytesIO(file_content)
    text = convert_image_to_text(query, image_stream, tenant_id, language)

    return f"Image file {filename} content: {text}"


async def process_text_file(query, filename, file_content, tenant_id: str, language: str = 'zh') -> str:
    """
    Process text file, convert to text using external API
    """
    # file_content is byte data, need to send to API through file upload
    data_process_service_url = os.environ.get('DATA_PROCESS_SERVICE')
    api_url = f"{data_process_service_url}/tasks/process_text_file"
    logger.info(f"Processing text file {filename} with API: {api_url}")

    try:
        # Upload byte data as a file
        files = {
            'file': (filename, file_content, 'application/octet-stream')
        }
        data = {
            'chunking_strategy': 'basic',
            'timeout': 60
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(api_url, files=files, data=data, timeout=60)

        if response.status_code == 200:
            result = response.json()
            raw_text = result.get("text", "")
            logger.info(f"File processed successfully: {raw_text[:100]}...")
        else:
            error_detail = response.json().get('detail', '未知错误') if response.headers.get('content-type', '').startswith('application/json') else response.text
            logger.error(f"File processing failed (status code: {response.status_code}): {error_detail}")
            raise Exception(f"File processing failed (status code: {response.status_code}): {error_detail}")

    except requests.exceptions.Timeout:
        raise Exception("API call timeout")
    except requests.exceptions.ConnectionError:
        raise Exception(f"Cannot connect to data processing service: {api_url}")
    except Exception as e:
        raise Exception(f"Error processing file: {str(e)}")

    text = convert_long_text_to_text(query, raw_text, tenant_id, language)
    return f"File {filename} content: {text}"


def get_file_description(files: List[UploadFile]) -> str:
    """
    Generate file description text
    """
    description = "User provided some reference files:\n"
    for file in files:
        ext = os.path.splitext(file.filename or "")[1].lower()
        if ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp']:
            description += f"- Image file {file.filename or ''}\n"
        else:
            description += f"- File {file.filename or ''}\n"
    return description
