# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Signed reverse FileCleanse admission, inspection and cancellation."""

import asyncio
import logging
from time import monotonic
from uuid import uuid4

from contracts.agentos import ManagementOperation
from contracts.agentos_knowledge import FileCleanseLookup, FileCleanseRequest
from contracts.constants import environment
from fastapi import APIRouter, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from management.api.agentos_request import read_agentos_callback
from management.services.file.run_cleanse_service import FileCleanseService
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import DeadlineExceeded
from nexent.storage.models import OperationContext
from starlette.responses import JSONResponse

from backend.http.server.knowledge_errors import knowledge_error

logger = logging.getLogger(__name__)
_DEADLINE_SECONDS = 10


def create_file_cleanse_router(service=None):
    service = service if service is not None else FileCleanseService(parser_version=environment.APP_VERSION + "-cleanse-v2")
    router = APIRouter()

    async def dispatch(request, operation, schema, action, status):
        context = OperationContext("file-cleanse-" + uuid4().hex, monotonic() + _DEADLINE_SECONDS)
        try:
            async with asyncio.timeout(context.remaining()):
                payload, actor = await read_agentos_callback(request, operation, schema, max_bytes=16384)
                state = await run_blocking(
                    "agentos-file-cleanse", action, payload, tenant_id=actor.tenant_id, user_id=actor.user_id,
                    context=context, lane="control-io", owner="management.file_cleanse",
                )
                return JSONResponse(jsonable_encoder(state), status_code=status)
        except HTTPException:
            raise
        except TimeoutError:
            logger.warning("file_cleanse_timeout phase=records threshold_seconds=%s", _DEADLINE_SECONDS)
            return knowledge_error(DeadlineExceeded(operation_id=context.operation_id), prefix="FILE_CLEANSE")
        except Exception as error:  # noqa: BLE001 - The HTTP boundary must redact unexpected failures.
            return knowledge_error(error, prefix="FILE_CLEANSE")

    @router.post(ManagementOperation.FILE_CLEANSE.value, include_in_schema=False)
    async def submit(request: Request):
        return await dispatch(request, ManagementOperation.FILE_CLEANSE, FileCleanseRequest, service.submit, 202)

    @router.post(ManagementOperation.FILE_CLEANSE_STATUS.value, include_in_schema=False)
    async def inspect(request: Request):
        return await dispatch(request, ManagementOperation.FILE_CLEANSE_STATUS, FileCleanseLookup, service.inspect, 200)

    @router.post(ManagementOperation.FILE_CLEANSE_CANCEL.value, include_in_schema=False)
    async def cancel(request: Request):
        return await dispatch(request, ManagementOperation.FILE_CLEANSE_CANCEL, FileCleanseLookup, service.cancel, 200)

    @router.post(ManagementOperation.FILE_CLEANSE_RELEASE.value, include_in_schema=False)
    async def release(request: Request):
        return await dispatch(request, ManagementOperation.FILE_CLEANSE_RELEASE, FileCleanseLookup, service.release, 200)

    return router
