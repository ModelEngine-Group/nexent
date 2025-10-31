import logging
from contextlib import asynccontextmanager
from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from consts.model import (
    BatchTaskRequest,
    ConvertStateRequest,
    TaskRequest,
)
from data_process.tasks import process_and_forward, process_sync
from services.data_process_service import get_data_process_service

logger = logging.getLogger("data_process.app")

# Use shared service instance
service = get_data_process_service()


@asynccontextmanager
async def lifespan(app: APIRouter):
    # Startup
    try:
        await service.start()
        yield
    finally:
        # Shutdown
        await service.stop()


router = APIRouter(
    prefix="/tasks",
    lifespan=lifespan
)


@router.post("")
async def create_task(request: TaskRequest, authorization: Optional[str] = Header(None)):
    """
    Create a new data processing task (Process → Forward chain)

    Returns task ID immediately. Processing happens in the background.
    Tasks are forwarded to Elasticsearch when complete.
    """
    # Create task using the new process_and_forward task

    logger.info(
        f"Creating task with source_type: {request.source_type}, model_id: {request.embedding_model_id}")
    task_result = process_and_forward.delay(
        source=request.source,
        source_type=request.source_type,
        chunking_strategy=request.chunking_strategy,
        index_name=request.index_name,
        original_filename=request.original_filename,
        authorization=authorization,
        embedding_model_id=request.embedding_model_id,
        tenant_id=request.tenant_id
    )
    return JSONResponse(status_code=HTTPStatus.CREATED, content={"task_id": task_result.id})


@router.post("/process")
async def process_sync_endpoint(
        source: str = Form(...),
        source_type: str = Form(...),
        chunking_strategy: str = Form("basic"),
        timeout: int = Form(30)
):
    """
    Process a file synchronously and return extracted text immediately

    This endpoint provides real-time file processing for immediate text extraction.
    Uses high-priority processing queue for fast response.

    Parameters:
        source: File path, URL, or text content to process
        source_type: Type of source ("local", "minio")
        chunking_strategy: Strategy for chunking the document
        timeout: Maximum time to wait for processing (seconds)

    Returns:
        JSON object containing extracted text and metadata
    """
    try:
        # Use the synchronous process task with high priority
        task_result = process_sync.apply_async(
            kwargs={
                'source': source,
                'source_type': source_type,
                'chunking_strategy': chunking_strategy,
                'timeout': timeout
            },
            priority=0,  # High priority for real-time processing
            queue='process_q'
        )
        # Wait for the result with timeout
        result = task_result.get(timeout=timeout)
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={
                "success": True,
                "task_id": task_result.id,
                "source": source,
                "text": result.get("text", ""),
                "chunks": result.get("chunks", []),
                "chunks_count": result.get("chunks_count", 0),
                "processing_time": result.get("processing_time", 0),
                "text_length": result.get("text_length", 0)
            }
        )
    except HTTPException:
        # Preserve explicit HTTP errors
        raise
    except Exception as e:
        logger.error(f"Error in synchronous processing: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error processing file: {str(e)}"
        )


@router.post("/batch")
async def create_batch_tasks(request: BatchTaskRequest, authorization: Optional[str] = Header(None)):
    """
    Create multiple data processing tasks at once (individual Process → Forward chains)

    Returns list of task IDs immediately. Each file gets its own task for better status tracking.
    Processing happens in the background for each file independently.
    """
    try:
        task_ids = await service.create_batch_tasks_impl(authorization=authorization, request=request)
        return JSONResponse(status_code=HTTPStatus.CREATED, content={"task_ids": task_ids})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating batch tasks: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Failed to create batch tasks: {str(e)}")


@router.get("/load_image")
async def load_image(url: str):
    """
    Load an image from URL and return it as base64 encoded data

    Parameters:
        url: Image URL to load

    Returns:
        JSON object containing base64 encoded image data and content type
    """
    try:
        # Use the service to load the image
        image = await service.load_image(url)

        if image is None:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND, detail="Failed to load image or image format not supported")

        image_data, content_type = await service.convert_to_base64(image)
        return JSONResponse(status_code=HTTPStatus.OK,
                            content={"success": True, "base64": image_data, "content_type": content_type})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error loading image: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error loading image: {str(e)}")


@router.get("")
async def list_tasks():
    """Get a list of all tasks with their basic status information"""
    tasks = await service.get_all_tasks()

    task_responses = []
    for task in tasks:
        task_responses.append({
            "id": task["id"],
            "task_name": task["task_name"],
            "index_name": task["index_name"],
            "path_or_url": task["path_or_url"],
            "original_filename": task["original_filename"],
            "status": task["status"],
            "created_at": task["created_at"],
            "updated_at": task["updated_at"],
            "error": task["error"]
        })

    return JSONResponse(
        status_code=HTTPStatus.OK,
        content={"tasks": task_responses}
    )


@router.get("/indices/{index_name}")
async def get_index_tasks(index_name: str):
    """
    Get all active tasks for a specific index

    Returns tasks that are being processed or waiting to be processed
    """
    try:
        return await service.get_index_tasks(index_name)
    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/{task_id}/details")
async def get_task_details(task_id: str):
    """Get detailed information about a task, including results"""
    task = await service.get_task_details(task_id)
    if not task:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND,
                            detail="Task not found")
    return task


@router.post("/filter_important_image")
async def filter_important_image(
        image_url: str = Form(...),
        positive_prompt: str = Form("an important image"),
        negative_prompt: str = Form("an unimportant image")
):
    """
    Check if an image is important

    Uses AI to determine image importance based on provided prompts.
    Returns importance score and confidence level.
    """
    try:
        result = await service.filter_important_image(
            image_url=image_url,
            positive_prompt=positive_prompt,
            negative_prompt=negative_prompt
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content=result
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing image: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Error processing image: {str(e)}")


@router.post("/process_text_file")
async def process_text_file(
        file: UploadFile = File(...),
        chunking_strategy: str = Form("basic")
):
    """
    Transfer the uploaded file to text content using SDK DataProcessCore

    This interface is specifically used for file-to-text conversion, supporting multiple file formats including PDF, Word, Excel, etc.
    Uses DataProcessCore from SDK for direct in-memory processing.

    Returns a JSON object containing the extracted text and metadata.
    """
    try:
        logger.info(
            f"Processing uploaded file: {file.filename} using SDK DataProcessCore")

        file_content = await file.read()
        filename = file.filename or "unknown_file"

        result = await service.process_uploaded_text_file(
            file_content=file_content,
            filename=filename,
            chunking_strategy=chunking_strategy,
        )
        return JSONResponse(content=result)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            f"Error processing uploaded file {file.filename}: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while processing the file: {str(e)}"
        )


@router.post("/convert_state")
async def convert_state(request: ConvertStateRequest):
    """
    Convert process state to forward state

    This endpoint converts a process state string to a forward state string.
    """
    try:
        result = service.convert_celery_states_to_custom(
            process_celery_state=request.process_state or "",
            forward_celery_state=request.forward_state or ""
        )
        return JSONResponse(
            status_code=HTTPStatus.OK,
            content={"state": result}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error converting state: {str(e)}")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error converting state: {str(e)}"
        )
