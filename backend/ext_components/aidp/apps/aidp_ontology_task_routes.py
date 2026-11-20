# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AIDP background task routes."""
from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse
from nexent.core.concurrency import run_blocking

from ext_components.aidp.apps.aidp_mgmt_common import _auth, _credentials
from ext_components.aidp.services.aidp_ontology_task_service import (
    get_task_impl,
    list_tasks_impl,
)


logger = logging.getLogger("aidp_ontology_task_routes")
aidp_ontology_task_router = APIRouter()


@aidp_ontology_task_router.get("/tasks")
async def list_aidp_tasks(
    request: Request,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    task_type: Annotated[str | None, Query(max_length=64)] = None,
) -> JSONResponse:
    await _auth(request)
    server_url, api_key = _credentials()
    envelope = await run_blocking(
        "aidp-task-list",
        list_tasks_impl,
        server_url,
        api_key,
        page=page,
        page_size=page_size,
        task_type=task_type,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=envelope)


@aidp_ontology_task_router.get("/tasks/{task_id}")
async def get_aidp_task(
    request: Request,
    task_id: Annotated[str, Path(..., min_length=1, max_length=64)],
) -> JSONResponse:
    await _auth(request)
    server_url, api_key = _credentials()
    result = await run_blocking(
        "aidp-task-get",
        get_task_impl,
        server_url,
        api_key,
        task_id,
        lane="control-io",
        owner="config",
    )
    return JSONResponse(status_code=HTTPStatus.OK, content=result)

