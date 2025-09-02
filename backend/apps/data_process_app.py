import base64
import io
import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from nexent.data_process.core import DataProcessCore

from consts.model import (
    BatchTaskRequest,
    BatchTaskResponse,
    ConvertStateRequest,
    ConvertStateResponse,
    SimpleTaskStatusResponse,
    SimpleTasksListResponse,
    TaskRequest,
    TaskResponse,
)
from data_process.tasks import process_and_forward, process_sync
from data_process.utils import get_task_info
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


@router.post("", response_model=TaskResponse, status_code=201)
async def create_task(request: TaskRequest, authorization: Optional[str] = Header(None)):
    """
    Create a new data processing task (Process → Forward chain)

    Returns task ID immediately. Processing happens in the background.
    Tasks are forwarded to Elasticsearch when complete.
    """
    # Create task using the new process_and_forward task

    logger.info(f"Creating task with source_type: {request.source_type}")
    task_result = process_and_forward.delay(
        source=request.source,
        source_type=request.source_type,
        chunking_strategy=request.chunking_strategy,
        index_name=request.index_name,
        original_filename=request.original_filename,
        authorization=authorization
    )

    return TaskResponse(task_id=task_result.id)


@router.post("/process", response_model=dict, status_code=200)
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

        return {
            "success": True,
            "task_id": task_result.id,
            "source": source,
            "text": result.get("text", ""),
            "chunks": result.get("chunks", []),
            "chunks_count": result.get("chunks_count", 0),
            "processing_time": result.get("processing_time", 0),
            "text_length": result.get("text_length", 0)
        }

    except Exception as e:
        logger.error(f"Error in synchronous processing: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error processing file: {str(e)}"
        )


@router.post("/batch", response_model=BatchTaskResponse, status_code=201)
async def create_batch_tasks(request: BatchTaskRequest, authorization: Optional[str] = Header(None)):
    """
    Create multiple data processing tasks at once (individual Process → Forward chains)

    Returns list of task IDs immediately. Each file gets its own task for better status tracking.
    Processing happens in the background for each file independently.
    """
    try:
        task_ids = []

        # Create individual tasks for each source
        for source_config in request.sources:
            # Extract parameters
            source = source_config.get('source')
            source_type = source_config.get('source_type')
            chunking_strategy = source_config.get('chunking_strategy')
            index_name = source_config.get('index_name')
            original_filename = source_config.get('original_filename')

            # Validate required fields
            if not source:
                logger.error(
                    f"Missing required field 'source' in source config: {source_config}")
                continue
            if not index_name:
                logger.error(
                    f"Missing required field 'index_name' in source config: {source_config}")
                continue

            # Create individual task for this source
            task_result = process_and_forward.delay(
                source=source,
                source_type=source_type,
                chunking_strategy=chunking_strategy,
                index_name=index_name,
                original_filename=original_filename,
                authorization=authorization
            )

            task_ids.append(task_result.id)
            logger.debug(f"Created task {task_result.id} for source: {source}")

        logger.info(
            f"Created {len(task_ids)} individual tasks for batch processing")
        return BatchTaskResponse(task_ids=task_ids)

    except Exception as e:
        logger.error(f"Error creating batch tasks: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to create batch tasks: {str(e)}")


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
                status_code=404, detail="Failed to load image or image format not supported")

        # Convert PIL image to base64
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format=image.format or 'JPEG')
        img_byte_arr.seek(0)

        # Convert to base64
        image_data = base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')

        # Determine correct content_type
        content_type = f"image/{image.format.lower() if image.format else 'jpeg'}"

        return {"success": True, "base64": image_data, "content_type": content_type}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error loading image: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error loading image: {str(e)}")


@router.get("/{task_id}", response_model=SimpleTaskStatusResponse)
async def get_task(task_id: str):
    """Get basic status information for a specific task"""
    task = await get_task_info(task_id)

    if not task:
        raise HTTPException(
            status_code=404, detail=f"Task with ID {task_id} not found")
    return SimpleTaskStatusResponse(
        id=task["id"],
        task_name=task["task_name"],
        index_name=task["index_name"],
        path_or_url=task["path_or_url"],
        original_filename=task["original_filename"],
        status=task["status"],
        created_at=task["created_at"],
        updated_at=task["updated_at"],
        error=task["error"]
    )


@router.get("", response_model=SimpleTasksListResponse)
async def list_tasks():
    """Get a list of all tasks with their basic status information"""
    tasks = await service.get_all_tasks()

    task_responses = []
    for task in tasks:
        task_responses.append(
            SimpleTaskStatusResponse(
                id=task["id"],
                task_name=task["task_name"],
                index_name=task["index_name"],
                path_or_url=task["path_or_url"],
                original_filename=task["original_filename"],
                status=task["status"],
                created_at=task["created_at"],
                updated_at=task["updated_at"],
                error=task["error"]
            )
        )

    return SimpleTasksListResponse(tasks=task_responses)


