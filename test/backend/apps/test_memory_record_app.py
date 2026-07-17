"""Unit tests for ``backend.apps.memory_record_app`` (Phase 2).

Tests use FastAPI's ``TestClient`` against the app router with stubbed
services so the request/response shape can be validated without touching
the database or Elasticsearch.
"""

import sys
import types
from unittest.mock import MagicMock

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
sys.modules["database"] = database_pkg
sys.modules["backend.database"] = database_pkg

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

    fake_record_service = MagicMock()
    fake_record_service.create_memory = MagicMock(
        return_value={"memory_id": 1, "event": "ADD", "layer": "user",
                       "memory_type": "long_term", "indexed": False}
    )
    fake_record_service.list_memories = MagicMock(
        return_value=[{"memory_id": 1, "content": "x"}]
    )
    fake_record_service.get_memory = MagicMock(
        return_value={"memory_id": 1, "content": "x", "user_id": "u1",
                      "layer": "user"}
    )
    fake_record_service.update_memory = MagicMock(return_value=True)
    fake_record_service.soft_delete_memory = MagicMock(return_value=True)
    record_service_mod.get_memory_record_service.return_value = fake_record_service

    fake_retrieval = MagicMock()
    async def _fake_search(request, **_):
        return [MemorySearchResult(memory_id="1", content="x", score=0.9,
                                    layer=MemoryLayer.AGENT)]
    fake_retrieval.search = _fake_search
    retrieval_service_mod.get_memory_retrieval_service.return_value = fake_retrieval

    fake_context = MagicMock()

    class _Ctx:
        tenant_long_term = []
        user_long_term = []
        agent_short_term = []
        external = []

        def to_prompt_text(self):
            return ""

    async def _fake_build(**_):
        return _Ctx()
    fake_context.build_context = _fake_build
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