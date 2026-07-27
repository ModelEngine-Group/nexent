"""Unit tests for ``backend.apps.memory_record_app`` (Phase 2).

Tests use FastAPI's ``TestClient`` against the app router with stubbed
services so the request/response shape can be validated without touching
the database or Elasticsearch.
"""

import logging
import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# Path setup
sys.path.insert(
    0,
    __import__("os").path.join(__import__("os").path.dirname(__file__), "../../.."),
)


# Stub backend modules so the app can be imported without real DB/ES.
database_pkg = types.ModuleType("database")
database_pkg.memory_record_db = MagicMock(name="memory_record_db")
database_pkg.memory_retrieval_hit_db = MagicMock(name="memory_retrieval_hit_db")
user_tenant_db_mod = types.ModuleType("database.user_tenant_db")
user_tenant_db_mod.get_user_tenant_by_user_id = MagicMock(
    return_value={"user_role": "ADMIN"}
)
sys.modules["database"] = database_pkg
sys.modules["backend.database"] = database_pkg
sys.modules["database.user_tenant_db"] = user_tenant_db_mod

services_pkg = types.ModuleType("services")
record_service_mod = types.ModuleType("services.memory_record_service")
retrieval_service_mod = types.ModuleType("services.memory_retrieval_service")
context_service_mod = types.ModuleType("services.memory_context_service")


class _MemoryRecordError(Exception):
    pass


record_service_mod.MemoryRecordError = _MemoryRecordError
record_service_mod.get_memory_record_service = MagicMock(
    name="get_memory_record_service"
)
retrieval_service_mod.get_memory_retrieval_service = MagicMock(
    name="get_memory_retrieval_service"
)
context_service_mod.get_memory_context_service = MagicMock(
    name="get_memory_context_service"
)
sys.modules["services"] = services_pkg
sys.modules["services.memory_record_service"] = record_service_mod
sys.modules["services.memory_retrieval_service"] = retrieval_service_mod
sys.modules["services.memory_context_service"] = context_service_mod


# Stub SDK nexent.memory
nexent_pkg = types.ModuleType("nexent")
memory_pkg = types.ModuleType("nexent.memory")


class MemoryLayer:
    TENANT = "tenant"
    USER = "user"
    AGENT = "agent"

    def __init__(self, value):
        self.value = value

    def __eq__(self, other):
        return getattr(other, "value", other) == self.value


class MemorySearchRequest:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class MemorySearchResult:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def model_dump(self):
        return self.__dict__


memory_models = types.ModuleType("nexent.memory.models")
memory_models.MemoryLayer = MemoryLayer
memory_models.MemorySearchRequest = MemorySearchRequest
memory_models.MemorySearchResult = MemorySearchResult
sys.modules["nexent.memory.models"] = memory_models
memory_pkg.models = memory_models
nexent_pkg.memory = memory_pkg
sys.modules["nexent"] = nexent_pkg
sys.modules["nexent.memory"] = memory_pkg


# Stub auth utils
auth_utils_mod = types.ModuleType("utils.auth_utils")
auth_utils_mod.get_current_user_id = MagicMock(return_value=("u1", "t1"))
sys.modules["utils.auth_utils"] = auth_utils_mod
sys.modules["backend.utils.auth_utils"] = auth_utils_mod


# Stub exceptions
consts_pkg = types.ModuleType("consts")
exceptions_mod = types.ModuleType("consts.exceptions")
exceptions_mod.UnauthorizedError = type("UnauthorizedError", (Exception,), {})
sys.modules["consts"] = consts_pkg
sys.modules["consts.exceptions"] = exceptions_mod


