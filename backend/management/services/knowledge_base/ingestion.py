# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Knowledge ingestion submission and upstream error compatibility."""

import logging
from typing import List

import httpx
from consts.const import DATA_PROCESS_SERVICE
from contracts.knowledge import ProcessParams
from management.db.knowledge_base.repository import get_knowledge_record
from infrastructure.ingestion.errors import classify_ingestion_exception
from infrastructure.observability.knowledge import (
    inject_trace_context,
    set_span_attributes,
    trace_knowledge_operation,
)

logger = logging.getLogger(__name__)


def _data_process_error_result(
    error: object,
    stage: str = "TASK_SUBMIT",
    legacy_code: object = None,
) -> dict:
    """Keep an upstream stable code when data-process rejects a request."""
    classified = classify_ingestion_exception(error, stage)
    if legacy_code is not None:
        compatibility_code = legacy_code
    elif isinstance(error, httpx.RequestError):
        # Preserve the pre-lifecycle response contract for callers that still
        # branch on CONNECTION_ERROR while exposing the new error_code too.
        compatibility_code = "CONNECTION_ERROR"
    else:
        compatibility_code = "INTERNAL_ERROR"
    return {
        "status": "error",
        "code": compatibility_code,
        "error_code": classified.error_code,
        "message": classified.error_message or "Data process service failed",
    }


@trace_knowledge_operation("knowledge.process.submit", "process.submit")
async def trigger_data_process(files: List[dict], process_params: ProcessParams, tenant_id: str):
    """Trigger data processing service to handle uploaded files"""
    try:
        if not files:
            return None

        if not tenant_id:
            raise ValueError("Authenticated tenant is required")

        # Resolve embedding model from the knowledge base record (not request model_id)
        embedding_model_id = None
        try:
            knowledge_record = get_knowledge_record(
                {
                    "index_name": process_params.index_name,
                    "tenant_id": tenant_id,
                }
            )
            embedding_model_id = (
                knowledge_record.get("embedding_model_id") if knowledge_record else None
            )
        except Exception as e:
            logger.warning(
                "Failed to resolve embedding_model_id from knowledge_record: %s", e
            )

        # Build headers with authorization
        headers = {"Authorization": process_params.authorization}
        telemetry_context = inject_trace_context()
        headers.update(telemetry_context)

        # Build source data list
        if len(files) == 1:
            # Single file request
            file_details = files[0]
            payload = {
                "source": file_details.get("path_or_url"),
                "source_type": process_params.source_type,
                "chunking_strategy": process_params.chunking_strategy,
                "index_name": process_params.index_name,
                "original_filename": file_details.get("filename"),
                "file_id": file_details.get("file_id"),
                "embedding_model_id": embedding_model_id,
                "tenant_id": tenant_id,
            }
            payload["telemetry_context"] = telemetry_context

            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{DATA_PROCESS_SERVICE}/tasks",
                        headers=headers,
                        json=payload,
                        timeout=30.0,
                    )

                if response.status_code == 201:
                    return response.json()
                else:
                    logger.error(
                        "Error from data process service: %s - %s",
                        response,
                        response.text
                        if hasattr(response, "text")
                        else "No response text",
                    )
                    try:
                        error_payload = response.json()
                    except ValueError:
                        error_payload = (
                            response.text
                            or f"Data process service error: {response.status_code}"
                        )
                    return _data_process_error_result(
                        error_payload, legacy_code=response.status_code
                    )
            except httpx.RequestError as e:
                logger.error("Failed to connect to data process service: %s", str(e))
                return _data_process_error_result(e)

        else:
            # Batch file request
            sources = []
            for file_details in files:
                source = {
                    "source": file_details.get("path_or_url"),
                    "source_type": process_params.source_type,
                    "chunking_strategy": process_params.chunking_strategy,
                    "index_name": process_params.index_name,
                    "original_filename": file_details.get("filename"),
                    "file_id": file_details.get("file_id"),
                    "embedding_model_id": embedding_model_id,
                    "tenant_id": tenant_id,
                }
                source["telemetry_context"] = telemetry_context
                sources.append(source)

            payload = {"sources": sources}

            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{DATA_PROCESS_SERVICE}/tasks/batch",
                        headers=headers,
                        json=payload,
                        timeout=30.0,
                    )

                if response.status_code == 201:
                    set_span_attributes(stage="process.submitted")
                    return response.json()
                else:
                    logger.error(
                        "Error from data process service: %s - %s",
                        response,
                        response.text
                        if hasattr(response, "text")
                        else "No response text",
                    )
                    try:
                        error_payload = response.json()
                    except ValueError:
                        error_payload = (
                            response.text
                            or f"Data process service error: {response.status_code}"
                        )
                    return _data_process_error_result(
                        error_payload, legacy_code=response.status_code
                    )
            except httpx.RequestError as e:
                logger.error("Failed to connect to data process service: %s", str(e))
                return _data_process_error_result(e)
    except Exception as e:
        logger.error("Error triggering data process: %s", str(e))
        return _data_process_error_result(e)
