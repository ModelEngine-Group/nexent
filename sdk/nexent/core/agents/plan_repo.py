"""Plan persistence layer: Redis primary + local memory fallback.

SDK internal use only. Redis client is passed in from the backend
(via AgentRunInfo), not created from environment variables.
"""

import json
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)


class PlanRepo:
    """Stores agent plans in Redis with local memory fallback."""

    PLAN_KEY_PREFIX = "plan"
    DEFAULT_TTL_SECONDS = 86400  # 24 hours

    def __init__(
        self,
        redis_client=None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ):
        """
        Args:
            redis_client: redis.Redis instance. If None, uses local memory only.
            ttl_seconds: TTL for plan keys in Redis.
        """
        self._redis = redis_client
        self._ttl = ttl_seconds
        self._local: dict[str, dict] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _make_key(conversation_id: int, user_id: str) -> str:
        return f"{conversation_id}:{user_id}"

    @staticmethod
    def _make_redis_key(conversation_id: int, user_id: str) -> str:
        return f"plan:{conversation_id}:{user_id}"

    def save(
        self,
        plan_dict: dict,
        conversation_id: int,
        user_id: str,
        status: str = "active",
    ) -> None:
        """Persist a plan. Writes to Redis if available, otherwise local memory."""
        key = self._make_key(conversation_id, user_id)
        with self._lock:
            self._local[key] = plan_dict

        if self._redis is not None:
            try:
                self._redis.setex(
                    self._make_redis_key(conversation_id, user_id),
                    self._ttl,
                    json.dumps(plan_dict, ensure_ascii=False),
                )
            except Exception as e:
                logger.warning(f"Redis save failed, using local memory: {e}")

    def load(self, conversation_id: int, user_id: str) -> Optional[dict]:
        """Load a plan. Tries Redis first, falls back to local memory."""
        key = self._make_key(conversation_id, user_id)

        if self._redis is not None:
            try:
                data = self._redis.get(self._make_redis_key(conversation_id, user_id))
                if data:
                    plan = json.loads(data)
                    with self._lock:
                        self._local[key] = plan
                    return plan
            except Exception as e:
                logger.warning(f"Redis load failed, falling back to local memory: {e}")

        with self._lock:
            return self._local.get(key)

    def delete(
        self,
        conversation_id: int,
        user_id: str,
        status: str = "completed",
    ) -> None:
        """Delete a plan from both Redis and local memory."""
        key = self._make_key(conversation_id, user_id)

        with self._lock:
            self._local.pop(key, None)

        if self._redis is not None:
            try:
                self._redis.delete(self._make_redis_key(conversation_id, user_id))
            except Exception as e:
                logger.warning(f"Redis delete failed: {e}")

    def update_step(
        self,
        conversation_id: int,
        user_id: str,
        step_id: str,
        status: str,
    ) -> None:
        """Update a single step's status within a stored plan."""
        plan = self.load(conversation_id, user_id)
        if plan is None:
            return
        for step in plan.get("steps", []):
            if step.get("id") == step_id:
                step["status"] = status
                break
        self.save(plan, conversation_id, user_id, status="active")
