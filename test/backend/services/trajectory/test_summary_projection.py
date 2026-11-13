# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Projection arithmetic stays separate from database and archive collaborators."""

from unittest.mock import Mock

import pytest


def test_projection_keeps_zero_and_unknown_categories_separate():
    from management.services.trajectory.projection import execution_values

    run = {
        "trajectory_id": "00000000-0000-0000-0000-000000000001",
        "turn_no": 2,
        "root_agent_id": "7",
        "root_agent_version_no": 0,
        "capture_state": "ready",
        "business_status": "completed",
        "started_at": "2026-11-13T00:00:00Z",
        "finished_at": "2026-11-13T00:00:01Z",
        "publication_no": 2,
    }
    nodes = [
        {"id": "root", "kind": "agent", "duration_ms": 1000},
        {
            "id": "a",
            "kind": "model",
            "model": "m",
            "usage": {"input": 0, "output": 2, "total": 2},
        },
        {
            "id": "b",
            "kind": "model",
            "model": "m",
            "usage": {"input": None, "output": 3, "total": None},
        },
    ]
    result = execution_values("1", run, nodes, "root")
    assert result["models"] == ["m"]
    assert (
        result["input_tokens"] is None
        and result["output_tokens"] == 5
        and result["total_tokens"] is None
    )
    assert result["duration_ms"] == 1000 and result["agent_version_no"] == 0
    run["capture_state"] = "expired"
    assert execution_values("1", run, nodes, "root")["status"] == "expired"


def test_projection_rejects_model_overflow():
    from management.services.trajectory.projection import model_names

    with pytest.raises(ValueError):
        model_names([{"kind": "model", "model": "x" * 101}])
    with pytest.raises(ValueError):
        model_names([{"kind": "model", "model": str(i)} for i in range(1001)])


def test_records_never_open_files_and_freeze_pages():
    from management.services.trajectory.access import Actor
    from management.services.trajectory.cache import ByteCache
    from management.services.trajectory.pg_collection import records
    from management.services.trajectory.primitives import ReferenceStore

    service = Mock()
    service.references = ReferenceStore()
    service.queries = ByteCache(1024 * 1024)
    service.max_candidates = 1000
    service.catalog.names.return_value = {}
    service.catalog.agent_names.return_value = {}
    service.catalog.tenants.return_value = ["t"]
    service.catalog.actor_active.return_value = True
    service.execution_catalog.list_records.return_value = [
        {
            "conversation_id": "1",
            "tenant_id": "t",
            "user_id": "u",
            "_runs": [],
            "started_at": None,
        },
        {
            "conversation_id": "2",
            "tenant_id": "t",
            "user_id": "u",
            "_runs": [],
            "started_at": None,
        },
    ]
    service.execution_catalog.statistics.return_value = {
        "complete": False,
        "computed_at": None,
    }
    actor = Actor("admin", "t", "ADMIN")
    first = records(service, actor, {}, view="conversation", page_size=1)
    service.execution_catalog.list_records.return_value = []
    second = records(
        service,
        actor,
        {},
        view="conversation",
        query_id=first["query_id"],
        page=2,
        page_size=1,
    )
    assert (
        first["total"] == second["total"] == 2
        and second["items"][0]["conversation_id"] == "2"
    )
    service.archive.manifest.assert_not_called()
    service.load.assert_not_called()
    service.execution_catalog.list_records.assert_called_once()
    service.execution_catalog.statistics.assert_called_with(["t"], global_scope=False)


@pytest.mark.parametrize("values", [[], [0], [0, 10, 20], list(range(1000))])
def test_disk_quantiles_match_exact_interpolation_and_release_files(values):
    from management.services.trajectory.primitives import percentiles
    from management.services.trajectory.quantiles import DiskQuantiles

    with DiskQuantiles(chunk_size=3) as calculator:
        folder = calculator.root
        for value in reversed(values):
            calculator.add(value)
        assert calculator.result() == percentiles(values)
    assert not folder.exists()


def test_disk_quantiles_cancel_removes_owned_files():
    from management.services.trajectory.quantiles import DiskQuantiles

    def cancelled():
        raise InterruptedError("controlled")

    with (
        pytest.raises(InterruptedError),
        DiskQuantiles(cancelled, chunk_size=2) as calculator,
    ):
        folder = calculator.root
        calculator.add(1)
        calculator.add(2)
    assert not folder.exists()


