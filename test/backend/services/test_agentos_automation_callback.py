# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from contracts.agentos import AgentOperation, AgentRunLookup, AgentRunReference, ManagementOperation, ToolBinding
from infrastructure.agent_tool_config import AUTOMATION_PROPOSAL_TOOL
from infrastructure.agentos_identity import AgentOSIdentityError, ServicePrincipal, sign_call, verify_call
from management.services.automation import agentos_callback
from runtime.agentos import prepared_automation
from runtime.agentos.prepared_automation import materialize_automation_tool


ACTOR = ServicePrincipal("actor", "tenant")
REFERENCE = AgentRunReference(conversation_id=42, run_id="a" * 32)


def test_reverse_agentos_token_is_distinct_and_body_bound(monkeypatch):
    from contracts.constants import environment

    monkeypatch.setattr(environment, "JWT_SECRET", "synthetic-agentos-secret-for-callback")
    body = REFERENCE.model_dump_json().encode()
    operation = ManagementOperation.AUTOMATION_PROPOSAL
    reverse = sign_call(operation, body, ACTOR)
    assert verify_call(reverse, operation, body) == ACTOR
    forward = sign_call(AgentOperation.RUN, body, ACTOR)
    with pytest.raises(AgentOSIdentityError):
        verify_call(forward, operation, body)
    with pytest.raises(AgentOSIdentityError):
        verify_call(reverse, AgentOperation.RUN, body)
    with pytest.raises(AgentOSIdentityError):
        verify_call(reverse, operation, body + b" ")


@pytest.mark.asyncio
async def test_callback_confirms_owned_turn_and_uses_its_stored_message(mocker):
    turn = SimpleNamespace(assistant_message_id=None)
    context = agentos_callback.AutomationToolRuntimeContext(
        tenant_id="tenant", user_id="actor", conversation_id=42, agent_id=7, user_message="saved input",
        source_message_id=91,
    )

    async def inline(_name, fn, *args, lane, owner):
        return fn(*args)

    mocker.patch.object(agentos_callback, "run_blocking", side_effect=inline)
    mocker.patch.object(agentos_callback.store, "automation_turn", return_value=turn)
    confirm = mocker.patch.object(agentos_callback.store, "confirm_turn", return_value=turn)
    mocker.patch.object(agentos_callback, "_read_context", return_value=context)
    runtime = SimpleNamespace(inspect_run=AsyncMock(return_value=SimpleNamespace(
        **REFERENCE.model_dump(), status="running", cancellation_requested=False,
    )))
    mocker.patch.object(agentos_callback, "_agentos_client", return_value=runtime)
    create = mocker.patch.object(agentos_callback.agent_loop_automation_tool_adapter, "create_proposal",
                                 return_value={"status": "proposal_ready"})

    assert await agentos_callback.create_automation_proposal(REFERENCE, ACTOR) == {"status": "proposal_ready"}
    runtime.inspect_run.assert_awaited_once_with(AgentRunLookup(**REFERENCE.model_dump()), "actor", "tenant")
    confirm.assert_called_once_with(turn)
    create.assert_awaited_once_with(context, "")


@pytest.mark.asyncio
async def test_unbound_callback_never_reaches_runtime_or_creates_a_proposal(mocker):
    mocker.patch.object(agentos_callback, "run_blocking", return_value=None)
    client = mocker.patch.object(agentos_callback, "_agentos_client")
    create = mocker.patch.object(agentos_callback.agent_loop_automation_tool_adapter, "create_proposal")
    assert await agentos_callback.create_automation_proposal(REFERENCE, ACTOR) is None
    client.assert_not_called()
    create.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "cancellation_requested"), [("completed", False), ("running", True)])
