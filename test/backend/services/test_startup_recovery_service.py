import asyncio
import sys
import types
from datetime import datetime
from unittest.mock import MagicMock, call

import pytest

from backend.services import startup_recovery_service


def _install_module(monkeypatch, name, **attributes):
    module = types.ModuleType(name)
    for attribute, value in attributes.items():
        setattr(module, attribute, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def test_recover_runtime_tasks_finishes_database_and_redis_state(monkeypatch):
    fail_messages = MagicMock(
        return_value=[
            {"message_id": 1, "conversation_id": 10, "user_id": "user-1"},
            {"message_id": 2, "conversation_id": 20, "user_id": None},
        ]
    )
    reap = MagicMock(side_effect=[2, 3])
    runtime_state = MagicMock()
    _install_module(
        monkeypatch,
        "database.conversation_db",
        fail_streaming_assistant_messages=fail_messages,
    )
    _install_module(
        monkeypatch,
        "database.agent_automation_db",
        recover_orphaned_runs=MagicMock(return_value=4),
        release_all_task_locks=MagicMock(return_value=5),
    )
    _install_module(
        monkeypatch,
        "database.agent_evaluation_db",
        list_evaluation_tenant_ids=MagicMock(return_value=["tenant-1", "tenant-2"]),
        reap_stale_runs=reap,
    )
    _install_module(
        monkeypatch,
        "services.runtime_state_service",
        runtime_state_service=runtime_state,
    )

    result = startup_recovery_service.recover_runtime_tasks()

    assert result == {
        "conversation_messages": 2,
        "agent_evaluations": 5,
        "automation_runs": 4,
        "automation_locks": 5,
    }
    assert reap.call_args_list == [
        call("tenant-1", timeout_minutes=0),
        call("tenant-2", timeout_minutes=0),
    ]
    runtime_state.mark_run_finished.assert_called_once_with("user-1", 10, "failed")
    runtime_state.mark_stream_completed.assert_called_once_with(
        "user-1", 10, "failed"
    )


def test_recover_config_tasks_uses_existing_failure_states(monkeypatch):
    _install_module(
        monkeypatch,
        "database.agent_evaluation_db",
        fail_interrupted_no_set_runs_on_startup=MagicMock(return_value=2),
    )
    _install_module(
        monkeypatch,
        "database.evaluation_set_db",
        recover_interrupted_generations=MagicMock(return_value=3),
        cleanup_orphaned_virtual_evaluation_sets=MagicMock(return_value=4),
    )
    _install_module(
        monkeypatch,
        "database.model_management_db",
        fail_detecting_models_on_startup=MagicMock(return_value=5),
    )
    _install_module(
        monkeypatch,
        "database.memory_dreaming_db",
        recover_stale=MagicMock(return_value=6),
    )

    assert startup_recovery_service.recover_config_tasks() == {
        "agent_evaluation_setups": 2,
        "evaluation_set_generations": 3,
        "orphaned_virtual_sets": 4,
        "model_connectivity_checks": 5,
        "dreaming_runs": 6,
    }


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
        "database.knowledge_file_lifecycle_db",
        fail_interrupted_file_tasks=MagicMock(return_value=records),
    )
    _install_module(
        monkeypatch,
        "services.redis_service",
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
        "database.a2a_agent_db",
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
    _install_module(monkeypatch, "database.attachment_db", delete_file=delete_object)
    _install_module(monkeypatch, "database.client", minio_client=MagicMock())
    _install_module(
        monkeypatch,
        "database.knowledge_file_lifecycle_db",
        list_uploading_files_created_before=MagicMock(return_value=records),
        transition_file_record=transition,
    )

    assert startup_recovery_service.fail_interrupted_uploads(
        cutoff,
        "nexent-config",
    ) == 1
    list_uploads = sys.modules[
        "database.knowledge_file_lifecycle_db"
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
        "database.attachment_db",
        delete_file=MagicMock(return_value={"success": False, "error": "storage down"}),
    )
    _install_module(monkeypatch, "database.client", minio_client=minio_client)
    _install_module(
        monkeypatch,
        "database.knowledge_file_lifecycle_db",
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
async def test_schedule_interrupted_upload_cleanup_checks_now_and_after_grace(
    monkeypatch,
):
    fail_uploads = MagicMock(return_value=0)
    monkeypatch.setattr(startup_recovery_service, "fail_interrupted_uploads", fail_uploads)
    monkeypatch.setattr(startup_recovery_service, "UPLOAD_RECOVERY_GRACE_SECONDS", 0)
    startup_recovery_service._upload_cleanup_tasks.clear()

    await startup_recovery_service.schedule_interrupted_upload_cleanup(
        "nexent-config"
    )
    pending = list(startup_recovery_service._upload_cleanup_tasks)
    if pending:
        await asyncio.gather(*pending)

    assert fail_uploads.call_count == 2
    assert (
        fail_uploads.call_args_list[0].args[0]
        <= fail_uploads.call_args_list[1].args[0]
    )
    assert [call_args.args[1] for call_args in fail_uploads.call_args_list] == [
        "nexent-config",
        "nexent-config",
    ]
