# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from contracts.agentos import PreparedEvaluationRun
from infrastructure.agentos_identity import ServicePrincipal
from runtime.agentos.prepared_evaluation import prepare_evaluation_run


@pytest.fixture(autouse=True)
def local_sandbox(monkeypatch):
    monkeypatch.setattr("runtime.agentos.prepared_evaluation.NEXENT_SANDBOX_DEFAULT_LEVEL", "local")


def evaluation_payload():
    return {
        "mode": "nexent",
        "resource": {
            "agent_id": 7, "version_no": 2, "name": "test_agent",
            "description": "Evaluation agent", "prompt_templates": {"system_prompt": "Answer the query"},
        },
        "models": {"llm": {"model_id": 11, "alias": "evaluation_llm", "revision": "revision-1"}},
        "input": {"query": "hello", "history": [{"role": "user", "content": "earlier"}]},
        "conversation_id": -10,
    }


def test_prepared_case_round_trip_and_forbidden_fields():
    payload = evaluation_payload()
    model = PreparedEvaluationRun.model_validate(payload)
    assert PreparedEvaluationRun.model_validate_json(model.model_dump_json()) == model

    payload["models"]["llm"]["api_key"] = "should-not-cross"
    with pytest.raises(ValidationError, match="api_key"):
        PreparedEvaluationRun.model_validate(payload)


@pytest.mark.parametrize("conversation_id", [1, "0", True])
def test_prepared_case_rejects_real_or_coerced_conversation_ids(conversation_id):
    with pytest.raises(ValidationError, match="conversation_id"):
        PreparedEvaluationRun.model_validate(evaluation_payload() | {"conversation_id": conversation_id})


def model_record(**changes):
    return {
        "tenant_id": "tenant-a", "delete_flag": "N", "model_type": "llm", "model_name": "provider-model",
        "model_repo": None, "display_name": "Evaluation", "api_key": "runtime-only",
        "base_url": "https://runtime-provider.example/v1", "update_time": "revision-1",
    } | changes


def test_runtime_materializes_authorized_model_and_local_objects(mocker):
    load_record = mocker.patch(
        "runtime.agentos.prepared_evaluation.get_model_by_model_id", return_value=model_record(),
    )
    actor = ServicePrincipal("user-a", "tenant-a")
    info = prepare_evaluation_run(PreparedEvaluationRun.model_validate(evaluation_payload()), actor)

    load_record.assert_called_once_with(11, "tenant-a")
    assert info.tenant_id == "tenant-a" and info.user_id == "user-a"
    assert info.conversation_id == -10 and info.query == "hello"
    assert info.agent_config.model_name == "evaluation_llm"
    assert info.model_config_list[0].api_key == "runtime-only"
    assert not info.stop_event.is_set()
    assert info.history[0].content == "earlier"


@pytest.mark.parametrize(("change", "status"), [
    ({"tenant_id": "tenant-b"}, 404), ({"delete_flag": "Y"}, 404),
    ({"update_time": "revision-2"}, 409), ({"model_type": "embedding"}, 422),
])
def test_runtime_rejects_unavailable_model_before_constructing_sdk_objects(mocker, change, status):
    from fastapi import HTTPException

    mocker.patch("runtime.agentos.prepared_evaluation.get_model_by_model_id", return_value=model_record(**change))
    build = mocker.patch("runtime.agentos.prepared_evaluation.build_run_info", new=MagicMock())

    with pytest.raises(HTTPException) as error:
        prepare_evaluation_run(
            PreparedEvaluationRun.model_validate(evaluation_payload()), ServicePrincipal("user-a", "tenant-a"),
        )

    assert error.value.status_code == status
    build.assert_not_called()


@pytest.mark.parametrize("change", [
    {"tools": [{"tool_id": "download", "version": "1"}]},
    {"sandbox_policy": {"level": "docker"}},
    {"memory_ref": "some-memory"},
])
def test_runtime_rejects_unsupported_resources_before_model_lookup(mocker, change):
    from fastapi import HTTPException

    lookup = mocker.patch("runtime.agentos.prepared_evaluation.get_model_by_model_id")
    payload = evaluation_payload()
    payload["resource"].update(change)

    with pytest.raises(HTTPException) as error:
        prepare_evaluation_run(PreparedEvaluationRun.model_validate(payload), ServicePrincipal("user-a", "tenant-a"))

    assert error.value.status_code == 422
    assert error.value.detail == {"code": "AGENTOS_RESOURCE_UNSUPPORTED"}
    lookup.assert_not_called()


@pytest.mark.asyncio
async def test_cancellation_keeps_run_registered_until_worker_exits(mocker):
    import asyncio
    from concurrent.futures import Future

    from runtime.agentos import prepared_evaluation
    from runtime.executions import LocalExecutionRegistry

    actor = ServicePrincipal("user-a", "tenant-a")
    payload = PreparedEvaluationRun.model_validate(evaluation_payload())
    mocker.patch.object(prepared_evaluation, "get_model_by_model_id", return_value=model_record())
    info = prepare_evaluation_run(payload, actor)
    future = Future()
    info.thread_future = future
    mocker.patch.object(prepared_evaluation, "run_blocking", return_value=info)
    registry = LocalExecutionRegistry()
    mocker.patch.object(prepared_evaluation, "agent_run_manager", registry)
    unregister = mocker.spy(registry, "unregister_agent_run")
    mocker.patch.object(prepared_evaluation, "collect_observer_output", side_effect=asyncio.CancelledError)

    with pytest.raises(asyncio.CancelledError):
        await prepared_evaluation.execute_prepared_evaluation(payload, actor)

    assert registry.get_agent_run_info(-10, actor.user_id) is info
    unregister.assert_not_called()
    future.set_result(None)
    assert registry.get_agent_run_info(-10, actor.user_id) is None
    unregister.assert_called_once_with(-10, actor.user_id, status="stopped", agent_run_info=info)
