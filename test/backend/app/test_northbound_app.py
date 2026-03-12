import os
import sys
from unittest.mock import MagicMock, AsyncMock
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
import types
import sys as _sys

# Dynamically determine the backend path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../../backend"))
sys.path.append(backend_dir)


# Pre-mock heavy dependencies before importing router
sys.modules['consts'] = MagicMock()
sys.modules['consts.model'] = MagicMock()

consts_exceptions_mod = types.ModuleType("consts.exceptions")

class LimitExceededError(Exception):
    pass
class UnauthorizedError(Exception):
    pass
class SignatureValidationError(Exception):
    pass

consts_exceptions_mod.LimitExceededError = LimitExceededError
consts_exceptions_mod.UnauthorizedError = UnauthorizedError
consts_exceptions_mod.SignatureValidationError = SignatureValidationError

# Ensure the parent 'consts' is a module
if 'consts' not in _sys.modules or not isinstance(_sys.modules['consts'], types.ModuleType):
    consts_root = types.ModuleType("consts")
    consts_root.__path__ = []
    _sys.modules['consts'] = consts_root
else:
    consts_root = _sys.modules['consts']

consts_root.exceptions = consts_exceptions_mod
_sys.modules['consts.exceptions'] = consts_exceptions_mod
sys.modules['services'] = MagicMock()
sys.modules['services.northbound_service'] = MagicMock()
sys.modules['utils'] = MagicMock()
sys.modules['utils.auth_utils'] = MagicMock()

# Import router after setting mocks
from apps.northbound_app import router


app = FastAPI()
app.include_router(router)
client = TestClient(app)


def _build_headers(auth="Bearer test_jwt", request_id="req-123", aksk=True):
    headers = {
        "Authorization": auth,
        "X-Request-Id": request_id,
    }
    if aksk:
        headers.update({
            "X-Access-Key": "ak",
            "X-Timestamp": "1710000000",
            "X-Signature": "sig",
        })
    return headers