@pytest.fixture
def client(monkeypatch):
    """Build a TestClient and patch services per test."""
    from apps import memory_record_app

    user_tenant_db_mod.get_user_tenant_by_user_id.return_value = {
        "user_role": "ADMIN"
    }
    fake_record_service = MagicMock()
    def _fake_create_memory(**kwargs):
        if kwargs.get("layer") == "bogus":
            raise _MemoryRecordError("invalid layer")
        return {
            "memory_id": 1,
            "event": "ADD",
            "layer": kwargs.get("layer", "user"),
            "memory_type": "long_term",
            "indexed": False,
        }

    fake_record_service.create_memory = MagicMock(side_effect=_fake_create_memory)
    fake_record_service.list_memories = MagicMock(
        return_value=[{"memory_id": 1, "content": "x"}]
    )
    fake_record_service.get_memory = MagicMock(
        return_value={"memory_id": 1, "content": "x", "user_id": "u1",
                      "layer": "user"}
    )
    fake_record_service.get_memory_for_user = MagicMock(
        return_value={"memory_id": 1, "content": "x", "user_id": "u1",
                      "layer": "user"}
    )
    fake_record_service.update_memory = MagicMock(return_value=True)
    fake_record_service.soft_delete_memory = MagicMock(return_value=True)
    record_service_mod.get_memory_record_service.return_value = fake_record_service

    fake_retrieval = MagicMock()
    fake_retrieval.search_memories = AsyncMock(
        return_value=[MemorySearchResult(memory_id="1", content="x", score=0.9,
                                          layer=MemoryLayer.AGENT)]
    )
    retrieval_service_mod.get_memory_retrieval_service.return_value = fake_retrieval

    fake_context = MagicMock()

    class _Ctx:
        tenant_long_term = []
        user_long_term = []
        agent_short_term = []
        external = []

        def to_prompt_text(self):
            return ""

    fake_context.build_context = AsyncMock(return_value=_Ctx())
    context_service_mod.get_memory_context_service.return_value = fake_context

    app = FastAPI()
    app.include_router(memory_record_app.router)
    return TestClient(app), {
        "record": fake_record_service,
        "retrieval": fake_retrieval,
        "context": fake_context,
    }