def test_projection_schema_only_has_approved_business_fields():
    from management.db.trajectory.models import (
        TrajectoryExecution,
        TrajectoryStatistics,
    )

    audit = {"created_by", "updated_by", "create_time", "update_time", "delete_flag"}
    assert set(TrajectoryExecution.__table__.columns.keys()) - audit == {
        "trajectory_id",
        "conversation_id",
        "turn_no",
        "agent_id",
        "agent_version_no",
        "models",
        "status",
        "started_at",
        "finished_at",
        "duration_ms",
        "input_tokens",
        "output_tokens",
        "total_tokens",
    }
    assert len(TrajectoryExecution.__table__.primary_key.columns) == 1
    assert "ttft_sample_count" in TrajectoryStatistics.__table__.columns
    assert not any(index.unique for index in TrajectoryExecution.__table__.indexes)


def test_pg_queries_aggregate_nulls_match_same_execution_and_search_conversation_only(
    mocker,
):
    from contextlib import contextmanager

    from management.db.trajectory.queries import ExecutionCatalog

    session = Mock()
    session.execute.return_value.mappings.return_value.all.return_value = []

    @contextmanager
    def scoped():
        yield session

    mocker.patch("management.db.trajectory.queries._session", scoped)
    result = ExecutionCatalog().list_records(
        ["t"],
        {"id_query": " 12 ", "agent_id": "7", "model": "m", "status": "error"},
        view="conversation",
        limit=20,
        sort_by="duration_ms",
        sort_order="desc",
    )
    assert result == []
    statement, params = session.execute.call_args.args
    sql = str(statement)
    assert "CAST(b.conversation_id AS varchar) LIKE :id_query" in sql
    assert "l.status = :status" in sql and "g.matches" in sql
    assert "b.agent_id = :agent_id AND b.models @> ARRAY[:model]::varchar(100)[]" in sql
    assert "count(input_tokens) FILTER" in sql and "THEN sum(input_tokens)" in sql
    assert params["id_query"] == "%12%" and "trace" not in params


def test_same_scope_statistics_survive_filters_and_reset_rejects_removed_members(
    mocker,
):
    from management.services.trajectory.access import Actor
    from management.services.trajectory.cache import ByteCache
    from management.services.trajectory.pg_collection import records
    from management.services.trajectory.primitives import QueryError, ReferenceStore

    service = Mock(max_candidates=100)
    service.references = ReferenceStore()
    service.queries = ByteCache()
    service.catalog.actor_active.return_value = True
    service.catalog.tenants.return_value = ["t"]
    service.catalog.names.return_value = {}
    service.catalog.agent_names.return_value = {}
    service.execution_catalog.list_records.return_value = []
    service.execution_catalog.statistics.return_value = {
        "complete": True,
        "conversation_count": 30,
    }
    first = records(
        service, Actor("a", "t", "ADMIN"), {"model": "unknown"}, view="conversation"
    )
    assert first["total"] == 0 and first["summary"]["conversation_count"] == 30
    service.execution_catalog.validate.side_effect = QueryError("snapshot_reset", 409)
    with pytest.raises(QueryError, match="snapshot_reset"):
        records(
            service,
            Actor("a", "t", "ADMIN"),
            {"model": "unknown"},
            view="conversation",
            query_id=first["query_id"],
        )


def test_list_rechecks_administrator_permission_before_returning_statistics():
    from management.services.trajectory.access import Actor
    from management.services.trajectory.cache import ByteCache
    from management.services.trajectory.pg_collection import records
    from management.services.trajectory.primitives import QueryError, ReferenceStore

    service = Mock(max_candidates=100)
    service.references = ReferenceStore()
    service.queries = ByteCache()
    service.catalog.actor_active.side_effect = [True, False]
    service.catalog.tenants.return_value = ["t"]
    service.catalog.names.return_value = {}
    service.catalog.agent_names.return_value = {}
    service.execution_catalog.list_records.return_value = []
    service.execution_catalog.statistics.return_value = {}
    with pytest.raises(QueryError) as caught:
        records(service, Actor("admin", "t", "ADMIN"), {}, view="conversation")
    assert caught.value.status == 403
