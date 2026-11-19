# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Keep model administration and invocations on the tenant-scoped Runtime boundary."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from contracts.agentos import ModelAdministrationOperation as Operation
from contracts.errors.exceptions import ModelProviderError, RuntimeServiceUnavailableError, RuntimeUpstreamError
from management.clients import model as client
from management.services.model import commands

USER = "operator"
TENANT = "tenant"
DEFINITION = {"model_name": "chat-model", "model_type": "llm", "display_name": "Chat"}


@pytest.fixture
def command(mocker):
    transport = mocker.patch.object(commands, "AgentOSClient").return_value
    transport.model_command = AsyncMock()
    return transport.model_command


@pytest.mark.parametrize("status,body,error", [
    (429, b'{"code":"MODEL_PROVIDER_ERROR"}', ModelProviderError),
    (404, b"missing", LookupError),
    (400, b'{"code":"MODEL_VALIDATION"}', ValueError),
    (422, b"invalid", ValueError),
    (503, b"offline", RuntimeUpstreamError),
])
async def test_command_keeps_upstream_error_category_without_exposing_response(command, status, body, error):
    upstream = RuntimeUpstreamError(status, body, {})
    command.side_effect = upstream

    with pytest.raises(error) as exc:
        await commands.delete_model_for_tenant(USER, TENANT, "Chat")

    operation, payload, actor, tenant = command.await_args.args
    assert (operation, payload.display_name, actor, tenant) == (Operation.DEACTIVATE, "Chat", USER, TENANT)
    assert body.decode() not in str(exc.value)
    if error is RuntimeUpstreamError:
        assert exc.value is upstream
    else:
        assert exc.value.__cause__ is upstream
    if error is ModelProviderError:
        assert exc.value.upstream_status == 429


@pytest.mark.parametrize("count", [False, -1, "1", None])
async def test_tenant_deactivation_rejects_invalid_runtime_receipt(command, count):
    command.return_value = count
    with pytest.raises(RuntimeServiceUnavailableError, match="Invalid AgentOS model cleanup result"):
        await commands.deactivate_tenant_models(USER, TENANT)
    operation, payload, actor, tenant = command.await_args.args
    assert (operation, payload.model_dump(), actor, tenant) == (Operation.DEACTIVATE_TENANT, {}, USER, TENANT)


async def test_tenant_deactivation_returns_zero_for_a_repeated_request(command):
    command.return_value = 0
    assert await commands.deactivate_tenant_models(USER, TENANT) == 0


@pytest.mark.parametrize("batch,skip", [(False, False), (False, True), (True, False)])
async def test_defaults_are_backfilled_from_runtime_receipts_only(command, mocker, batch, skip):
    command.return_value = [7, 8, 7]
    binding = mocker.patch.object(commands, "run_blocking", return_value=["llm"])
    if batch:
        result = await commands.batch_create_models_for_tenant(
            USER, TENANT, {"api_key": "", "models": [DEFINITION], "provider": "openai", "type": "llm"},
        )
    else:
        result = await commands.create_model_for_tenant(USER, TENANT, DEFINITION, skip_default_backfill=skip)

    operation, payload, actor, tenant = command.await_args.args
    assert (operation, actor, tenant) == (Operation.IMPORT if batch else Operation.REGISTER, USER, TENANT)
    assert (payload.models if batch else [payload.definition()]) == [DEFINITION]
    if skip:
        binding.assert_not_awaited()
        assert result == {"auto_configured_defaults": []}
    else:
        binding.assert_awaited_once_with(
            "model-default-bindings", commands._backfill_default_model_slots,
            USER, TENANT, new_model_ids={7, 8}, lane="control-io", owner="management",
        )
        assert result == {"auto_configured_defaults": ["llm"]}


