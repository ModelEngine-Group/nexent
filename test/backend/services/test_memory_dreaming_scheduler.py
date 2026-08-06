"""Unit tests for ``backend.services.memory_dreaming_scheduler`` (Phase 2)."""

import sys
import types
from datetime import datetime, timedelta
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


def test_scoring_helpers_cover_bounds_and_decay(mocker):
    assert memory_dreaming_scheduler._clamp01(-1.0) == 0.0
    assert memory_dreaming_scheduler._clamp01(2.0) == 1.0
    assert memory_dreaming_scheduler._clamp01(0.5) == 0.5
    assert memory_dreaming_scheduler._relevance(0, 10.0) == 0.0
    assert memory_dreaming_scheduler._relevance(2, 3.0) == 1.0
    assert memory_dreaming_scheduler._diversity(100) == 1.0
    assert memory_dreaming_scheduler._consolidation(0, 0) == 0.0
    assert memory_dreaming_scheduler._concept([]) == 0.0
    assert memory_dreaming_scheduler._phase_boost(0, 1) == 0.0
    assert memory_dreaming_scheduler._phase_boost(10, 10) == 0.05
    assert memory_dreaming_scheduler._normalize_weights({}) == {}

    future = datetime.utcnow() + timedelta(days=1)
    old = datetime.utcnow() - timedelta(days=14)
    assert memory_dreaming_scheduler._recency(future) == 1.0
    assert 0.49 < memory_dreaming_scheduler._recency(old) < 0.51
    assert memory_dreaming_scheduler._recency(None) == 0.0
    mocker.patch.object(memory_dreaming_scheduler, "RECENCY_HALF_LIFE_DAYS", 0)
    assert 0.0 < memory_dreaming_scheduler._recency(old) <= 1.0


def test_run_light_sleep_handles_empty_hit_days():
    memory_dreaming_scheduler.memory_retrieval_hit_db.aggregate_memory_stats.reset_mock()
    memory_dreaming_scheduler.memory_record_db.update_memory_record.reset_mock()
    memory_dreaming_scheduler.memory_record_db.apply_dreaming_phase.reset_mock()
    memory_dreaming_scheduler.memory_retrieval_hit_db.aggregate_memory_stats.return_value = [
        {
            "memory_id": 2,
            "hit_count": 1,
            "grounded_count": 0,
            "days": set(),
            "query_hashes": set(),
        }
    ]

    assert memory_dreaming_scheduler.run_light_sleep(
        tenant_id="t1", user_id="u1", window_days=0
    ) == 1
    payload = memory_dreaming_scheduler.memory_record_db.update_memory_record.call_args.args[2]
    assert payload["last_recalled_at"] is None
    assert payload["query_hashes"] == []
    assert payload["recall_days"] == []


def test_run_rem_sleep_skips_empty_content_and_merges_limited_tags():
    memory_dreaming_scheduler.memory_record_db.list_memory_records.reset_mock()
    memory_dreaming_scheduler.memory_record_db.update_memory_record.reset_mock()
    memory_dreaming_scheduler.memory_record_db.apply_dreaming_phase.reset_mock()
    memory_dreaming_scheduler.memory_record_db.list_memory_records.return_value = [
        {"memory_id": 1, "content": "the and"},
        {
            "memory_id": 2,
            "content": "Python Python Java Java Rust",
            "concept_tags": ["existing"],
        },
    ]

    assert memory_dreaming_scheduler.run_rem_sleep(
        tenant_id="t1", user_id="u1", max_keywords=2
    ) == 1
    payload = memory_dreaming_scheduler.memory_record_db.update_memory_record.call_args.args[2]
    assert payload["concept_tags"] == ["existing", "python"]
    memory_dreaming_scheduler.memory_record_db.apply_dreaming_phase.assert_called_once_with(
        2, "t1", phase="rem"
    )


def test_run_deep_sleep_skips_duplicate_queries_and_promotion_errors():
    memory_dreaming_scheduler.memory_record_db.list_memories_for_dreaming.reset_mock()
    memory_dreaming_scheduler.memory_record_db.apply_dreaming_phase.reset_mock()
    service = memory_record_service_mod.get_memory_record_service.return_value
    service.create_memory.reset_mock()
    service.create_memory.side_effect = memory_record_service_mod.MemoryRecordError(
        "already promoted"
    )
    memory_dreaming_scheduler.memory_record_db.list_memories_for_dreaming.return_value = [
        {
            "memory_id": 1,
            "query_hashes": ["same", "same"],
            "recall_count": 10,
        },
        {
            "memory_id": 2,
            "query_hashes": ["q1", "q2"],
            "recall_count": 10,
            "daily_count": 5,
            "grounded_count": 2,
            "concept_tags": ["tag"],
            "last_recalled_at": datetime.utcnow(),
            "light_hits": 2,
            "rem_hits": 2,
            "content": "promote me",
        },
    ]

    assert memory_dreaming_scheduler.run_deep_sleep(
        tenant_id="t1", user_id="u1", min_score=0.0, min_unique_queries=2
    ) == []
    service.create_memory.assert_called_once()
    memory_dreaming_scheduler.memory_record_db.apply_dreaming_phase.assert_not_called()


