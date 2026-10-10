"""Regressions for publication-owned A2A version selection."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("version", ["1", "7"])
async def test_a2a_forwards_published_version_without_chat_persistence(mocker, streaming, version):
    from backend.services import a2a_server_service as module

    service = module.A2AServerService()
    registration = {"agent_id": 7, "tenant_id": "tenant", "version": version, "is_enabled": True}
    mocker.patch.object(module.a2a_agent_db, "get_server_agent_by_endpoint", return_value=registration)
    mocker.patch.object(service, "_resolve_task_id", return_value=(None, None, False))
    mocker.patch.object(service, "_store_user_message")
    mocker.patch.object(service, "_store_agent_response")

    async def body():
        yield 'data: {"type": "final_answer", "content": "done"}\n\n'

    response = MagicMock(status_code=200, headers={}, body_iterator=body())
    forward = mocker.patch.object(module, "forward_agent_run", new_callable=AsyncMock, return_value=response)
    # Caller metadata must not choose the executed version.
    payload = {"message": {"parts": [{"text": "hello"}], "metadata": {"version_no": 999}}}
    if streaming:
        events = [event async for event in service.handle_message_stream("endpoint", payload, user_id="caller")]
        assert events[-1]["statusUpdate"]["status"]["state"] == "TASK_STATE_COMPLETED"
    else:
        await service.handle_message_send("endpoint", payload, user_id="caller")

    forward.assert_awaited_once()
    request = forward.call_args.kwargs["agent_request"]
    assert request.agent_id == 7
    assert request.version_no == int(version)
    assert request.is_debug is True
    assert request.conversation_id is None
    assert request.model_dump(mode="json")["version_no"] == int(version)


def test_explicit_published_version_takes_precedence_over_debug(mocker):
    from services import knowledge_scope_service

    current = mocker.patch.object(knowledge_scope_service, "query_current_version_no", return_value=99)
    assert knowledge_scope_service.resolve_root_version(7, "tenant", 1, True) == 1
    current.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("version", [None, "", "0", "-1", "1.0.0", "draft", " 1", "1.5", True, 1, "１"])
async def test_a2a_invalid_version_never_dispatches_draft(mocker, streaming, version):
    from backend.services import a2a_server_service as module

    service = module.A2AServerService()
    registration = {"agent_id": 7, "tenant_id": "tenant", "version": version, "is_enabled": True}
    mocker.patch.object(module.a2a_agent_db, "get_server_agent_by_endpoint", return_value=registration)
    resolve = mocker.patch.object(service, "_resolve_task_id")
    store = mocker.patch.object(service, "_store_user_message")
    forward = mocker.patch.object(module, "forward_agent_run", new_callable=AsyncMock)
    with pytest.raises(module.EndpointNotFoundError, match="valid published version"):
        if streaming:
            [event async for event in service.handle_message_stream("endpoint", {"message": {}})]
        else:
            await service.handle_message_send("endpoint", {"message": {}})
    resolve.assert_not_called()
    store.assert_not_called()
    forward.assert_not_awaited()
