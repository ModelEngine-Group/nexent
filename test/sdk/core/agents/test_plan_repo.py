"""Unit tests for sdk.nexent.core.agents.plan_repo.

PlanRepo is a pure stdlib module: it persists plans to Redis (when a client
is provided) and always mirrors them to a thread-local in-memory dict as a
fallback. We test the memory path, the Redis path, and the degradation
behaviour on Redis failures.
"""

import importlib.util
import json
import sys
import threading
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]


def _pkg(name, path):
    mod = types.ModuleType(name)
    mod.__path__ = [str(path)]
    sys.modules.setdefault(name, mod)
    return mod


sdk_pkg = _pkg("sdk", REPO_ROOT / "sdk")
nexent_pkg = _pkg("sdk.nexent", REPO_ROOT / "sdk" / "nexent")
core_pkg = _pkg("sdk.nexent.core", REPO_ROOT / "sdk" / "nexent" / "core")
agents_pkg = _pkg("sdk.nexent.core.agents", REPO_ROOT / "sdk" / "nexent" / "core" / "agents")

sdk_pkg.nexent = nexent_pkg
nexent_pkg.core = core_pkg
core_pkg.agents = agents_pkg


MODULE_PATH = REPO_ROOT / "sdk" / "nexent" / "core" / "agents" / "plan_repo.py"
MODULE_NAME = "sdk.nexent.core.agents.plan_repo"
spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
plan_repo_module = importlib.util.module_from_spec(spec)
sys.modules[MODULE_NAME] = plan_repo_module
assert spec and spec.loader
spec.loader.exec_module(plan_repo_module)
agents_pkg.plan_repo = plan_repo_module