def test_run_once_aggregates_tenants_and_handles_iteration_errors(mocker):
    mocker.patch.object(
        memory_dreaming_scheduler, "list_distinct_tenants",
        return_value=[("t1", "u1"), ("t2", "u2")],
    )
    light = mocker.patch.object(
        memory_dreaming_scheduler, "run_light_sleep", side_effect=[2, RuntimeError("db")]
    )
    rem = mocker.patch.object(memory_dreaming_scheduler, "run_rem_sleep", return_value=3)
    deep = mocker.patch.object(
        memory_dreaming_scheduler, "run_deep_sleep",
        return_value=[{"memory_id": 8, "score": 0.8, "event": "PROMOTE"}],
    )

    summary = memory_dreaming_scheduler.run_once(timeout_seconds=60)

    assert summary["tenants"] == 2
    assert summary["light_rows"] == 2
    assert summary["rem_rows"] == 3
    assert summary["promotions"] == [{"memory_id": 8, "score": 0.8, "event": "PROMOTE"}]
    assert light.call_count == 2
    rem.assert_called_once_with(tenant_id="t1", user_id="u1")
    deep.assert_called_once_with(tenant_id="t1", user_id="u1")


def test_run_once_stops_before_work_when_deadline_reached(mocker):
    mocker.patch.object(
        memory_dreaming_scheduler, "list_distinct_tenants",
        return_value=[("t1", "u1")],
    )
    mocker.patch.object(
        memory_dreaming_scheduler.time, "time", side_effect=[100.0, 2000.0, 2000.0, 2000.0]
    )
    light = mocker.patch.object(memory_dreaming_scheduler, "run_light_sleep")

    summary = memory_dreaming_scheduler.run_once(timeout_seconds=1)

    assert summary["tenants"] == 1
    assert summary["light_rows"] == 0
    assert summary["rem_rows"] == 0
    assert summary["promotions"] == []
    light.assert_not_called()


def test_list_distinct_tenants_returns_filtered_pairs_and_handles_errors(monkeypatch):
    class Column:
        def isnot(self, value):
            return (self, value)

    class MemoryRetrievalHit:
        tenant_id = Column()
        user_id = Column()

    class Query:
        def filter(self, *conditions):
            self.conditions = conditions
            return self

        def all(self):
            return [("t1", "u1"), ("", "u2"), ("t2", None), ("t3", "u3")]

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def query(self, *columns):
            self.columns = columns
            return Query()

    client = types.ModuleType("database.client")
    client.get_db_session = lambda: Session()
    db_models = types.ModuleType("database.db_models")
    db_models.MemoryRetrievalHit = MemoryRetrievalHit
    sqlalchemy = types.ModuleType("sqlalchemy")
    sqlalchemy.distinct = lambda value: ("distinct", value)
    monkeypatch.setitem(sys.modules, "database.client", client)
    monkeypatch.setitem(sys.modules, "database.db_models", db_models)
    monkeypatch.setitem(sys.modules, "sqlalchemy", sqlalchemy)

    assert memory_dreaming_scheduler.list_distinct_tenants() == [("t1", "u1"), ("t3", "u3")]

    client.get_db_session = MagicMock(side_effect=RuntimeError("db unavailable"))
    assert memory_dreaming_scheduler.list_distinct_tenants() == []


def test_run_rem_sleep_skips_when_keyword_limit_is_zero():
    memory_dreaming_scheduler.memory_record_db.list_memory_records.reset_mock()
    memory_dreaming_scheduler.memory_record_db.update_memory_record.reset_mock()
    memory_dreaming_scheduler.memory_record_db.apply_dreaming_phase.reset_mock()
    memory_dreaming_scheduler.memory_record_db.list_memory_records.return_value = [
        {"memory_id": 3, "content": "python java"},
    ]

    assert memory_dreaming_scheduler.run_rem_sleep(
        tenant_id="t1", user_id="u1", max_keywords=0
    ) == 0
    memory_dreaming_scheduler.memory_record_db.update_memory_record.assert_not_called()
    memory_dreaming_scheduler.memory_record_db.apply_dreaming_phase.assert_not_called()


def test_run_deep_sleep_skips_record_below_score_threshold():
    memory_dreaming_scheduler.memory_record_db.list_memories_for_dreaming.reset_mock()
    memory_dreaming_scheduler.memory_record_db.apply_dreaming_phase.reset_mock()
    service = memory_record_service_mod.get_memory_record_service.return_value
    service.create_memory.reset_mock()
    memory_dreaming_scheduler.memory_record_db.list_memories_for_dreaming.return_value = [
        {
            "memory_id": 4,
            "query_hashes": ["q1", "q2"],
            "recall_count": 1,
            "daily_count": 0,
            "grounded_count": 0,
            "concept_tags": [],
            "last_recalled_at": None,
            "light_hits": 0,
            "rem_hits": 0,
        },
    ]

    assert memory_dreaming_scheduler.run_deep_sleep(
        tenant_id="t1", user_id="u1", min_score=0.99
    ) == []
    service.create_memory.assert_not_called()
    memory_dreaming_scheduler.memory_record_db.apply_dreaming_phase.assert_not_called()
