# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import sys
import types
from contextlib import nullcontext
from datetime import datetime
from unittest.mock import MagicMock, call

import pytest
from management import recovery as startup_recovery_service
from nexent.storage.models import Page, Revision, WriteReceipt


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


def test_recover_northbound_tasks_fails_active_a2a_tasks(monkeypatch):
    fail_active = MagicMock(return_value=6)
    _install_module(
        monkeypatch,
        "management.db.a2a.repository",
        fail_active_tasks_on_startup=fail_active,
    )

    assert startup_recovery_service.recover_northbound_tasks() == {"a2a_tasks": 6}
    fail_active.assert_called_once_with()


def _recovery_storage(monkeypatch, records, receipts=()):
    reader, writer = MagicMock(), MagicMock()
    reader.query.return_value = Page(tuple(records), None)
    writer.patch.side_effect = receipts
    ports = MagicMock(side_effect=lambda owner, *, record=None, **kwargs: nullcontext(
        reader if record is None else writer
    ))
    monkeypatch.setattr(startup_recovery_service, "interrupted_upload_ports", ports)
    return reader, writer, ports


def test_fail_interrupted_uploads_claims_before_deleting_partial_object(monkeypatch):
    cutoff = datetime(2026, 9, 1, 12, 0)
    records = [
        {
            "tenant_id": "tenant",
            "file_id": "claimed",
            "version": 2,
            "object_name": "knowledge/a.pdf",
            "bucket_name": "files",
        },
        {
            "tenant_id": "tenant",
            "file_id": "stale",
            "version": 1,
            "object_name": "knowledge/b.pdf",
            "bucket_name": "files",
        },
    ]
    reader, writer, records_ports = _recovery_storage(monkeypatch, records, [
        WriteReceipt("op", True, Revision("3")), WriteReceipt("op", False),
    ])
    from nexent.storage.models import DeleteReceipt, ObjectRef

    store = MagicMock()
    def delete(ref, *, context):
        writer.patch.assert_called_once()
        assert ref == ObjectRef("files", "knowledge/a.pdf")
        return DeleteReceipt(context.operation_id, True)
    store.delete.side_effect = delete
    ports = MagicMock(return_value=nullcontext(store))
    _install_module(monkeypatch, "infrastructure.file_objects", file_object_ports=ports)

    assert startup_recovery_service.fail_interrupted_uploads(cutoff, "nexent-config") == 1
    assert records_ports.call_args_list[0].args == ("nexent-config",)
    query = reader.query.call_args.args[1]
    assert (query.where.field, query.where.operator, query.where.value) == (
        "create_time", "lt", "2026-09-01T12:00:00+00:00",
    )
    assert store.delete.call_count == 1
    actor, target = ports.call_args.args
    assert (actor.user_id, actor.tenant_id) == ("upload-recovery", "tenant")
    assert (target.bucket_name, target.object_name) == ("files", "knowledge/a.pdf")
    first_update = writer.patch.call_args_list[0]
    assert first_update.args[1] == "claimed"
    assert first_update.args[2].set_values["status"] == "FAILED"
    assert first_update.args[2].set_values["stage"] == "UPLOAD"
    assert first_update.args[2].set_values["error_code"] == "CONTAINER_RESTARTED"
    assert first_update.kwargs["expected"] == Revision("2")
    assert records_ports.call_args_list[1].kwargs["expected_status"] == "UPLOADING"


def test_new_source_intents_are_not_deleted_by_legacy_recovery(monkeypatch):
    delete_object = MagicMock()
    monkeypatch.setattr(startup_recovery_service, "_delete_interrupted_object", delete_object)
    _, writer, _ = _recovery_storage(monkeypatch, [
        {"file_id": "pending", "stage": "SOURCE_UPLOAD"},
        {"file_id": "pinned", "source_revision": "etag:known"},
        {"file_id": "review", "stage": "SOURCE_REVIEW", "source_upload_sha256": "1" * 64},
    ])
    assert startup_recovery_service.fail_interrupted_uploads(datetime(2026, 9, 1), "management") == 0
    writer.patch.assert_not_called()
    delete_object.assert_not_called()



@pytest.mark.parametrize("physical_state", ["present", "absent", "unknown"])
def test_failed_legacy_delete_only_accepts_confirmed_absence(monkeypatch, physical_state):
    from nexent.storage.errors import NotFound, OutcomeUnknown, Unavailable
    from nexent.storage.models import ObjectRef

    record = {"file_id": "failed", "tenant_id": "tenant", "version": 3,
              "object_name": "s3://files/knowledge/a:legacy.pdf", "bucket_name": "files"}
    _, writer, records_ports = _recovery_storage(monkeypatch, [record], [
        WriteReceipt("op", True, Revision("4")), WriteReceipt("op", True, Revision("5")),
    ])
    store = MagicMock()
    store.delete.side_effect = OutcomeUnknown()
    inspection = MagicMock()
    if physical_state == "absent":
        inspection.stat.side_effect = NotFound()
    elif physical_state == "unknown":
        inspection.stat.side_effect = Unavailable()
    ports = MagicMock(return_value=nullcontext(store))
    reads = MagicMock(return_value=nullcontext(inspection))
    _install_module(monkeypatch, "infrastructure.file_objects", file_object_ports=ports)
    _install_module(monkeypatch, "infrastructure.file_reads", file_read_ports=reads)
    assert startup_recovery_service.fail_interrupted_uploads(datetime(2026, 9, 1), "nexent-northbound") == 1
    context = ports.call_args.kwargs["context"]
    ref = ObjectRef("files", "knowledge/a:legacy.pdf")
    store.delete.assert_called_once_with(ref, context=context)
    reads.assert_called_once_with(ref.key, bucket="files", context=context)
    inspection.stat.assert_called_once_with(ref, context=context)
    if physical_state == "absent":
        assert writer.patch.call_count == 1
    else:
        assert writer.patch.call_count == 2
        failure = writer.patch.call_args_list[1]
        assert failure.args[1] == "failed"
        fields = failure.args[2].set_values
        assert fields["status"] == "FAILED"
        assert failure.kwargs["expected"] == Revision("4")
        assert records_ports.call_args_list[-1].kwargs["expected_status"] == "FAILED"
        assert fields["error_code"] == "UPLOAD_RECOVERY_FAILED"
        expected = str(Unavailable() if physical_state == "unknown" else OutcomeUnknown())
        assert fields["error_message"] == expected


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
    from runtime import recovery

    from infrastructure.rdb.agent_execution import RunIdentity

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