@pytest.mark.parametrize("kind", ["single", "batch"])
async def test_model_updates_send_only_the_requested_changes(command, kind):
    change = {"temperature": 0, "top_p": 0.75}
    if kind == "single":
        await commands.update_single_model_for_tenant(USER, TENANT, "Chat", change)
        expected = (Operation.UPDATE, {"display_name": "Chat", "patch": change})
    else:
        await commands.batch_update_models_for_tenant(USER, TENANT, [{"model_id": 7, **change}])
        expected = (Operation.BATCH_UPDATE, {"patches": [{"model_id": 7, **change}]})

    operation, payload, actor, tenant = command.await_args.args
    assert (operation, payload.model_dump()) == expected
    assert (actor, tenant) == (USER, TENANT)


async def test_provider_discovery_and_probe_keep_runtime_bindings_distinct(command):
    command.side_effect = [{"models": ["chat"]}, ["chat"], {"available": True}, {"available": False}]
    assert await commands.create_provider_models_for_tenant(
        TENANT, {"provider": "openai", "base_url": "https://model.example", "ssl_verify": False}, user_id=USER,
    ) == {"models": ["chat"]}
    assert await commands.list_provider_models_for_tenant(TENANT, "openai", "llm", user_id=USER) == ["chat"]
    assert await commands.check_model_connectivity("Chat", TENANT, "llm", user_id=USER, persist_status=False) == {
        "available": True,
    }
    assert await commands.verify_model_config_connectivity(DEFINITION, user_id=USER, tenant_id=TENANT) == {
        "available": False,
    }
    discovery, listed, health, probe = [call.args for call in command.await_args_list]
    assert [call[0] for call in (discovery, listed, health, probe)] == [
        Operation.DISCOVER, Operation.LIST_PROVIDER, Operation.HEALTHCHECK, Operation.PROBE,
    ]
    assert all(call[2:] == (USER, TENANT) for call in (discovery, listed, health, probe))
    assert discovery[1].base_url == "https://model.example"
    assert discovery[1].ssl_verify is False
    assert listed[1].model_dump() == {"provider": "openai", "model_type": "llm"}
    assert health[1].model_dump() == {"display_name": "Chat", "model_type": "llm", "persist_status": False}
    assert probe[1].model_name == "chat-model"


@pytest.mark.parametrize("output", [None, [], [[1.0], [2.0]], [""], [[]], [[True]], [[float("nan")]]])
async def test_embedding_client_rejects_malformed_provider_output(mocker, output):
    transport = mocker.patch.object(client, "_model_client").return_value
    transport.invoke_model = AsyncMock(return_value=SimpleNamespace(output=output))
    with pytest.raises(RuntimeServiceUnavailableError, match="Invalid AgentOS query embedding"):
        await client.embed_query(model_id=7, query="question", user_id=USER, tenant_id=TENANT, revision="r2")
    payload, actor, tenant = transport.invoke_model.await_args.args
    assert (payload.model_id, payload.expected_revision, payload.input, actor, tenant) == (7, "r2", ["question"], USER, TENANT)


def test_worker_model_calls_preserve_scope_and_filter_hidden_reasoning(mocker):
    transport = mocker.patch.object(client, "_model_client").return_value
    transport.invoke_model = AsyncMock(
        side_effect=[SimpleNamespace(output={"content": "<think>internal</think> answer "}),
                     SimpleNamespace(output=[[0.125, 0.25]])],
    )
    assert client.invoke_chat_prompt_in_worker(
        model_id=7, system_prompt="system", user_prompt="question", user_id=USER, tenant_id=TENANT,
    ) == "answer"
    assert client.embed_query_in_worker(model_id=8, query="question", user_id=USER, tenant_id=TENANT) == [0.125, 0.25]
    chat, embedding = transport.invoke_model.await_args_list
    request, actor, tenant = chat.args
    assert (actor, tenant, request.model_id) == (USER, TENANT, 7)
    assert [(message.role, message.content) for message in request.input] == [("system", "system"), ("user", "question")]
    assert (request.options.temperature, request.options.top_p) == (0.3, 0.95)
    assert (embedding.args[0].model_id, *embedding.args[1:]) == (8, USER, TENANT)
