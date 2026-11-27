# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Northbound Web-layer primitives shared by every service exposing /nb routes.

The lane policy (path to credential kind), the published partner envelope and
the per-tenant rate limiter are transport concerns used by both the
management gates and the ops ``/nb`` mirror. They live in the shared Web
layer so a service never imports another service's source to expose
northbound routes: the ops container ships a curated module whitelist, and
management-only modules are not on it. The shared layer must not import
business source; only contracts and optional infrastructure adapters.
"""

import asyncio
import logging
import time
from typing import Any

from contracts.authentication import CredentialKind
from contracts.constants.constants import NORTHBOUND_PATH_PREFIX
from contracts.constants.environment import (
    NORTHBOUND_RATE_LIMIT_ENABLED,
    NORTHBOUND_RATE_LIMIT_PER_MINUTE,
)
from contracts.errors.exceptions import LimitExceededError

logger = logging.getLogger(__name__)

SUCCESS_MESSAGE = "success"


def is_northbound_path(path: str) -> bool:
    """Whether a request path belongs to the public northbound namespace."""
    normalized = path or ""
    return normalized == NORTHBOUND_PATH_PREFIX or normalized.startswith(f"{NORTHBOUND_PATH_PREFIX}/")


def credential_kind_for_path(path: str) -> CredentialKind:
    """Select the credential policy from the path, never from unverified claims."""
    return CredentialKind.API_KEY if is_northbound_path(path) else CredentialKind.SESSION


def northbound_envelope(data: Any = None, request_id: str = "", message: str = SUCCESS_MESSAGE) -> dict:
    """Build the northbound ``{message, data, requestId}`` envelope."""
    return {"message": message, "data": data, "requestId": request_id}


# In-memory rate limit fallback for deployments without the Redis state
# adapter (not shipped or not configured); the limit then applies per process.
_RATE_STATE: dict[str, dict[str, int]] = {}
_RATE_LOCK = asyncio.Lock()


def _now_seconds() -> float:
    return time.time()


def _minute_bucket(ts: float | None = None) -> str:
    t = int((ts or _now_seconds()) // 60)
    return str(t)


async def check_and_consume_rate_limit(tenant_id: str) -> None:
    """Consume one request from the tenant's per-minute northbound budget.

    Redis-backed when the shared runtime state adapter is available and
    enabled; an in-memory minute bucket otherwise. Raises
    ``LimitExceededError`` (mapped to HTTP 429) when the budget is exhausted
    or the accounting backend fails.
    """
    if not NORTHBOUND_RATE_LIMIT_ENABLED:
        return

    runtime_state_service = None
    try:
        from infrastructure.redis.run_state import (
            runtime_state_service,  # lazy: optional adapter
        )
    except ImportError:
        logger.warning("Redis state adapter unavailable; northbound rate limit is per process")

    if runtime_state_service is not None and runtime_state_service.enabled:
        try:
            await runtime_state_service.consume_rate_limit_async(
                tenant_id=tenant_id,
                limit_per_minute=NORTHBOUND_RATE_LIMIT_PER_MINUTE,
            )
            return
        except ValueError:
            raise LimitExceededError("Query rate exceeded limit. Please try again later")
        except Exception:
            logger.exception("Northbound rate limit Redis operation failed")
            raise LimitExceededError("Rate limit service is unavailable. Please try again later")

    bucket = _minute_bucket()
    async with _RATE_LOCK:
        state = _RATE_STATE.setdefault(tenant_id, {})
        count = state.get(bucket, 0)
        if count >= NORTHBOUND_RATE_LIMIT_PER_MINUTE:
            raise LimitExceededError("Query rate exceeded limit. Please try again later")
        state[bucket] = count + 1
        # cleanup old buckets, keep only current
        for b in list(state.keys()):
            if b != bucket:
                state.pop(b, None)
