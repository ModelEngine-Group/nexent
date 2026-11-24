# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Sample REST endpoint that returns the current time for OpenAPI→MCP conversion demo."""

from datetime import datetime, timezone

from fastapi import APIRouter


router = APIRouter(prefix="/dev/clock", tags=["sample"])


@router.get("/current")
def get_current_time(use_utc: bool = True) -> dict:
    """Return the current time with an optional timezone switch.

    This endpoint is intentionally simple so that it can be wrapped as an
    MCP tool via the platform's OpenAPI→MCP conversion pipeline.
    """
    if use_utc:
        now = datetime.now(timezone.utc)
        tz_name = "UTC"
    else:
        now = datetime.now().astimezone()
        tz_name = now.tzname() or "local"
    unix = int(now.timestamp())
    return {
        "time": now.isoformat(),
        "timezone": tz_name,
        "unix": unix,
        "utc": use_utc,
    }


__all__ = ["router", "get_current_time"]