@pytest.mark.asyncio
async def test_health_check():
    resp = client.get("/nb/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["service"] == "northbound-api"


def test_run_chat_calls_service(monkeypatch):
    # Mock Bearer token validation to return valid token
    monkeypatch.setattr("apps.northbound_app.validate_bearer_token", lambda auth: (True, {"token_id": "t1"}))
    # Mock user/tenant lookup to return user and tenant
    monkeypatch.setattr("apps.northbound_app.get_user_and_tenant_by_access_key", lambda access_key: {
        "user_id": "u1", "tenant_id": "t1", "token_id": "t1"
    })
    async def _gen():
        yield b"data: hello\n\n"
    start_mock = AsyncMock(return_value=StreamingResponse(_gen(), media_type="text/event-stream"))
    monkeypatch.setattr("apps.northbound_app.start_streaming_chat", start_mock)

    # Use integer conversation_id as the endpoint expects Optional[int]
    payload = {"conversation_id": 1, "agent_name": "agent-a", "query": "hi"}
    headers = {**_build_headers(), "Idempotency-Key": "idem-1"}
    resp = client.post("/nb/v1/chat/run", json=payload, headers=headers)

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    # Validate call into service
    assert start_mock.await_count == 1
    args, kwargs = start_mock.call_args
    assert kwargs["conversation_id"] == 1
    assert kwargs["agent_name"] == "agent-a"
    assert kwargs["query"] == "hi"
    assert kwargs["idempotency_key"] == "idem-1"


def test_stop_chat_calls_service(monkeypatch):
    monkeypatch.setattr("apps.northbound_app.validate_bearer_token", lambda auth: (True, {"token_id": "t1"}))
    monkeypatch.setattr("apps.northbound_app.get_user_and_tenant_by_access_key", lambda access_key: {
        "user_id": "u1", "tenant_id": "t1", "token_id": "t1"
    })
    stop_mock = AsyncMock(return_value={"message": "success"})
    monkeypatch.setattr("apps.northbound_app.stop_chat", stop_mock)

    # Use integer conversation_id in URL path
    resp = client.get("/nb/v1/chat/stop/123", headers=_build_headers())
    assert resp.status_code == 200
    assert stop_mock.await_count == 1


def test_get_history_calls_service(monkeypatch):
    monkeypatch.setattr("apps.northbound_app.validate_bearer_token", lambda auth: (True, {"token_id": "t1"}))
    monkeypatch.setattr("apps.northbound_app.get_user_and_tenant_by_access_key", lambda access_key: {
        "user_id": "u1", "tenant_id": "t1", "token_id": "t1"
    })
    hist_mock = AsyncMock(return_value={"message": "success"})
    monkeypatch.setattr("apps.northbound_app.get_conversation_history", hist_mock)

    # Use integer conversation_id in URL path
    resp = client.get("/nb/v1/conversations/123", headers=_build_headers())
    assert resp.status_code == 200
    assert hist_mock.await_count == 1


def test_list_agents_calls_service(monkeypatch):
    monkeypatch.setattr("apps.northbound_app.validate_bearer_token", lambda auth: (True, {"token_id": "t1"}))
    monkeypatch.setattr("apps.northbound_app.get_user_and_tenant_by_access_key", lambda access_key: {
        "user_id": "u1", "tenant_id": "t1", "token_id": "t1"
    })
    agents_mock = AsyncMock(return_value={"message": "success", "data": []})
    monkeypatch.setattr("apps.northbound_app.get_agent_info_list", agents_mock)

    resp = client.get("/nb/v1/agents", headers=_build_headers())
    assert resp.status_code == 200
    assert agents_mock.await_count == 1


def test_list_conversations_calls_service(monkeypatch):
    monkeypatch.setattr("apps.northbound_app.validate_bearer_token", lambda auth: (True, {"token_id": "t1"}))
    monkeypatch.setattr("apps.northbound_app.get_user_and_tenant_by_access_key", lambda access_key: {
        "user_id": "u1", "tenant_id": "t1", "token_id": "t1"
    })
    list_mock = AsyncMock(return_value={"message": "success", "data": []})
    monkeypatch.setattr("apps.northbound_app.list_conversations", list_mock)

    resp = client.get("/nb/v1/conversations", headers=_build_headers())
    assert resp.status_code == 200
    assert list_mock.await_count == 1


def test_update_title_sets_headers(monkeypatch):
    monkeypatch.setattr("apps.northbound_app.validate_bearer_token", lambda auth: (True, {"token_id": "t1"}))
    monkeypatch.setattr("apps.northbound_app.get_user_and_tenant_by_access_key", lambda access_key: {
        "user_id": "u1", "tenant_id": "t1", "token_id": "t1"
    })
    # Ensure NorthboundContext yields plain string fields (avoid MagicMock in headers)
    class _NCtx:
        def __init__(self, request_id: str, tenant_id: str, user_id: str, authorization: str, token_id: int = 0):
            self.request_id = request_id
            self.tenant_id = tenant_id
            self.user_id = user_id
            self.authorization = authorization
            self.token_id = token_id
    monkeypatch.setattr("apps.northbound_app.NorthboundContext", _NCtx)
    update_mock = AsyncMock(return_value={"message": "success", "data": "nb-4", "idempotency_key": "ide-xyz"})
    monkeypatch.setattr("apps.northbound_app.update_conversation_title", update_mock)

    headers = {**_build_headers(request_id="req-999"), "Idempotency-Key": "ide-xyz"}
    resp = client.put("/nb/v1/conversations/123/title", params={"title": "New Title"}, headers=headers)
    assert resp.status_code == 200
    # Router wraps JSONResponse and should echo idempotency and request id
    assert resp.headers.get("Idempotency-Key") == "ide-xyz"
    assert resp.headers.get("X-Request-Id") == "req-999"
    assert update_mock.await_count == 1


def _std_headers(auth="Bearer test_jwt"):
    return {
        **_build_headers(auth=auth),
        "Idempotency-Key": "idem-xyz",
    }


@pytest.mark.parametrize("exc_cls, status", [
    (UnauthorizedError, 401),
    (LimitExceededError, 429),
    (SignatureValidationError, 401),
])
def test_run_chat_auth_exceptions_are_mapped(monkeypatch, exc_cls, status):
    # Force Bearer token validation to raise domain exceptions
    def _raise(*_, **__):
        raise exc_cls("boom")

    monkeypatch.setattr(
        "apps.northbound_app.validate_bearer_token", _raise)
    # Even if provided, auth should not be parsed because token validation fails first
    resp = client.post(
        "/nb/v1/chat/run",
        json={"conversation_id": 1, "agent_name": "a", "query": "hi"},
        headers=_std_headers(),
    )
    assert resp.status_code == status


def test_run_chat_missing_authorization_header_returns_401(monkeypatch):
    # When no Authorization header, validate_bearer_token returns (False, None)
    monkeypatch.setattr("apps.northbound_app.validate_bearer_token", lambda auth: (False, None))
    # No Authorization header
    headers = {k: v for k, v in _std_headers().items() if k.lower()
               != "authorization"}
    resp = client.post(
        "/nb/v1/chat/run",
        json={"conversation_id": 1, "agent_name": "a", "query": "hi"},
        headers=headers,
    )
    assert resp.status_code == 401
    assert "bearer token" in resp.json()["detail"].lower()


def test_run_chat_jwt_parse_exception_returns_401(monkeypatch):
    monkeypatch.setattr("apps.northbound_app.validate_bearer_token", lambda auth: (True, {"token_id": "t1"}))

    def _raise_user_lookup(_access_key):
        raise Exception("user lookup error")
    monkeypatch.setattr("apps.northbound_app.get_user_and_tenant_by_access_key", _raise_user_lookup)

    resp = client.post(
        "/nb/v1/chat/run",
        json={"conversation_id": 1, "agent_name": "a", "query": "hi"},
        headers=_std_headers(),
    )
    # When user lookup fails due to an invalid API key, return 401
    assert resp.status_code == 401
    assert "invalid api key" in resp.json()["detail"].lower()


def test_run_chat_jwt_missing_user_id_returns_400(monkeypatch):
    monkeypatch.setattr("apps.northbound_app.validate_bearer_token", lambda auth: (True, {"token_id": "t1"}))
    monkeypatch.setattr(
        "apps.northbound_app.get_user_and_tenant_by_access_key", lambda access_key: {
            "user_id": None, "tenant_id": "t1", "token_id": "t1"
        })

    resp = client.post(
        "/nb/v1/chat/run",
        json={"conversation_id": 1, "agent_name": "a", "query": "hi"},
        headers=_std_headers(),
    )
    assert resp.status_code == 400
    assert "user" in resp.json()["detail"].lower()


def test_run_chat_jwt_missing_tenant_id_returns_400(monkeypatch):
    monkeypatch.setattr("apps.northbound_app.validate_bearer_token", lambda auth: (True, {"token_id": "t1"}))
    monkeypatch.setattr(
        "apps.northbound_app.get_user_and_tenant_by_access_key", lambda access_key: {
            "user_id": "u1", "tenant_id": None, "token_id": "t1"
        })

    resp = client.post(
        "/nb/v1/chat/run",
        json={"conversation_id": 1, "agent_name": "a", "query": "hi"},
        headers=_std_headers(),
    )
    assert resp.status_code == 400
    assert "tenant" in resp.json()["detail"].lower()


def test_run_chat_internal_error_when_parsing_context_returns_401(monkeypatch):
    def _raise(*_, **__):
        raise Exception("unexpected")
    monkeypatch.setattr(
        "apps.northbound_app.validate_bearer_token", _raise)

    resp = client.post(
        "/nb/v1/chat/run",
        json={"conversation_id": 1, "agent_name": "a", "query": "hi"},
        headers=_std_headers(),
    )
    # Any exception during validation returns 401
    assert resp.status_code == 401


def test_run_chat_unexpected_service_error_maps_500(monkeypatch):
    monkeypatch.setattr("apps.northbound_app.validate_bearer_token", lambda auth: (True, {"token_id": "t1"}))
    monkeypatch.setattr("apps.northbound_app.get_user_and_tenant_by_access_key", lambda access_key: {
        "user_id": "u1", "tenant_id": "t1", "token_id": "t1"
    })
    start_mock = AsyncMock(side_effect=Exception("boom"))
    monkeypatch.setattr("apps.northbound_app.start_streaming_chat", start_mock)

    resp = client.post(
        "/nb/v1/chat/run",
        json={"conversation_id": 1, "agent_name": "a", "query": "hi"},
        headers=_std_headers(),
    )
    assert resp.status_code == 500


@pytest.mark.parametrize("path", [
    "/nb/v1/chat/stop/123",
    "/nb/v1/conversations/123",
    "/nb/v1/agents",
    "/nb/v1/conversations",
])
@pytest.mark.parametrize("exc_cls, status", [
    (UnauthorizedError, 401),
    (LimitExceededError, 429),
    (SignatureValidationError, 401),
])
def test_other_endpoints_auth_exceptions_are_mapped(monkeypatch, path, exc_cls, status):
    def _raise(*_, **__):
        raise exc_cls("boom")
    monkeypatch.setattr(
        "apps.northbound_app.validate_bearer_token", _raise)

    resp = client.get(path, headers=_build_headers())
    assert resp.status_code == status


@pytest.mark.parametrize(
    "path, target",
    [
        ("/nb/v1/chat/stop/123", "apps.northbound_app.stop_chat"),
        ("/nb/v1/conversations/123", "apps.northbound_app.get_conversation_history"),
        ("/nb/v1/agents", "apps.northbound_app.get_agent_info_list"),
        ("/nb/v1/conversations", "apps.northbound_app.list_conversations"),
    ],
)
def test_other_endpoints_unexpected_service_error_maps_500(monkeypatch, path, target):
    monkeypatch.setattr("apps.northbound_app.validate_bearer_token", lambda auth: (True, {"token_id": "t1"}))
    monkeypatch.setattr("apps.northbound_app.get_user_and_tenant_by_access_key", lambda access_key: {
        "user_id": "u1", "tenant_id": "t1", "token_id": "t1"
    })
    monkeypatch.setattr(target, AsyncMock(side_effect=Exception("boom")))

    resp = client.get(path, headers=_build_headers())
    assert resp.status_code == 500


def test_update_title_unexpected_service_error_maps_500(monkeypatch):
    monkeypatch.setattr("apps.northbound_app.validate_bearer_token", lambda auth: (True, {"token_id": "t1"}))
    monkeypatch.setattr("apps.northbound_app.get_user_and_tenant_by_access_key", lambda access_key: {
        "user_id": "u1", "tenant_id": "t1", "token_id": "t1"
    })
    monkeypatch.setattr("apps.northbound_app.update_conversation_title", AsyncMock(
        side_effect=Exception("boom")))

    resp = client.put(
        "/nb/v1/conversations/123/title",
        params={"title": "x"},
        headers=_build_headers(),
    )
    assert resp.status_code == 500


def test_run_chat_sets_headers_from_service_response(monkeypatch):
    # Mock Bearer token and user lookup
    monkeypatch.setattr("apps.northbound_app.validate_bearer_token", lambda auth: (True, {"token_id": "t1"}))
    monkeypatch.setattr("apps.northbound_app.get_user_and_tenant_by_access_key", lambda access_key: {
        "user_id": "u1", "tenant_id": "t1", "token_id": "t1"
    })

    # Ensure NorthboundContext yields plain string fields (avoid MagicMock in headers)
    class _NCtx:
        def __init__(self, request_id: str, tenant_id: str, user_id: str, authorization: str, token_id: int = 0):
            self.request_id = request_id
            self.tenant_id = tenant_id
            self.user_id = user_id
            self.authorization = authorization
            self.token_id = token_id

    monkeypatch.setattr("apps.northbound_app.NorthboundContext", _NCtx)

    async def _gen():
        yield b"data: ok\n\n"

    async def _start(ctx, conversation_id, agent_name, query, meta_data=None, idempotency_key=None):
        resp = StreamingResponse(_gen(), media_type="text/event-stream")
        # Service attaches headers in latest logic; emulate here
        resp.headers["X-Request-Id"] = ctx.request_id
        resp.headers["conversation_id"] = str(conversation_id)
        return resp

    monkeypatch.setattr("apps.northbound_app.start_streaming_chat", _start)

    headers = {**_std_headers(), "X-Request-Id": "rid-123"}
    resp = client.post(
        "/nb/v1/chat/run",
        json={"conversation_id": 1,
              "agent_name": "agent-a", "query": "hello"},
        headers=headers,
    )

    assert resp.status_code == 200
    assert resp.headers.get("X-Request-Id") == "rid-123"
    assert resp.headers.get("conversation_id") == "1"


def test_run_chat_service_error_maps_500(monkeypatch):
    monkeypatch.setattr("apps.northbound_app.validate_bearer_token", lambda auth: (True, {"token_id": "t1"}))
    monkeypatch.setattr("apps.northbound_app.get_user_and_tenant_by_access_key", lambda access_key: {
        "user_id": "u1", "tenant_id": "t1", "token_id": "t1"
    })

    async def _raise(*args, **kwargs):
        raise Exception("Failed to persist user message: boom")

    monkeypatch.setattr("apps.northbound_app.start_streaming_chat", _raise)

    resp = client.post(
        "/nb/v1/chat/run",
        json={"conversation_id": 1,
              "agent_name": "agent-a", "query": "hello"},
        headers=_std_headers(),
    )

    assert resp.status_code == 500