@router.get("/indices/{index_name}")
async def get_index_tasks(index_name: str):
    """
    Get all active tasks for a specific index

    Returns tasks that are being processed or waiting to be processed
    """
    try:
        return await service.get_index_tasks(index_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{task_id}/details")
async def get_task_details(task_id: str):
    """Get detailed information about a task, including results"""
    from data_process.utils import get_task_details as utils_get_task_details
    task = await utils_get_task_details(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/filter_important_image", response_model=dict)
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
        return result
    except Exception as e:
        logger.error(f"Error processing image: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error processing image: {str(e)}")


@router.post("/process_text_file", response_model=dict, status_code=200)
async def process_text_file(
    file: UploadFile = File(...),
    chunking_strategy: str = Form("basic")
):
    """
    Transfer the uploaded file to text content using SDK DataProcessCore

    This interface is specifically used for file-to-text conversion, supporting multiple file formats including PDF, Word, Excel, etc.
    Uses DataProcessCore from SDK for direct in-memory processing.

    Parameters:
        file: Uploaded file object
        chunking_strategy: Chunking strategy, default is "basic"

    Returns:
        JSON object, containing the extracted full text content and processing metadata
    """
    try:
        logger.info(
            f"Processing uploaded file: {file.filename} using SDK DataProcessCore")

        # Record processing start time
        start_time = time.time()

        # Read file content directly into memory
        file_content = await file.read()
        filename = file.filename or "unknown_file"

        # Initialize DataProcessCore
        data_processor = DataProcessCore()

        # Process file using SDK
        chunks = data_processor.file_process(
            file_data=file_content,
            filename=filename,
            chunking_strategy=chunking_strategy
        )

        # Extract text content from chunks
        full_text = ""
        chunk_texts = []
        for chunk in chunks:
            if 'content' in chunk:
                chunk_content = chunk['content']
                full_text += chunk_content + "\n"
                chunk_texts.append(chunk_content)

        # Calculate processing time
        processing_time = time.time() - start_time

        logger.info(
            f"Successfully processed uploaded file: {filename}, extracted {len(full_text)} characters in {processing_time:.2f}s")

        return {
            "success": True,
            "task_id": None,  # No async task ID for direct processing
            "filename": filename,
            "text": full_text.strip(),
            "chunks": chunk_texts,
            "chunks_count": len(chunks),
            "text_length": len(full_text.strip()),
            "processing_time": processing_time,
            "chunking_strategy": chunking_strategy
        }

    except Exception as e:
        logger.exception(
            f"Error processing uploaded file {file.filename}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while processing the file: {str(e)}"
        )


@router.post("/convert_state", response_model=ConvertStateResponse, status_code=200)
async def convert_state(request: ConvertStateRequest):
    """Convert Celery task states to custom frontend state.

    This helper endpoint allows callers that do **not** install Celery dependencies
    to obtain the corresponding frontend state for a pair of Celery task states.
    """
    from celery import states

    def _convert_to_custom_state_inner(process_celery_state: str, forward_celery_state: str) -> str:
        """Inner helper to keep the original mapping logic in one place."""
        # Handle failure states first
        if process_celery_state == states.FAILURE:
            return "PROCESS_FAILED"
        if forward_celery_state == states.FAILURE:
            return "FORWARD_FAILED"

        # Handle completed state - both must be SUCCESS
        if process_celery_state == states.SUCCESS and forward_celery_state == states.SUCCESS:
            return "COMPLETED"

        # Handle case where nothing has started
        if not process_celery_state and not forward_celery_state:
            return "WAIT_FOR_PROCESSING"

        # Define state mappings
        forward_state_map = {
            states.PENDING: "WAIT_FOR_FORWARDING",
            states.STARTED: "FORWARDING",
            states.SUCCESS: "COMPLETED",
            states.FAILURE: "FORWARD_FAILED",
        }
        process_state_map = {
            states.PENDING: "WAIT_FOR_PROCESSING",
            states.STARTED: "PROCESSING",
            states.SUCCESS: "WAIT_FOR_FORWARDING",  # Process done, waiting for forward
            states.FAILURE: "PROCESS_FAILED",
        }

        if forward_celery_state:
            return forward_state_map.get(forward_celery_state, "WAIT_FOR_FORWARDING")
        if process_celery_state:
            return process_state_map.get(process_celery_state, "WAIT_FOR_PROCESSING")
        return "WAIT_FOR_PROCESSING"

    state = _convert_to_custom_state_inner(
        request.process_state or "", request.forward_state or "")
    return ConvertStateResponse(state=state)