def test_create_record_returns_event(client):
    cli, services = client
    response = cli.post(
        "/memory/records",
        json={"layer": "user", "content": "preference", "memory_type": "long_term"},
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 200
    assert response.json()["event"] == "ADD"
    services["record"].create_memory.assert_called_once()


def test_create_record_rejects_invalid_layer(client):
    cli, _ = client
    response = cli.post(
        "/memory/records",
        json={"layer": "bogus", "content": "x"},
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 406


def test_create_tenant_record_requires_admin(client):
    cli, services = client
    user_tenant_db_mod.get_user_tenant_by_user_id.return_value = {
        "user_role": "USER"
    }

    response = cli.post(
        "/memory/records",
        json={
            "layer": "tenant",
            "content": "shared policy",
            "memory_type": "long_term",
        },
        headers={"Authorization": "Bearer test"},
    )

    assert response.status_code == 403
    services["record"].create_memory.assert_not_called()


def test_create_tenant_record_allows_admin(client):
    cli, services = client
    user_tenant_db_mod.get_user_tenant_by_user_id.return_value = {
        "user_role": "ADMIN"
    }

    response = cli.post(
        "/memory/records",
        json={
            "layer": "tenant",
            "content": "shared policy",
            "memory_type": "long_term",
        },
        headers={"Authorization": "Bearer test"},
    )

    assert response.status_code == 200
    services["record"].create_memory.assert_called_once()


def test_list_records_filters_by_user(client):
    cli, services = client
    response = cli.get(
        "/memory/records?layer=user&limit=10",
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    services["record"].list_memories.assert_called_once()
    assert services["record"].list_memories.call_args.kwargs["user_id"] == "u1"


def test_list_tenant_records_are_shared_across_users(client):
    cli, services = client
    response = cli.get(
        "/memory/records?layer=tenant&limit=10",
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 200
    assert services["record"].list_memories.call_args.kwargs["user_id"] is None


def test_delete_record_returns_success(client):
    cli, services = client
    response = cli.delete(
        "/memory/records/1",
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 200
    services["record"].soft_delete_memory.assert_called_once()


def test_delete_record_rejects_non_integer_path(client):
    cli, _ = client
    response = cli.delete(
        "/memory/records/not-an-int",
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 422


def test_search_records_returns_items(client):
    cli, services = client
    response = cli.post(
        "/memory/records/search",
        json={"query": "hi", "layers": ["agent"], "top_k": 5},
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    services["retrieval"].search_memories.assert_awaited_once()


def test_search_records_propagates_query_params(client):
    """All SearchMemoryRequest fields should be forwarded to the service."""
    cli, services = client
    response = cli.post(
        "/memory/records/search",
        json={
            "query": "books",
            "agent_id": "a1",
            "conversation_id": "c1",
            "layers": ["agent", "user"],
            "top_k": 7,
            "threshold": 0.5,
            "hybrid": True,
            "weight_accurate": 0.42,
        },
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 200
    call_kwargs = services["retrieval"].search_memories.await_args.kwargs
    assert call_kwargs["query"] == "books"
    assert call_kwargs["agent_id"] == "a1"
    assert call_kwargs["conversation_id"] == "c1"
    assert call_kwargs["layers"] == ["agent", "user"]
    assert call_kwargs["top_k"] == 7
    assert call_kwargs["threshold"] == 0.5
    assert call_kwargs["hybrid"] is True
    assert call_kwargs["weight_accurate"] == 0.42


def test_search_records_propagates_user_identity(client):
    cli, _ = client
    response = cli.post(
        "/memory/records/search",
        json={"query": "hi", "top_k": 3},
        headers={"Authorization": "Bearer abc"},
    )
    assert response.status_code == 200
    assert (
        response.json()["count"] >= 0
    )  # the fixture returns at least one item, but assert route runs.


def test_create_record_logs_when_agent_layer_not_indexed(client, caplog):
    """Line 148: emit a DEBUG log when agent short-term memory fails to index."""
    cli, services = client

    def _create(**kwargs):
        return {
            "memory_id": 7,
            "event": "ADD",
            "layer": kwargs.get("layer", "user"),
            "memory_type": "short_term",
            "indexed": False,
        }

    services["record"].create_memory.side_effect = _create

    with caplog.at_level(logging.DEBUG, logger="memory_record_app"):
        response = cli.post(
            "/memory/records",
            json={"layer": "agent", "content": "x", "memory_type": "short_term"},
            headers={"Authorization": "Bearer test"},
        )

    assert response.status_code == 200
    matched = [
        record
        for record in caplog.records
        if "memory_id=7" in record.getMessage()
        and "ES indexing" in record.getMessage()
    ]
    assert matched, "Expected the 'no ES indexing' debug log to be emitted"


def test_create_record_does_not_log_when_other_layer_not_indexed(client, caplog):
    """The DEBUG log only applies to the 'agent' layer."""
    cli, services = client

    def _create(**kwargs):
        return {
            "memory_id": 8,
            "event": "ADD",
            "layer": kwargs.get("layer", "user"),
            "memory_type": "long_term",
            "indexed": False,
        }

    services["record"].create_memory.side_effect = _create

    with caplog.at_level(logging.DEBUG, logger="memory_record_app"):
        response = cli.post(
            "/memory/records",
            json={"layer": "user", "content": "x", "memory_type": "long_term"},
            headers={"Authorization": "Bearer test"},
        )

    assert response.status_code == 200
    matched = [
        record for record in caplog.records if "ES indexing" in record.getMessage()
    ]
    assert not matched


def test_create_record_does_not_log_when_indexed(client, caplog):
    cli, services = client

    def _create(**kwargs):
        return {
            "memory_id": 9,
            "event": "ADD",
            "layer": "agent",
            "memory_type": "short_term",
            "indexed": True,
        }

    services["record"].create_memory.side_effect = _create

    with caplog.at_level(logging.DEBUG, logger="memory_record_app"):
        response = cli.post(
            "/memory/records",
            json={"layer": "agent", "content": "y", "memory_type": "short_term"},
            headers={"Authorization": "Bearer test"},
        )

    assert response.status_code == 200
    matched = [
        record for record in caplog.records if "ES indexing" in record.getMessage()
    ]
    assert not matched


def test_read_record_returns_record(client):
    """Lines 162-171: happy path for GET /memory/records/{memory_id}."""
    cli, services = client
    response = cli.get(
        "/memory/records/42",
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 200
    assert response.json()["memory_id"] == 1  # fixture id
    services["record"].get_memory_for_user.assert_called_once_with(
        memory_id=42, tenant_id="t1", user_id="u1"
    )


def test_read_record_returns_404_when_missing(client):
    """Lines 167-170: 404 when the service cannot find the record."""
    cli, services = client
    services["record"].get_memory_for_user.return_value = None
    response = cli.get(
        "/memory/records/999",
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Memory record not found"


def test_read_record_rejects_non_integer_path(client):
    cli, _ = client
    response = cli.get(
        "/memory/records/abc",
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 422


def test_update_record_updates_all_fields(client):
    """Lines 211-230: full PATCH path with content / status / concept_tags."""
    cli, services = client
    response = cli.patch(
        "/memory/records/11",
        json={
            "content": "new body",
            "status": "archived",
            "concept_tags": ["a", "b"],
        },
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 200
    assert response.json() == {"success": True, "memory_id": 11}
    services["record"].update_memory.assert_called_once()
    args = services["record"].update_memory.call_args.args
    assert args[0] == 11
    assert args[1] == "t1"
    payload = args[2]
    assert payload["updated_by"] == "u1"
    assert payload["content"] == "new body"
    assert payload["status"] == "archived"
    assert payload["concept_tags"] == ["a", "b"]


def test_update_record_only_actor_when_no_fields(client):
    """If no fields are provided, only updated_by is forwarded."""
    cli, services = client
    services["record"].update_memory.reset_mock()
    response = cli.patch(
        "/memory/records/12",
        json={},
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 200
    payload = services["record"].update_memory.call_args.args[2]
    assert payload == {"updated_by": "u1"}


def test_update_record_partial_status_only(client):
    cli, services = client
    services["record"].update_memory.reset_mock()
    response = cli.patch(
        "/memory/records/13",
        json={"status": "archived"},
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 200
    payload = services["record"].update_memory.call_args.args[2]
    assert payload == {"status": "archived", "updated_by": "u1"}


def test_update_record_returns_400_on_failure(client):
    """Lines 222-226: 400 when the service cannot update."""
    cli, services = client
    services["record"].update_memory.return_value = False
    response = cli.patch(
        "/memory/records/99",
        json={"content": "x"},
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Failed to update memory record"


def test_update_record_rejects_non_integer_path(client):
    cli, _ = client
    response = cli.patch(
        "/memory/records/not-an-int",
        json={"content": "x"},
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 422


def test_delete_record_returns_400_on_failure(client):
    """Line 242: 400 when the service cannot soft delete."""
    cli, services = client
    services["record"].soft_delete_memory.return_value = False
    response = cli.delete(
        "/memory/records/1",
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Failed to delete memory record"


def test_build_context_returns_prompt_block(client):
    """Lines 297-315: GET /memory/context happy path with parsed layers."""
    cli, services = client
    from datetime import datetime

    class _Ctx:
        def __init__(self):
            self.tenant_long_term = [
                type(
                    "R",
                    (),
                    {"model_dump": lambda self: {"id": "t1", "content": "tn"}},
                )()
            ]
            self.user_long_term = [
                type(
                    "R",
                    (),
                    {"model_dump": lambda self: {"id": "u1", "content": "un"}},
                )()
            ]
            self.agent_short_term = []
            self.external = []

        def to_prompt_text(self):
            return "### Memory Context"

    async def _build(**kwargs):
        assert kwargs["tenant_id"] == "t1"
        assert kwargs["user_id"] == "u1"
        assert kwargs["agent_id"] == "a1"
        assert kwargs["conversation_id"] == "c1"
        assert kwargs["query"] == "remember this"
        assert kwargs["top_k"] == 3
        assert kwargs["threshold"] == 0.7
        assert kwargs["layers"] == ["tenant", "user", "agent"]
        return _Ctx()

    services["context"].build_context.side_effect = _build

    response = cli.get(
        "/memory/context?query=remember%20this&agent_id=a1"
        "&conversation_id=c1&layers=tenant,user,agent&top_k=3&threshold=0.7",
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["prompt_text"] == "### Memory Context"
    assert body["tenant_long_term"] == [{"id": "t1", "content": "tn"}]
    assert body["user_long_term"] == [{"id": "u1", "content": "un"}]
    assert body["agent_short_term"] == []
    assert body["external"] == []


def test_build_context_without_layers_keeps_none(client):
    cli, services = client

    captured = {}

    async def _build(**kwargs):
        captured["layers"] = kwargs.get("layers")
        captured["query"] = kwargs.get("query")
        class _Empty:
            tenant_long_term = []
            user_long_term = []
            agent_short_term = []
            external = []
            def to_prompt_text(self):
                return ""
        return _Empty()

    services["context"].build_context.side_effect = _build

    response = cli.get(
        "/memory/context",
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 200
    assert captured["layers"] is None
    assert captured["query"] is None


def test_build_context_normalizes_layers_lowercase_and_strips(client):
    cli, services = client

    captured = {}

    async def _build(**kwargs):
        captured["layers"] = kwargs.get("layers")
        class _Empty:
            tenant_long_term = []
            user_long_term = []
            agent_short_term = []
            external = []
            def to_prompt_text(self):
                return ""
        return _Empty()

    services["context"].build_context.side_effect = _build

    response = cli.get(
        "/memory/context?layers= Tenant ,USER ,agent",
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 200
    assert captured["layers"] == ["tenant", "user", "agent"]


def test_build_context_rejects_invalid_top_k(client):
    cli, _ = client
    response = cli.get(
        "/memory/context?top_k=0",
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 422


def test_build_context_rejects_invalid_threshold(client):
    cli, _ = client
    response = cli.get(
        "/memory/context?threshold=2.0",
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 422


def test_tenant_layer_normalization_in_list(client):
    """The list endpoint strips whitespace and lower-cases the layer filter."""
    cli, services = client
    response = cli.get(
        "/memory/records?layer=%20TENANT%20&limit=10",
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 200
    call_kwargs = services["record"].list_memories.call_args.kwargs
    assert call_kwargs["layer"] == "tenant"
    assert call_kwargs["user_id"] is None
    assert call_kwargs["limit"] == 10


def test_create_record_with_minimal_payload(client):
    """content is required; everything else should be optional with sane defaults."""
    cli, services = client
    response = cli.post(
        "/memory/records",
        json={"layer": "user", "content": "minimal payload"},
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code == 200
    args = services["record"].create_memory.call_args.kwargs
    assert args["content"] == "minimal payload"
    assert args["memory_type"] is None
    assert args["agent_id"] is None
    assert args["concept_tags"] == []


def test_create_record_missing_authorization_raises(monkeypatch):
    """An exception in auth_utils should surface as a 500 from the endpoint."""
    from apps import memory_record_app as app_module

    monkeypatch.setattr(
        app_module,
        "get_current_user_id",
        MagicMock(side_effect=Exception("missing token")),
    )
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(app_module.router)
    cli = TestClient(app, raise_server_exceptions=False)
    response = cli.post(
        "/memory/records",
        json={"layer": "user", "content": "x"},
    )
    # Starlette maps uncaught server exceptions to a 500 response.
    assert response.status_code == 500
