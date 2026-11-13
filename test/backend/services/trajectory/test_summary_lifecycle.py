# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Lifecycle, row serialization and publication are isolated from live PG."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from infrastructure.observability.trajectory_store import (
    CaptureIdentity,
    TrajectoryFileStore,
)


@pytest.fixture
def identity():
    return CaptureIdentity("t", "u", "123", "7")


def test_directory_lock_and_guard_are_shared_when_root_agent_changes(
    tmp_path, identity
):
    entries = []

    @contextmanager
    def guard(value):
        entries.append(value)
        yield

    store = TrajectoryFileStore(
        tmp_path, authorize=lambda _: None, initialization_guard=guard
    )
    with store.start(
        identity, str(uuid4()), str(uuid4()), core_type="smolagents"
    ) as writer:
        writer.finish("completed")
    changed = CaptureIdentity("t", "u", "123", "8")
    with store.start(
        changed, str(uuid4()), str(uuid4()), core_type="smolagents", turn_no=4
    ) as writer:
        writer.finish("completed")
    assert entries == [identity]
    assert (tmp_path / "t/u/7/123/.lock").is_file()
    assert not (tmp_path / ".locks").exists() and not (tmp_path / "t/u/8").exists()
    assert store.manifest(changed)["agent_id"] == "7"
    assert store.manifest(changed)["next_turn_no"] == 5
    store.cleanup(identity, before_days=1)
    assert (tmp_path / ".cleanup.lock").is_file()
    assert (tmp_path / "t/u/7/123/.lock").is_file()


def test_cleanup_publishes_expired_pg_only_after_durable_manifest(tmp_path, identity):
    store = TrajectoryFileStore(tmp_path, authorize=lambda _: None)
    run = str(uuid4())
    with store.start(identity, run, str(uuid4()), core_type="smolagents") as writer:
        writer.finish("completed")

    def expire(owner, ids):
        assert owner == identity and ids == [run]
        import json

        meta = json.loads((tmp_path / "t/u/7/123/meta.json").read_text())
        assert meta["runs"][0]["capture_state"] == "expired"

    store.expire_callback = Mock(side_effect=expire)
    store.cleanup(identity, force_reason="conversation_deleted")
    store.expire_callback.assert_called_once()
    assert not (tmp_path / "t/u/7/123" / f"{run}.otlp.jsonl").exists()


def test_lifecycle_allocates_one_id_and_reuses_it_for_capture_even_when_disabled(
    mocker, identity
):
    from infrastructure.observability.trajectory_execution import execution_observer
    from nexent.monitor import AgentRunMetadata

    repository = mocker.patch(
        "management.db.trajectory.repository.ExecutionRepository"
    ).return_value
    repository.begin.return_value = 4
    metadata = AgentRunMetadata(
        conversation_id=123, user_id="u", tenant_id="t", agent_id=7, agent_version_no=0
    )
    with execution_observer(capturing=False)(metadata) as bound:
        assert bound.extra_metadata["trajectory_turn_no"] == 4
        run = bound.extra_metadata["trajectory_id"]
    repository.begin.assert_called_once_with(
        identity, run, agent_version_no=0, capturing=False
    )
    assert metadata.extra_metadata.get("trajectory_id") is None


def test_idempotent_registration_and_expired_compensation_do_not_revive(
    mocker, identity
):
    from management.db.trajectory.repository import ExecutionRepository

    session = Mock()
    row = SimpleNamespace(
        conversation_id=123,
        created_by="u",
        delete_flag="N",
        turn_no=4,
        status="expired",
    )
    session.get.return_value = row

    @contextmanager
    def scoped():
        yield session

    mocker.patch("management.db.trajectory.repository.get_db_session", scoped)
    mocker.patch.object(ExecutionRepository, "_owner")
    repository = ExecutionRepository()
    assert repository.begin(identity, "id") == 4
    repository.sync(identity, {"trajectory_id": "id", "status": "success"})
    session.add.assert_not_called()
    session.execute.assert_not_called()
    row.delete_flag = "Y"
    with pytest.raises(PermissionError):
        repository.begin(identity, "id")


def test_summary_worker_failure_retries_without_publishing_partial(mocker):
    from management.services.trajectory.statistics import StatisticsWorker

    store = Mock()
    store.identities.return_value = iter([])
    repository = Mock()
    worker = StatisticsWorker(store, repository)
    mocker.patch(
        "management.services.trajectory.statistics.TrajectoryCatalog"
    ).return_value.tenants.return_value = ["t"]
    worker.refresher = Mock()
    worker.refresher.refresh.side_effect = ValueError("controlled")
    worker.tick()
    assert worker.refresher.refresh.call_count == 2
    worker.request_stop()
    with pytest.raises(InterruptedError):
        worker.check()