PlanRepo = plan_repo_module.PlanRepo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample_plan(plan_id="plan-1", step_count=3):
    return {
        "plan_id": plan_id,
        "title": "Sample",
        "current_step_index": 0,
        "steps": [
            {"id": f"step-{i}", "title": f"S{i}", "description": f"D{i}", "status": "pending"}
            for i in range(1, step_count + 1)
        ],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPlanRepoLocalOnly:
    """No Redis client: writes/reads/deletes go through the in-memory dict."""

    def test_save_then_load_roundtrip(self):
        repo = PlanRepo(redis_client=None)
        plan = _sample_plan()
        repo.save(plan, conversation_id=1, user_id="alice")
        loaded = repo.load(conversation_id=1, user_id="alice")
        assert loaded == plan

    def test_load_missing_returns_none(self):
        repo = PlanRepo(redis_client=None)
        assert repo.load(conversation_id=999, user_id="ghost") is None

    def test_save_overwrites(self):
        repo = PlanRepo(redis_client=None)
        repo.save(_sample_plan(plan_id="v1"), 1, "u")
        repo.save(_sample_plan(plan_id="v2"), 1, "u")
        assert repo.load(1, "u")["plan_id"] == "v2"

    def test_separate_keys_isolated(self):
        repo = PlanRepo(redis_client=None)
        repo.save(_sample_plan(plan_id="a"), 1, "u1")
        repo.save(_sample_plan(plan_id="b"), 1, "u2")
        repo.save(_sample_plan(plan_id="c"), 2, "u1")
        assert repo.load(1, "u1")["plan_id"] == "a"
        assert repo.load(1, "u2")["plan_id"] == "b"
        assert repo.load(2, "u1")["plan_id"] == "c"

    def test_delete_removes_from_memory(self):
        repo = PlanRepo(redis_client=None)
        repo.save(_sample_plan(), 1, "u")
        repo.delete(1, "u")
        assert repo.load(1, "u") is None

    def test_delete_missing_is_silent(self):
        repo = PlanRepo(redis_client=None)
        # Should not raise
        repo.delete(99, "ghost")

    def test_update_step_changes_status_and_persists(self):
        repo = PlanRepo(redis_client=None)
        repo.save(_sample_plan(), 1, "u")
        repo.update_step(1, "u", "step-2", "completed")
        loaded = repo.load(1, "u")
        statuses = {s["id"]: s["status"] for s in loaded["steps"]}
        assert statuses["step-2"] == "completed"
        # Other steps unchanged
        assert statuses["step-1"] == "pending"
        assert statuses["step-3"] == "pending"

    def test_update_step_missing_plan_is_noop(self):
        repo = PlanRepo(redis_client=None)
        # Should not raise
        repo.update_step(1, "ghost", "step-1", "completed")

    def test_update_step_missing_id_is_noop(self):
        repo = PlanRepo(redis_client=None)
        repo.save(_sample_plan(), 1, "u")
        repo.update_step(1, "u", "step-99", "completed")
        loaded = repo.load(1, "u")
        assert all(s["status"] == "pending" for s in loaded["steps"])

    def test_make_key_format(self):
        assert PlanRepo._make_key(7, "alice") == "7:alice"

    def test_redis_key_format(self):
        assert PlanRepo._make_redis_key(7, "alice") == "plan:7:alice"


class TestPlanRepoRedis:
    """Redis client provided: writes also flow to Redis with TTL."""

    def test_save_writes_to_redis_with_ttl(self):
        redis = MagicMock()
        repo = PlanRepo(redis_client=redis, ttl_seconds=1234)
        plan = _sample_plan()
        repo.save(plan, conversation_id=1, user_id="alice")
        redis.setex.assert_called_once()
        key, ttl, payload = redis.setex.call_args.args
        assert key == "plan:1:alice"
        assert ttl == 1234
        assert json.loads(payload) == plan

    def test_load_prefers_redis(self):
        redis = MagicMock()
        plan = _sample_plan(plan_id="from-redis")
        redis.get.return_value = json.dumps(plan, ensure_ascii=False)
        repo = PlanRepo(redis_client=redis)
        loaded = repo.load(1, "alice")
        assert loaded == plan
        redis.get.assert_called_once_with("plan:1:alice")

    def test_load_redis_misses_falls_back_to_memory(self):
        redis = MagicMock()
        redis.get.return_value = None
        repo = PlanRepo(redis_client=redis)
        repo.save(_sample_plan(plan_id="from-mem"), 1, "alice")
        loaded = repo.load(1, "alice")
        assert loaded["plan_id"] == "from-mem"

    def test_load_redis_failure_falls_back_to_memory(self):
        redis = MagicMock()
        redis.get.side_effect = ConnectionError("redis down")
        repo = PlanRepo(redis_client=redis)
        repo.save(_sample_plan(plan_id="from-mem"), 1, "alice")
        loaded = repo.load(1, "alice")
        assert loaded["plan_id"] == "from-mem"

    def test_redis_load_populates_memory(self):
        """When Redis has the plan, the result is also cached in local memory."""
        redis = MagicMock()
        plan = _sample_plan(plan_id="from-redis")
        redis.get.return_value = json.dumps(plan, ensure_ascii=False)
        repo = PlanRepo(redis_client=redis)
        repo.load(1, "alice")
        # Now disable Redis and load again -- should still hit memory
        repo._redis = None
        loaded = repo.load(1, "alice")
        assert loaded["plan_id"] == "from-redis"

    def test_save_redis_failure_falls_back_to_memory(self):
        redis = MagicMock()
        redis.setex.side_effect = ConnectionError("redis down")
        repo = PlanRepo(redis_client=redis)
        # Should not raise
        repo.save(_sample_plan(), 1, "alice")
        # Memory still has the plan
        assert repo.load(1, "alice") is not None

    def test_delete_calls_redis(self):
        redis = MagicMock()
        repo = PlanRepo(redis_client=redis)
        repo.save(_sample_plan(), 1, "alice")
        repo.delete(1, "alice")
        redis.delete.assert_called_once_with("plan:1:alice")

    def test_delete_redis_failure_is_swallowed(self):
        redis = MagicMock()
        redis.delete.side_effect = ConnectionError("redis down")
        repo = PlanRepo(redis_client=redis)
        # Should not raise
        repo.delete(1, "alice")

    def test_default_ttl(self):
        repo = PlanRepo(redis_client=MagicMock())
        assert repo._ttl == 86400


class TestPlanRepoThreadSafety:
    """PlanRepo._lock is shared across the same instance; concurrent saves must not corrupt memory."""

    def test_concurrent_saves(self):
        repo = PlanRepo(redis_client=None)
        errors = []

        def writer(i):
            try:
                for _ in range(50):
                    repo.save(_sample_plan(plan_id=f"plan-{i}"), 1, "u")
            except Exception as e:  # pragma: no cover - exercised on regression
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # Some plan must be present (last writer wins, but no corruption)
        assert repo.load(1, "u") is not None