async def test_finished_or_cancelled_run_cannot_create_a_proposal(mocker, status, cancellation_requested):
    mocker.patch.object(agentos_callback, "run_blocking", return_value=SimpleNamespace(assistant_message_id=61))
    runtime = SimpleNamespace(inspect_run=AsyncMock(return_value=SimpleNamespace(
        **REFERENCE.model_dump(), status=status, cancellation_requested=cancellation_requested,
    )))
    mocker.patch.object(agentos_callback, "_agentos_client", return_value=runtime)
    create = mocker.patch.object(agentos_callback.agent_loop_automation_tool_adapter, "create_proposal")
    assert await agentos_callback.create_automation_proposal(REFERENCE, ACTOR) is None
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_dedicated_proposal_request_signs_the_same_owned_turn(monkeypatch):
    from contracts.constants import environment

    monkeypatch.setattr(environment, "JWT_SECRET", "synthetic-agentos-secret-for-callback")
    monkeypatch.setattr(environment, "MANAGEMENT_AGENTOS_URL", "http://management.test")
    operation = ManagementOperation.AUTOMATION_PROPOSAL
    seen = []

    def handler(request):
        assert request.url.path == f"/api{operation.value}"
        assert request.content == REFERENCE.model_dump_json().encode()
        _, token = request.headers["authorization"].split()
        assert verify_call(token, operation, request.content) == ACTOR
        seen.append(request.method)
        return httpx.Response(200, json={"status": "proposal_ready", "proposal": {"proposal_id": 1}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(prepared_automation.httpx, "AsyncClient", lambda **kwargs: client)

    assert await prepared_automation.request_automation_proposal(REFERENCE, ACTOR) == {
        "status": "proposal_ready", "proposal": {"proposal_id": 1},
    }
    assert seen == ["POST"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("status_code", "body", "error", "cause"), [
    (503, b'{}', "unavailable", httpx.HTTPStatusError),
    (200, b'not JSON', "unavailable", ValueError),
    (200, b'[]', "invalid result", type(None)),
    (200, b'{"status": 1}', "invalid result", type(None)),
])
async def test_dedicated_proposal_request_rejects_invalid_upstream_results(
    monkeypatch, status_code, body, error, cause,
):
    from contracts.constants import environment

    monkeypatch.setattr(environment, "JWT_SECRET", "synthetic-agentos-secret-for-callback")
    monkeypatch.setattr(environment, "MANAGEMENT_AGENTOS_URL", "http://management.test")
    transport = httpx.MockTransport(lambda _request: httpx.Response(status_code, content=body))
    client = httpx.AsyncClient(transport=transport)
    monkeypatch.setattr(prepared_automation.httpx, "AsyncClient", lambda **_options: client)

    with pytest.raises(RuntimeError, match=error) as exc:
        await prepared_automation.request_automation_proposal(REFERENCE, ACTOR)

    assert isinstance(exc.value.__cause__, cause)


@pytest.mark.parametrize("status_code", [200, 503])
def test_runtime_bound_tool_uses_the_owned_turn_instead_of_model_text(monkeypatch, status_code):
    from contracts.constants import environment

    monkeypatch.setattr(environment, "JWT_SECRET", "synthetic-agentos-secret-for-callback")
    monkeypatch.setattr(environment, "MANAGEMENT_AGENTOS_URL", "http://management.test")
    result = {"status": "proposal_ready", "proposal": {"proposal_id": 1, "task_id": None}}
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(status_code, json=result)

    client = httpx.Client(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(prepared_automation.httpx, "Client", lambda **_options: client)
    binding = ToolBinding(tool_id=AUTOMATION_PROPOSAL_TOOL, version="1")
    tool = materialize_automation_tool(SimpleNamespace(tools=[binding]), ACTOR, REFERENCE)[AUTOMATION_PROPOSAL_TOOL]
    create_proposal = tool.metadata["create_proposal"]

    if status_code == 200:
        assert create_proposal("Use a different conversation") == result
    else:
        with pytest.raises(RuntimeError, match="unavailable") as exc:
            create_proposal("Use a different conversation")
        assert isinstance(exc.value.__cause__, httpx.HTTPStatusError)

    request, = requests
    operation = ManagementOperation.AUTOMATION_PROPOSAL
    assert request.method == "POST"
    assert request.url == httpx.URL(f"http://management.test/api{operation.value}")
    assert request.content == REFERENCE.model_dump_json().encode()
    assert verify_call(request.headers["authorization"].removeprefix("Bearer "), operation, request.content) == ACTOR


@pytest.mark.parametrize("change", [{"version": "2"}, {"parameters": {"query": "untrusted"}}, {"credential_ref": "key"}])
def test_runtime_rejects_unapproved_tool_parameters(change):
    binding = ToolBinding.model_validate({"tool_id": AUTOMATION_PROPOSAL_TOOL, "version": "1"} | change)
    with pytest.raises(ValueError, match="Unsupported"):
        materialize_automation_tool(SimpleNamespace(tools=[binding]), ACTOR, REFERENCE)


def test_runtime_rejects_proposal_tool_outside_the_public_root():
    binding = ToolBinding(tool_id=AUTOMATION_PROPOSAL_TOOL, version="1")
    with pytest.raises(ValueError, match="Unsupported"):
        materialize_automation_tool(SimpleNamespace(tools=[binding]), ACTOR, None)