def test_registration_uses_file_highwater_and_does_not_reuse_a_turn(mocker, identity):
    from management.db.trajectory.repository import ExecutionRepository

    session = Mock()
    session.get.return_value = None
    session.execute.return_value.scalar.return_value = 2

    @contextmanager
    def scoped():
        yield session

    mocker.patch("management.db.trajectory.repository.get_db_session", scoped)
    mocker.patch.object(ExecutionRepository, "_owner")
    dirty = mocker.patch("management.db.trajectory.repository.dirty")
    assert (
        ExecutionRepository().begin(
            identity, str(uuid4()), agent_version_no=0, prior_turn=8
        )
        == 9
    )
    execution = session.add.call_args.args[0]
    assert (
        execution.turn_no == 9
        and execution.agent_id == 7
        and execution.agent_version_no == 0
    )
    assert execution.status == "unarchived" and execution.models == []
    dirty.assert_called_once_with(session, "t")
    session.commit.assert_not_called()


def test_out_of_order_file_registration_keeps_highest_turn_latest(tmp_path, identity):
    store = TrajectoryFileStore(tmp_path, authorize=lambda _: None)
    with store.start(
        identity, str(uuid4()), str(uuid4()), core_type="smolagents", turn_no=4
    ) as writer:
        writer.finish("completed")
    with store.start(
        identity, str(uuid4()), str(uuid4()), core_type="smolagents", turn_no=3
    ) as writer:
        writer.finish("failed")
    meta = store.manifest(identity)
    assert meta["latest_execution"]["turn_no"] == 4 and meta["next_turn_no"] == 5


def test_pending_notifications_are_coalesced_and_repaired_by_the_projection_worker(
    mocker, identity
):
    from management.services.trajectory.statistics import SummaryWorker

    store = Mock()
    store.identities.return_value = iter([])
    repository = Mock()
    worker = SummaryWorker(store, repository)
    worker.projector = Mock()
    worker.notify(identity)
    worker.notify(identity)
    worker.tick()
    worker.projector.sync.assert_called_once_with(identity, worker.check)
    assert worker._pending == {}
    repository.placeholders.assert_called_once()
    repository.compact.assert_called_once()


def test_statistics_scope_lock_is_released_even_after_failure(mocker):
    from management.db.trajectory.statistics import scope_lock

    engine = mocker.patch("management.db.trajectory.statistics.db_client").engine
    connection = engine.connect.return_value.execution_options.return_value.__enter__.return_value
    connection.execute.return_value.scalar.return_value = True
    with (
        pytest.raises(ValueError, match="controlled"),
        scope_lock("tenant", "t") as acquired,
    ):
        assert acquired
        raise ValueError("controlled")
    statements = [str(call.args[0]) for call in connection.execute.call_args_list]
    assert (
        "pg_try_advisory_lock" in statements[0]
        and "pg_advisory_unlock" in statements[-1]
    )


def test_statistics_publication_is_atomic_and_preserves_newer_source_revision(mocker):
    from datetime import UTC, datetime

    from management.db.trajectory.statistics import publish

    session = Mock()
    session.execute.return_value.scalar.return_value = False

    @contextmanager
    def scoped():
        yield session

    mocker.patch("management.db.trajectory.statistics.get_db_session", scoped)
    assert publish(
        "tenant",
        "t",
        ["t"],
        datetime.now(UTC),
        3,
        {"ttft_sample_count": 2, "ttft_p90_ms": 18},
    )
    statement = session.execute.call_args.args[0]
    sql = str(statement)
    assert "computed_revision" in sql and "source_revision=" not in sql
    assert statement.compile().params["computed_revision"] == 3
    session.commit.assert_not_called()
    session.execute.return_value.scalar.return_value = True
    previous = session.execute.call_count
    assert (
        publish("tenant", "t", ["t"], datetime.now(UTC), 3, {"ttft_sample_count": 2})
        is False
    )
    assert session.execute.call_count == previous + 2


def test_delayed_parser_cannot_republish_after_file_cleanup(tmp_path, identity, mocker):
    from management.services.trajectory.projection import Projector

    store = TrajectoryFileStore(tmp_path, authorize=lambda _: None)
    run = str(uuid4())
    with store.start(identity, run, str(uuid4()), core_type="smolagents") as writer:
        writer.finish("completed")

    def parsed(*args, **kwargs):
        store.cleanup(identity, force_reason="conversation_deleted")
        return (
            [{"id": "root", "kind": "agent", "duration_ms": 100}],
            "root",
            {"complete": True},
        )

    mocker.patch(
        "management.services.trajectory.projection.build_nodes", side_effect=parsed
    )
    repository = Mock()
    Projector(store, repository).sync(identity)
    assert repository.sync.call_args.args[1]["status"] == "expired"


def test_corrupt_archives_are_projected_explicitly_without_stalling_other_runs(
    tmp_path, identity
):
    from management.services.trajectory.projection import Projector

    store = TrajectoryFileStore(tmp_path, authorize=lambda _: None)
    run = str(uuid4())
    with store.start(identity, run, str(uuid4()), core_type="smolagents") as writer:
        writer.finish("completed")
    (tmp_path / "t/u/7/123" / f"{run}.otlp.jsonl").write_text("corrupt")
    repository = Mock()
    Projector(store, repository).sync(identity)
    assert repository.sync.call_args.args[1]["status"] == "corrupt"


