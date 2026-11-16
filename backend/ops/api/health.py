# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Process health endpoints that never query external dependencies."""

from fastapi import APIRouter, Request, Response, status

router = APIRouter(prefix='/health', include_in_schema=False)


@router.get('/live')
async def live() -> dict[str, str]:
    """Report that the process can handle an HTTP request."""
    return {'status': 'alive'}


@router.get('/ready')
async def ready(request: Request, response: Response) -> dict[str, str]:
    """Report readiness only after local startup and before shutdown."""
    if not getattr(request.app.state, 'ready', False):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {'status': 'not_ready'}
    return {'status': 'ready'}
