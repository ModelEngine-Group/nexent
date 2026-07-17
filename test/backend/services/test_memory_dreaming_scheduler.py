"""Unit tests for ``backend.services.memory_dreaming_scheduler`` (Phase 2)."""

import sys
import types
from datetime import datetime
from unittest.mock import MagicMock

import pytest


# Path setup
sys.path.insert(
    0,
    __import__("os").path.join(__import__("os").path.dirname(__file__), "../../.."),
)


# Stub consts
consts_pkg = types.ModuleType("consts")
consts_pkg.AGENT_SHORT_TERM_HALF_LIFE_DAYS = 14
consts_pkg.LIGHT_SLEEP_WINDOW_DAYS = 7
consts_pkg.MIN_PROMOTION_SCORE = 0.72
consts_pkg.MIN_RECALL_COUNT = 3
consts_pkg.MIN_UNIQUE_QUERIES = 2
consts_pkg.RECENCY_HALF_LIFE_DAYS = 14
consts_mod = types.ModuleType("consts.const")
for name, value in vars(consts_pkg).items():
    if not name.startswith("_"):
        setattr(consts_mod, name, value)
sys.modules["consts"] = types.ModuleType("consts")
sys.modules["consts.const"] = consts_mod


# Stub database
database_pkg = types.ModuleType("database")
database_pkg.memory_record_db = MagicMock(name="memory_record_db")
database_pkg.memory_retrieval_hit_db = MagicMock(name="memory_retrieval_hit_db")
sys.modules["database"] = database_pkg
sys.modules["backend.database"] = database_pkg


# Stub services.memory_record_service
memory_record_service_mod = types.ModuleType("services.memory_record_service")
memory_record_service_mod.MemoryRecordError = type("MemoryRecordError", (Exception,), {})


class _RecordService:
    pass


memory_record_service_mod.MemoryRecordService = _RecordService
memory_record_service_mod.get_memory_record_service = MagicMock(
    name="get_memory_record_service"
)
sys.modules["services.memory_record_service"] = memory_record_service_mod


from backend.services import memory_dreaming_scheduler


def test_compute_promotion_score_no_signal():
    score = memory_dreaming_scheduler.compute_promotion_score({})
    assert 0.0 <= score <= 1.0


def test_compute_promotion_score_increases_with_recall():
    low = memory_dreaming_scheduler.compute_promotion_score(
        {"recall_count": 1, "daily_count": 1, "grounded_count": 1, "light_hits": 0,
         "rem_hits": 0, "last_recalled_at": datetime.utcnow(), "concept_tags": [],
         "query_hashes": []}
    )
    high = memory_dreaming_scheduler.compute_promotion_score(
        {"recall_count": 12, "daily_count": 5, "grounded_count": 4,
         "light_hits": 3, "rem_hits": 3,
         "last_recalled_at": datetime.utcnow(), "concept_tags": ["python"],
         "query_hashes": ["a", "b", "c", "d", "e"]}
    )
    assert high > low


def test_run_light_sleep_aggregates_into_rows():
    memory_dreaming_scheduler.memory_retrieval_hit_db.aggregate_memory_stats.return_value = [
        {
            "memory_id": 1,
            "hit_count": 5,
            "grounded_count": 2,
            "days": {"2026-07-13", "2026-07-12"},
            "query_hashes": {"q1", "q2"},
        }
    ]
    memory_dreaming_scheduler.memory_record_db.update_memory_record.return_value = True
    memory_dreaming_scheduler.memory_record_db.apply_dreaming_phase.return_value = True

    touched = memory_dreaming_scheduler.run_light_sleep(
        tenant_id="t1", user_id="u1"
    )

    assert touched == 1
    memory_dreaming_scheduler.memory_record_db.update_memory_record.assert_called_once()
    memory_dreaming_scheduler.memory_record_db.apply_dreaming_phase.assert_called_once_with(
        1, "t1", phase="light"
    )


def test_run_rem_sleep_writes_concept_tags():
    memory_dreaming_scheduler.memory_record_db.list_memory_records.return_value = [
        {
            "memory_id": 1,
            "tenant_id": "t1",
            "user_id": "u1",
            "content": "Python Python Java Python Java C++",
            "layer": "agent",
            "memory_type": "short_term",
            "concept_tags": [],
        }
    ]
    memory_dreaming_scheduler.memory_record_db.update_memory_record.return_value = True
    memory_dreaming_scheduler.memory_record_db.apply_dreaming_phase.return_value = True

    touched = memory_dreaming_scheduler.run_rem_sleep(
        tenant_id="t1", user_id="u1"
    )

    assert touched == 1
    # Update payload should carry the new tags.
    update_call = memory_dreaming_scheduler.memory_record_db.update_memory_record.call_args
    payload = update_call.args[2]
    assert "python" in payload["concept_tags"]
    assert "java" in payload["concept_tags"]


def test_run_deep_sleep_skips_low_signal():
    memory_dreaming_scheduler.memory_record_db.list_memories_for_dreaming.return_value = [
        {
            "memory_id": 1,
            "content": "low signal",
            "layer": "agent",
            "recall_count": 1,
            "daily_count": 0,
            "grounded_count": 0,
            "query_hashes": ["q1"],
            "concept_tags": [],
            "last_recalled_at": datetime.utcnow(),
            "light_hits": 0,
            "rem_hits": 0,
        }
    ]
    memory_record_service_mod.get_memory_record_service.return_value.create_memory.return_value = {
        "memory_id": 999,
        "event": "ADD",
    }

    promoted = memory_dreaming_scheduler.run_deep_sleep(
        tenant_id="t1", user_id="u1", min_score=0.99
    )

    assert promoted == []
    memory_record_service_mod.get_memory_record_service.return_value.create_memory.assert_not_called()


def test_run_deep_sleep_promotes_high_signal():
    memory_dreaming_scheduler.memory_record_db.list_memories_for_dreaming.return_value = [
        {
            "memory_id": 1,
            "content": "user prefers dark mode",
            "layer": "agent",
            "recall_count": 8,
            "daily_count": 4,
            "grounded_count": 2,
            "query_hashes": ["q1", "q2", "q3"],
            "concept_tags": ["preference"],
            "last_recalled_at": datetime.utcnow(),
            "light_hits": 2,
            "rem_hits": 1,
            "agent_id": "a1",
            "conversation_id": "c1",
        }
    ]
    memory_record_service_mod.get_memory_record_service.return_value.create_memory.return_value = {
        "memory_id": 999,
        "event": "ADD",
    }
    memory_dreaming_scheduler.memory_record_db.apply_dreaming_phase.return_value = True

    promoted = memory_dreaming_scheduler.run_deep_sleep(
        tenant_id="t1", user_id="u1", min_score=0.5
    )

    assert len(promoted) == 1
    create_kwargs = memory_record_service_mod.get_memory_record_service.return_value.create_memory.call_args.kwargs
    assert create_kwargs["layer"] == "user"
    assert create_kwargs["memory_type"] == "long_term"
    assert create_kwargs["actor"] == "dreaming"