def test_directory_candidates_use_pg_without_file_checks(mocker):
    from management.services.trajectory.access import Actor
    from management.services.trajectory.directory import directory
    from management.services.trajectory.primitives import ReferenceStore

    service = Mock()
    service.execution_catalog = Mock()
    service.references = ReferenceStore()
    service.catalog.tenants.return_value = ["t"]
    service.catalog.directory_page.return_value = [
        {"conversation_id": "123", "agent_id": "7", "user_id": "u"}
    ]
    service.catalog.agent_names.return_value = {("t", "7"): "Agent"}
    result = directory(service, Actor("admin", "t", "ADMIN"), target_user_id="u")
    assert result["items"][0]["agent_name"] == "Agent"
    service.archive.manifest.assert_not_called()


def test_statistics_duration_queries_use_sql_percentiles_and_exclude_expired(mocker):
    from datetime import UTC, datetime

    from management.db.trajectory.statistics import duration_statistics

    session = Mock()
    session.execute.return_value.mappings.return_value.one.return_value = {}
    session.execute.return_value.scalar.return_value = 3

    @contextmanager
    def scoped():
        yield session

    mocker.patch("management.db.trajectory.statistics.get_db_session", scoped)
    assert duration_statistics(["t"], datetime.now(UTC))["conversation_count"] == 3
    sql = str(session.execute.call_args_list[1].args[0])
    assert "percentile_cont(0.99)" in sql
    assert "status IN ('success','error','partial')" in sql
    assert "count(*)=count(duration_ms)" in sql
    assert "update_time<=:asof" in sql


def test_pruned_latest_expired_fact_is_backfilled_without_fabricated_metrics(
    tmp_path, identity
):
    from management.services.trajectory.projection import Projector

    store = TrajectoryFileStore(tmp_path, authorize=lambda _: None)
    run = str(uuid4())
    with store.start(identity, run, str(uuid4()), core_type="smolagents") as writer:
        writer.finish("completed")
    store.cleanup(identity, force_reason="conversation_deleted")
    with store._session(identity) as directory:
        meta = directory.read_json("meta.json")
        meta["runs"] = []
        store._save_manifest(directory, meta)
    repository = Mock()
    Projector(store, repository).sync(identity)
    values = repository.sync.call_args.args[1]
    assert values["trajectory_id"] == run and values["status"] == "expired"
    assert values["turn_no"] == 1 and values["duration_ms"] is None
    assert values["total_tokens"] is None


def test_tenant_migration_revokes_summaries_and_marks_both_scopes_dirty(mocker):
    from management.db.trajectory.repository import detach_owner

    session = Mock()
    dirty = mocker.patch("management.db.trajectory.repository.dirty")
    detach_owner(session, "u", "old", "new")
    statements = [str(call.args[0]) for call in session.execute.call_args_list]
    assert "UPDATE" in statements[0] and "delete_flag" in statements[0]
    assert "ON CONFLICT (trajectory_id)" in statements[1]
    assert "not_captured" in statements[1]
    dirty.assert_called_once_with(session, ["new", "old"])
    session.commit.assert_not_called()


def test_lifecycle_still_registers_latest_request_when_archive_is_unreadable(mocker):
    from infrastructure.observability.trajectory_execution import execution_observer
    from nexent.monitor import AgentRunMetadata

    repository = mocker.patch(
        "management.db.trajectory.repository.ExecutionRepository"
    ).return_value
    repository.begin.return_value = 8
    store = Mock()
    store.manifest.side_effect = OSError("offline volume")
    with execution_observer(capturing=True, store=store)(
        AgentRunMetadata(conversation_id=123, tenant_id="t", user_id="u", agent_id=7)
    ) as bound:
        assert bound.extra_metadata["trajectory_turn_no"] == 8
    assert repository.begin.call_args.kwargs["prior_turn"] == 0


def test_pg_reader_construction_never_opens_or_provisions_the_file_root(mocker):
    from contracts.constants import environment
    from management.services.trajectory import runtime

    mocker.patch.object(runtime, "_service", None)
    mocker.patch.object(environment, "TRAJECTORY_READ_ENABLED", True)
    provision = mocker.patch(
        "infrastructure.observability.trajectory_store.TrajectoryFileStore.provision",
        side_effect=AssertionError("List construction touched storage"),
    )
    service = runtime.get_service()
    assert service.execution_catalog is not None
    provision.assert_not_called()


def test_multiple_dirty_tenant_scopes_are_locked_before_the_global_scope():
    from management.db.trajectory.repository import dirty

    session = Mock()
    dirty(session, ["old", "new", "old"])
    scopes = [call.args[0].compile().params["scope_id"] for call in session.execute.call_args_list]
    assert scopes == ["new", "old", "global"]
