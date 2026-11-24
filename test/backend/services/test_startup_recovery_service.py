# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import asyncio
import sys
import types
from datetime import datetime
from unittest.mock import MagicMock, call

import pytest

from management import recovery as startup_recovery_service


def _install_module(monkeypatch, name, **attributes):
    module = types.ModuleType(name)
    for attribute, value in attributes.items():
        setattr(module, attribute, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def test_recover_streaming_runs_finishes_redis_state(monkeypatch):
    from runtime import recovery

    monkeypatch.setattr(recovery, "fail_streaming_assistant_messages", MagicMock(
        return_value=[
            {"message_id": 1, "conversation_id": 10, "user_id": "user-1"},
            {"message_id": 2, "conversation_id": 20, "user_id": None},
        ]
    ))
    runtime_state = MagicMock()
    monkeypatch.setattr(recovery, "runtime_state_service", runtime_state)

    assert recovery.recover_streaming_runs() == 2
    runtime_state.mark_run_finished.assert_called_once_with("user-1", 10, "failed")
    runtime_state.mark_stream_completed.assert_called_once_with("user-1", 10, "failed")


@pytest.mark.parametrize("sandbox_enabled", [False, True])
def test_maintenance_redis_failure_leaves_conversation_update_for_transaction_rollback(monkeypatch, sandbox_enabled):
    from runtime import identity

    monkeypatch.setattr(identity, "uses_distributed_runtime", lambda: sandbox_enabled)
    session = object()
    fail_messages = MagicMock(return_value=[{"message_id": 123, "conversation_id": 10, "user_id": "user-1"}])
    runtime_state = MagicMock()
    runtime_state.mark_interrupted_run.side_effect = ConnectionError("Redis offline")
    _install_module(monkeypatch, "infrastructure.rdb.conversation_state", fail_streaming_assistant_messages=fail_messages)
    automation = _install_module(
        monkeypatch, "management.db.automation.repository",
        recover_orphaned_runs=MagicMock(), release_all_task_locks=MagicMock(),
    )
    _install_module(
        monkeypatch, "management.db.evaluation.runs",
        list_evaluation_tenant_ids=MagicMock(), reap_stale_runs=MagicMock(),
    )
    _install_module(monkeypatch, "infrastructure.redis.run_state", runtime_state_service=runtime_state)

    with pytest.raises(ConnectionError, match="Redis offline"):
        startup_recovery_service.recover_runtime_tasks(db_session=session)

    fail_messages.assert_called_once_with(db_session=session)
    runtime_state.mark_interrupted_run.assert_called_once_with("user-1", 10, 123)
    automation.release_all_task_locks.assert_not_called()


def test_maintenance_enlists_automation_recovery_in_batch_transaction(monkeypatch):
    session = object()
    messages = _install_module(
        monkeypatch, "infrastructure.rdb.conversation_state", fail_streaming_assistant_messages=MagicMock(return_value=[]),
    )
    automation = _install_module(
        monkeypatch, "management.db.automation.repository",
        recover_orphaned_runs=MagicMock(return_value=2), release_all_task_locks=MagicMock(return_value=3),
    )
    evaluations = _install_module(
        monkeypatch, "management.db.evaluation.runs",
        list_evaluation_tenant_ids=MagicMock(return_value=["tenant-1"]), reap_stale_runs=MagicMock(return_value=1),
    )
    _install_module(monkeypatch, "infrastructure.redis.run_state", runtime_state_service=MagicMock())

    result = startup_recovery_service.recover_runtime_tasks(db_session=session)

    assert result == {"conversation_messages": 0, "agent_evaluations": 1, "automation_runs": 2, "automation_locks": 3}
    messages.fail_streaming_assistant_messages.assert_called_once_with(db_session=session)
    evaluations.reap_stale_runs.assert_called_once_with(
        "tenant-1", timeout_minutes=0, recover_owned=True, db_session=session,
    )
    automation.recover_orphaned_runs.assert_called_once_with(db_session=session)
    automation.release_all_task_locks.assert_called_once_with(db_session=session)


def test_recover_config_tasks_uses_existing_failure_states(monkeypatch):
    reap = MagicMock(side_effect=[2, 3])
    _install_module(
        monkeypatch,
        "management.db.evaluation.runs",
        fail_interrupted_no_set_runs_on_startup=MagicMock(return_value=2),
        list_evaluation_tenant_ids=MagicMock(return_value=["tenant-1", "tenant-2"]),
        reap_stale_runs=reap,
    )
    _install_module(
        monkeypatch,
        "management.db.evaluation.sets",
        recover_interrupted_generations=MagicMock(return_value=3),
        cleanup_orphaned_virtual_evaluation_sets=MagicMock(return_value=4),
    )
    _install_module(
        monkeypatch,
        "management.db.memory.dreaming",
        recover_stale=MagicMock(return_value=6),
    )

    assert startup_recovery_service.recover_config_tasks() == {
        "agent_evaluation_setups": 2,
        "agent_evaluations": 5,
        "evaluation_set_generations": 3,
        "orphaned_virtual_sets": 4,
        "dreaming_runs": 6,
    }
    assert reap.call_args_list == [call("tenant-1", timeout_minutes=0), call("tenant-2", timeout_minutes=0)]


def test_recover_data_process_tasks_marks_each_celery_id_cancelled_once(monkeypatch):
    records = [
        {
            "process_task_id": "process-1",
            "forward_task_id": "forward-1",
            "parent_task_id": "parent-1",
        },
        {
            "process_task_id": "process-1",
            "forward_task_id": None,
            "parent_task_id": "parent-2",
        },
    ]
    redis_service = MagicMock()
    redis_service.mark_task_cancelled.side_effect = [True, True, False, True]
    _install_module(
        monkeypatch,
        "management.db.knowledge_base.file_lifecycle",
        fail_interrupted_file_tasks=MagicMock(return_value=records),
    )
    _install_module(
        monkeypatch,
        "management.services.knowledge_base.task_state",
        get_redis_service=MagicMock(return_value=redis_service),
    )

    result = startup_recovery_service.recover_data_process_tasks()

    assert result == {"knowledge_files": 2, "cancel_markers": 3}
    assert {
        invocation.args[0]
        for invocation in redis_service.mark_task_cancelled.call_args_list
    } == {"process-1", "forward-1", "parent-1", "parent-2"}


def test_recover_northbound_tasks_fails_active_a2a_tasks(monkeypatch):
    fail_active = MagicMock(return_value=6)
    _install_module(
        monkeypatch,
        "management.db.a2a.repository",
        fail_active_tasks_on_startup=fail_active,
    )

    assert startup_recovery_service.recover_northbound_tasks() == {"a2a_tasks": 6}
    fail_active.assert_called_once_with()


def test_fail_interrupted_uploads_claims_before_deleting_partial_object(monkeypatch):
    cutoff = datetime(2026, 9, 1, 12, 0)
    records = [
        {
            "file_id": "claimed",
            "version": 2,
            "object_name": "knowledge/a.pdf",
            "bucket_name": "files",
        },
        {
            "file_id": "stale",
            "version": 1,
            "object_name": "knowledge/b.pdf",
            "bucket_name": "files",
        },
    ]
    transition = MagicMock(side_effect=[{"file_id": "claimed", "version": 3}, None])
    delete_object = MagicMock(return_value={"success": True})
    _install_module(monkeypatch, "management.db.file.attachment", delete_file=delete_object)
    _install_module(monkeypatch, "infrastructure.object_storage.client", minio_client=MagicMock())
    _install_module(
        monkeypatch,
        "management.db.knowledge_base.file_lifecycle",
        list_uploading_files_created_before=MagicMock(return_value=records),
        transition_file_record=transition,
    )

    assert startup_recovery_service.fail_interrupted_uploads(
        cutoff,
        "nexent-config",
    ) == 1
    list_uploads = sys.modules[
        "management.db.knowledge_base.file_lifecycle"
    ].list_uploading_files_created_before
    list_uploads.assert_called_once_with(cutoff, "nexent-config")
    delete_object.assert_called_once_with("knowledge/a.pdf", "files")
    first_update = transition.call_args_list[0]
    assert first_update.args == ("claimed",)
    assert first_update.kwargs["status"] == "FAILED"
    assert first_update.kwargs["stage"] == "UPLOAD"
    assert first_update.kwargs["expected_statuses"] == ("UPLOADING",)
    assert first_update.kwargs["expected_version"] == 2
    assert first_update.kwargs["error_code"] == "CONTAINER_RESTARTED"


def test_fail_interrupted_uploads_records_storage_cleanup_failure(monkeypatch):
    cutoff = datetime(2026, 9, 1, 12, 0)
    record = {
        "file_id": "failed",
        "version": 3,
        "object_name": "knowledge/a.pdf",
        "bucket_name": "files",
    }
    transition = MagicMock(
        side_effect=[
            {"file_id": "failed", "version": 4},
            {"file_id": "failed", "version": 5},
        ]
    )
    minio_client = MagicMock()
    minio_client.file_exists.return_value = True
    _install_module(
        monkeypatch,
        "management.db.file.attachment",
        delete_file=MagicMock(return_value={"success": False, "error": "storage down"}),
    )
    _install_module(monkeypatch, "infrastructure.object_storage.client", minio_client=minio_client)
    _install_module(
        monkeypatch,
        "management.db.knowledge_base.file_lifecycle",
        list_uploading_files_created_before=MagicMock(return_value=[record]),
        transition_file_record=transition,
    )

    assert startup_recovery_service.fail_interrupted_uploads(
        cutoff,
        "nexent-northbound",
    ) == 1
    assert transition.call_count == 2
    failure = transition.call_args_list[1]
    assert failure.args == ("failed",)
    assert failure.kwargs["status"] == "FAILED"
    assert failure.kwargs["expected_statuses"] == ("FAILED",)
    assert failure.kwargs["expected_version"] == 4
    assert failure.kwargs["error_code"] == "UPLOAD_RECOVERY_FAILED"
    assert failure.kwargs["error_message"] == "storage down"




@pytest.mark.asyncio
async def test_upload_recovery_uses_management_lane_and_returns_owned_task(monkeypatch):
    from unittest.mock import AsyncMock

    fail_uploads = MagicMock(return_value=0)
    monkeypatch.setattr(startup_recovery_service, "fail_interrupted_uploads", fail_uploads)
    monkeypatch.setattr(startup_recovery_service, "UPLOAD_RECOVERY_GRACE_SECONDS", 0)

    async def run(lane, spec, fn, *args):
        assert lane == "control-io"
        assert spec.owner == "management.recovery"
        return fn(*args)

    manager = MagicMock()
    manager.run = AsyncMock(side_effect=run)
    task = await startup_recovery_service.schedule_interrupted_upload_cleanup("nexent-config", thread_manager=manager)
    await task
    assert manager.run.await_count == 2
    assert fail_uploads.call_count == 2
    assert all(call.args[1] == "nexent-config" for call in fail_uploads.call_args_list)


def test_durable_recovery_retries_failed_redis_write_without_clearing_repair(monkeypatch):
    from redis.exceptions import ConnectionError

    from infrastructure.rdb.agent_execution import RunIdentity
    from runtime import recovery

    identity = RunIdentity("tenant", "user", 42, "a" * 32)
    renew = MagicMock()
    reclaim = MagicMock()
    clear = MagicMock()
    journal = MagicMock()
    journal.return_value.repair_terminal.side_effect = [ConnectionError("Redis unavailable"), None]
    monkeypatch.setattr(recovery, "renew_execution_leases", renew)
    monkeypatch.setattr(recovery, "recover_expired_executions", reclaim)
    monkeypatch.setattr(recovery, "pending_journal_repairs", lambda: [(identity, "stopped")])
    monkeypatch.setattr(recovery, "mark_journal_repaired", clear)
    monkeypatch.setattr(recovery, "RunJournal", journal)
    monkeypatch.setattr(recovery, "runtime_state_service", MagicMock(enabled=True))

    recovery.reconcile_executions()
    clear.assert_not_called()
    recovery.reconcile_executions()
    clear.assert_called_once_with(identity)
    assert renew.call_count == reclaim.call_count == 2
    assert journal.return_value.repair_terminal.call_args_list == [call("stopped"), call("stopped")]


def test_startup_has_no_system_agent_backfill():
    assert not hasattr(startup_recovery_service, "schedule_workbench_main_backfill")
    assert not hasattr(startup_recovery_service, "_system_agent_backfill_tasks")
