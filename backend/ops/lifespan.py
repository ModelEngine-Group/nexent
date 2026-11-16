# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Own process-local operations startup and shutdown."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI


@asynccontextmanager
async def ops_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Keep readiness aligned with the application lifetime."""
    app.state.ready = True
    try:
        yield
    finally:
        app.state.ready = False
