"""Reusable Redis client singleton with lazy initialization and connection pooling."""

import logging
import threading
from typing import Optional

import redis

from consts.const import REDIS_BACKEND_URL

logger = logging.getLogger("redis_utils")

_redis_pool: Optional[redis.ConnectionPool] = None
_redis_client: Optional[redis.Redis] = None
_init_lock = threading.Lock()
_initialized = False


def _ensure_initialized() -> None:
    global _redis_pool, _redis_client, _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        _redis_pool = None
        _redis_client = None
        if not REDIS_BACKEND_URL:
            logger.warning("REDIS_BACKEND_URL not set, Redis client unavailable.")
            _initialized = True
            return
        try:
            _redis_pool = redis.ConnectionPool.from_url(
                REDIS_BACKEND_URL,
                max_connections=50,
                decode_responses=True,
            )
            _redis_client = redis.Redis(connection_pool=_redis_pool)
            _redis_client.ping()
            logger.info("Redis client singleton initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize Redis client singleton: {e}")
            _redis_pool = None
            _redis_client = None
        _initialized = True


def get_redis_client() -> Optional[redis.Redis]:
    """Get the shared Redis client instance.

    Returns:
        redis.Redis instance if available, None if REDIS_BACKEND_URL is not configured
        or initialization failed.
    """
    _ensure_initialized()
    return _redis_client


def is_redis_available() -> bool:
    """Check whether Redis is available (configured and reachable)."""
    _ensure_initialized()
    return _redis_client is not None
