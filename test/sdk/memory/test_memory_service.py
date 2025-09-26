import sys
import types
from typing import Any, Dict, List

import pytest


# ---------------------------------------------------------------------------
# Install lightweight stubs before importing the module under test to avoid
# importing real heavy dependencies from memory_core/memory_utils.
# ---------------------------------------------------------------------------

dummy_memory_core = types.ModuleType("sdk.nexent.memory.memory_core")


async def _default_get_memory_instance(_: Dict[str, Any]):
    class _Noop:
        async def add(self, *args, **kwargs):
            return {"results": []}

        async def search(self, *args, **kwargs):
            return {"results": []}

        async def get_all(self, *args, **kwargs):
            return {"results": []}

        async def delete(self, *args, **kwargs):
            return {"ok": True}

        async def reset(self, *args, **kwargs):
            return None

    return _Noop()


setattr(dummy_memory_core, "get_memory_instance", _default_get_memory_instance)

dummy_memory_utils = types.ModuleType("sdk.nexent.memory.memory_utils")


def _build_memory_identifiers(*, memory_level: str, user_id: str, tenant_id: str) -> str:  # noqa: ARG001
    # Keep it simple for tests; only shape matters for callers.
    return f"mem:{tenant_id}/{user_id}:{memory_level}"


setattr(dummy_memory_utils, "build_memory_identifiers", _build_memory_identifiers)

sys.modules.setdefault("sdk.nexent.memory.memory_core", dummy_memory_core)
sys.modules.setdefault("sdk.nexent.memory.memory_utils", dummy_memory_utils)


from sdk.nexent.memory import memory_service  # noqa: E402  (import after stubs)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class DummyMemory:
    def __init__(self, config: Dict[str, Any] | None = None):
        self.config = config or {}
        self.calls: Dict[str, List[Dict[str, Any]]] = {
            "add": [],
            "search": [],
            "get_all": [],
            "delete": [],
            "reset": [],
        }

    async def add(self, messages, *, user_id=None, agent_id=None, infer=True):  # noqa: ANN001
        self.calls["add"].append({
            "messages": messages,
            "user_id": user_id,
            "agent_id": agent_id,
            "infer": infer,
        })
        results = self.config.get("add_results", [
            {"id": "1", "memory": "m1", "event": "ADD"},
        ])
        return {"results": results}

    async def search(self, *, query, limit, threshold, user_id, agent_id=None):  # noqa: ANN001
        self.calls["search"].append({
            "query": query,
            "limit": limit,
            "threshold": threshold,
            "user_id": user_id,
            "agent_id": agent_id,
        })
        results: Any = self.config.get("search_results", [
            {"id": "1", "memory": "m1", "score": 0.9, "agent_id": agent_id},
            {"id": "2", "memory": "m2", "score": 0.7},
        ])
        if self.config.get("search_results_are_coroutine"):
            async def _coro():
                return results

            return {"results": _coro()}
        return {"results": results}

    async def get_all(self, *, user_id, agent_id=None):  # noqa: ANN001
        self.calls["get_all"].append({"user_id": user_id, "agent_id": agent_id})
        results: Any = self.config.get("all_results", [
            {"id": "1", "memory": "m1"},
            {"id": "2", "memory": "m2", "agent_id": agent_id or "a"},
        ])
        if self.config.get("all_results_are_coroutine"):
            async def _coro():
                return results

            return {"results": _coro()}
        return {"results": results}

    async def delete(self, *, memory_id):  # noqa: ANN001
        self.calls["delete"].append({"memory_id": memory_id})
        fail_ids = set(self.config.get("delete_fail_ids", []))
        if memory_id in fail_ids:
            raise RuntimeError("delete failed")
        return {"ok": True}

    async def reset(self):  # noqa: D401
        """Simulate reset operation."""
        self.calls["reset"].append({})
        if self.config.get("reset_raises"):
            raise RuntimeError("boom")
        return None


async def _return_dummy_memory(config: Dict[str, Any] | None = None):
    return DummyMemory(config)


# ---------------------------------------------------------------------------
# Tests for add_memory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_memory_user_and_agent_paths(monkeypatch):
    mem = DummyMemory()

    async def _gm(_: Dict[str, Any]):
        return mem

    monkeypatch.setattr(memory_service, "get_memory_instance", _gm)

    # user level (no agent_id)
    res_user = await memory_service.add_memory(
        messages=[{"role": "user", "content": "hi"}],
        memory_level="user",
        memory_config={},
        tenant_id="t1",
        user_id="u1",
        agent_id=None,
        infer=True,
    )
    assert res_user["results"][0]["event"] == "ADD"
    assert mem.calls["add"][0]["agent_id"] is None

    # agent level (agent_id included)
    res_agent = await memory_service.add_memory(
        messages="hello",
        memory_level="agent",
        memory_config={},
        tenant_id="t1",
        user_id="u1",
        agent_id="a1",
        infer=True,
    )
    assert res_agent["results"][0]["event"] == "ADD"
    assert mem.calls["add"][1]["agent_id"] == "a1"


@pytest.mark.asyncio
async def test_add_memory_invalid_level(monkeypatch):
    monkeypatch.setattr(memory_service, "get_memory_instance", _return_dummy_memory)
    with pytest.raises(ValueError):
        await memory_service.add_memory(
            messages="hi",
            memory_level="wrong",
            memory_config={},
            tenant_id="t1",
            user_id="u1",
        )


# ---------------------------------------------------------------------------
# Tests for add_memory_in_levels
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_memory_in_levels_merge_priority(monkeypatch):
    # Simulate overlapping ids across levels; higher priority event should win.
    # Priority: DELETE > ADD > UPDATE > NONE
    async def _fake_add(messages, memory_level, memory_config, tenant_id, user_id, agent_id, infer):  # noqa: ARG001
        mapping = {
            "agent": [{"id": "X", "memory": "m", "event": "ADD"}],
            "user_agent": [{"id": "X", "memory": "m", "event": "DELETE"}],
            "user": [{"id": "Y", "memory": "m2", "event": "UPDATE"}],
            "tenant": [{"id": "Y", "memory": "m2", "event": "NONE"}],
        }
        return {"results": mapping.get(memory_level, [])}

    monkeypatch.setattr(memory_service, "add_memory", _fake_add)

    out = await memory_service.add_memory_in_levels(
        messages="hi",
        memory_config={},
        tenant_id="t1",
        user_id="u1",
        agent_id="a1",
        memory_levels=["agent", "user_agent", "tenant", "user"],
    )

    results = {item["id"]: item["event"] for item in out["results"]}
    # For id X, DELETE should override ADD
    assert results["X"] == "DELETE"
    # For id Y, UPDATE should override NONE
    assert results["Y"] == "UPDATE"


# ---------------------------------------------------------------------------
# Tests for search_memory and search_memory_in_levels
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_memory_filters_and_coroutine_results(monkeypatch):
    mem = DummyMemory({
        "search_results": [
            {"id": "1", "memory": "u", "score": 0.9},
            {"id": "2", "memory": "a", "score": 0.8, "agent_id": "a1"},
        ],
        "search_results_are_coroutine": True,
    })

    async def _gm(_: Dict[str, Any]):
        return mem

    monkeypatch.setattr(memory_service, "get_memory_instance", _gm)

    # user level should filter out agent memories
    res_user = await memory_service.search_memory(
        query_text="q",
        memory_level="user",
        memory_config={},
        tenant_id="t1",
        user_id="u1",
        top_k=3,
        threshold=0.5,
    )
    assert all("agent_id" not in r for r in res_user["results"])  # filtered

    # agent level should keep only agent memories
    res_agent = await memory_service.search_memory(
        query_text="q",
        memory_level="agent",
        memory_config={},
        tenant_id="t1",
        user_id="u1",
        agent_id="a1",
    )
    assert all("agent_id" in r for r in res_agent["results"])  # filtered


@pytest.mark.asyncio
async def test_search_memory_invalid_level(monkeypatch):
    monkeypatch.setattr(memory_service, "get_memory_instance", _return_dummy_memory)
    with pytest.raises(ValueError):
        await memory_service.search_memory(
            query_text="q",
            memory_level="bad",
            memory_config={},
            tenant_id="t1",
            user_id="u1",
        )


@pytest.mark.asyncio
async def test_search_memory_in_levels_aggregates_and_order(monkeypatch):
    async def _fake_search(query_text, memory_level, memory_config, tenant_id, user_id, agent_id, top_k, threshold):  # noqa: ARG001
        return {"results": [
            {"id": f"{memory_level}-1", "memory": "m", "score": 0.9},
        ]}

    monkeypatch.setattr(memory_service, "search_memory", _fake_search)

    levels = ["tenant", "user", "agent", "user_agent"]
    out = await memory_service.search_memory_in_levels(
        query_text="q",
        memory_config={},
        tenant_id="t1",
        user_id="u1",
        agent_id="a1",
        top_k=2,
        threshold=0.6,
        memory_levels=levels,
    )
    # Ensure each level contributes one result and order preserved
    got_levels = [r["memory_level"] for r in out["results"]]
    assert got_levels == levels


# ---------------------------------------------------------------------------
# Tests for list_memory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_memory_filters_and_counts(monkeypatch):
    mem = DummyMemory({
        "all_results": [
            {"id": "1", "memory": "m"},  # no agent_id
            {"id": "2", "memory": "a", "agent_id": "a1"},
            {"id": "3", "memory": "m3"},
        ],
        "all_results_are_coroutine": True,
    })

    async def _gm(_: Dict[str, Any]):
        return mem

    monkeypatch.setattr(memory_service, "get_memory_instance", _gm)

    # tenant level -> only items without agent_id
    out_tenant = await memory_service.list_memory(
        memory_level="tenant",
        memory_config={},
        tenant_id="t1",
        user_id="u1",
    )
    assert out_tenant["total"] == 2
    assert all("agent_id" not in r for r in out_tenant["items"])

    # agent level -> only items with agent_id
    out_agent = await memory_service.list_memory(
        memory_level="agent",
        memory_config={},
        tenant_id="t1",
        user_id="u1",
        agent_id="a1",
    )
    assert out_agent["total"] == 1
    assert all("agent_id" in r for r in out_agent["items"])


# ---------------------------------------------------------------------------
# Tests for delete_memory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_memory_success(monkeypatch):
    mem = DummyMemory()

    async def _gm(_: Dict[str, Any]):
        return mem

    monkeypatch.setattr(memory_service, "get_memory_instance", _gm)

    res = await memory_service.delete_memory("X", memory_config={})
    assert res["ok"] is True
    assert mem.calls["delete"][0]["memory_id"] == "X"


@pytest.mark.asyncio
async def test_delete_memory_unsupported(monkeypatch):
    class NoDelete:
        async def reset(self):  # pragma: no cover - not used here
            return None

    async def _gm(_: Dict[str, Any]):
        return NoDelete()

    monkeypatch.setattr(memory_service, "get_memory_instance", _gm)

    with pytest.raises(AttributeError):
        await memory_service.delete_memory("X", memory_config={})


# ---------------------------------------------------------------------------
# Tests for clear_memory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clear_memory_counts_and_failures(monkeypatch):
    mem = DummyMemory({
        "all_results": [
            {"id": "1", "memory": "m"},
            {"id": "2", "memory": "a", "agent_id": "a1"},
            {"id": "3", "memory": "m3"},
        ],
        "delete_fail_ids": {"3"},
    })

    async def _gm(_: Dict[str, Any]):
        return mem

    monkeypatch.setattr(memory_service, "get_memory_instance", _gm)

    # tenant level: should attempt to delete ids 1 and 3, with 3 failing
    out = await memory_service.clear_memory(
        memory_level="tenant",
        memory_config={},
        tenant_id="t1",
        user_id="u1",
    )
    assert out == {"deleted_count": 1, "total_count": 2}


# ---------------------------------------------------------------------------
# Tests for reset_all_memory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_all_memory_success_and_failure(monkeypatch):
    ok_mem = DummyMemory()
    bad_mem = DummyMemory({"reset_raises": True})

    async def _gm_ok(_: Dict[str, Any]):
        return ok_mem

    async def _gm_bad(_: Dict[str, Any]):
        return bad_mem

    monkeypatch.setattr(memory_service, "get_memory_instance", _gm_ok)
    assert await memory_service.reset_all_memory({}) is True

    monkeypatch.setattr(memory_service, "get_memory_instance", _gm_bad)
    assert await memory_service.reset_all_memory({}) is False


# ---------------------------------------------------------------------------
# Tests for _filter_by_memory_level
# ---------------------------------------------------------------------------


def test_filter_by_memory_level_variants():
    data = [
        {"id": "1"},
        {"id": "2", "agent_id": "a1"},
    ]
    assert memory_service._filter_by_memory_level("tenant", data) == [{"id": "1"}]
    assert memory_service._filter_by_memory_level("user", data) == [{"id": "1"}]
    assert memory_service._filter_by_memory_level("agent", data) == [{"id": "2", "agent_id": "a1"}]
    assert memory_service._filter_by_memory_level("user_agent", data) == [{"id": "2", "agent_id": "a1"}]

    with pytest.raises(ValueError):
        memory_service._filter_by_memory_level("bad", data)


# ---------------------------------------------------------------------------
# Additional coverage for error paths and clear_model_memories
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_memory_in_levels_ignores_failing_levels(monkeypatch):
    async def _fake_add(messages, memory_level, memory_config, tenant_id, user_id, agent_id, infer):  # noqa: ARG001
        if memory_level == "agent":
            raise RuntimeError("boom")
        return {"results": [{"id": memory_level, "event": "ADD"}]}

    monkeypatch.setattr(memory_service, "add_memory", _fake_add)

    out = await memory_service.add_memory_in_levels(
        messages="hi",
        memory_config={},
        tenant_id="t1",
        user_id="u1",
        agent_id="a1",
        memory_levels=["agent", "user"],
    )
    # agent failed and returns [], user succeeded
    assert [r["id"] for r in out["results"]] == ["user"]


@pytest.mark.asyncio
async def test_search_memory_in_levels_ignores_failing_levels_and_preserves_order(monkeypatch):
    async def _fake_search(query_text, memory_level, memory_config, tenant_id, user_id, agent_id, top_k, threshold):  # noqa: ARG001
        if memory_level == "user":
            raise RuntimeError("fail user")
        return {"results": [{"id": f"ok-{memory_level}", "memory": "m", "score": 0.9}]}

    monkeypatch.setattr(memory_service, "search_memory", _fake_search)

    levels = ["tenant", "user", "agent"]
    out = await memory_service.search_memory_in_levels(
        query_text="q",
        memory_config={},
        tenant_id="t1",
        user_id="u1",
        agent_id="a1",
        top_k=2,
        threshold=0.6,
        memory_levels=levels,
    )
    # Only tenant and agent appear, in their relative order
    got_ids = [r["id"] for r in out["results"]]
    assert got_ids == ["ok-tenant", "ok-agent"]


@pytest.mark.asyncio
async def test_list_memory_non_coroutine_results(monkeypatch):
    class Mem:
        async def get_all(self, *, user_id, agent_id=None):  # noqa: ANN001
            return {"results": [
                {"id": "1", "memory": "x"},
                {"id": "2", "memory": "a", "agent_id": agent_id or "a1"},
            ]}

    async def _gm(_: Dict[str, Any]):
        return Mem()

    monkeypatch.setattr(memory_service, "get_memory_instance", _gm)

    # user level -> only items without agent_id
    out = await memory_service.list_memory(
        memory_level="user",
        memory_config={},
        tenant_id="t1",
        user_id="u1",
    )
    assert out == {"items": [{"id": "1", "memory": "x"}], "total": 1}


# ---------------------------- clear_model_memories ---------------------------


class _DummyESCore:
    def __init__(self, exists_behavior=None, delete_raises=False):
        if exists_behavior is None:
            def exists_behavior(index):  # noqa: ANN001
                return True
        self._exists_behavior = exists_behavior
        indices = types.SimpleNamespace(exists=self._exists_behavior)
        self.client = types.SimpleNamespace(indices=indices)
        self._delete_raises = delete_raises
        self.deleted = []

    def delete_index(self, index_name: str):
        self.deleted.append(index_name)
        if self._delete_raises:
            raise RuntimeError("delete failed")


@pytest.mark.asyncio
async def test_clear_model_memories_early_exit_when_index_missing(monkeypatch):
    es = _DummyESCore(exists_behavior=lambda index: False)

    # Ensure reset is not called when index missing
    called = {"reset": False}

    async def _reset(cfg):  # noqa: ANN001
        called["reset"] = True
        return True

    monkeypatch.setattr(memory_service, "reset_all_memory", _reset)

    ok = await memory_service.clear_model_memories(
        es_core=es,
        model_repo="jina-ai",
        model_name="jina-embeddings-v2-base-en",
        embedding_dims=768,
        base_memory_config={"vector_store": {
            "config": {}}, "embedder": {"config": {}}},
    )
    assert ok is True
    assert called["reset"] is False
    assert es.deleted == []


@pytest.mark.asyncio
async def test_clear_model_memories_success_and_config_adjustment_with_repo(monkeypatch):
    es = _DummyESCore(exists_behavior=lambda index: True)
    seen_config: Dict[str, Any] = {}

    async def _reset(cfg):  # noqa: ANN001
        seen_config.update(cfg)
        return True

    monkeypatch.setattr(memory_service, "reset_all_memory", _reset)

    ok = await memory_service.clear_model_memories(
        es_core=es,
        model_repo="jina-ai",
        model_name="jina-embeddings-v2-base-en",
        embedding_dims=1024,
        base_memory_config={
            "vector_store": {"config": {"collection_name": "ignored", "embedding_model_dims": 0}},
            "embedder": {"config": {"embedding_dims": 0}},
        },
    )
    assert ok is True

    # Index name should include repo and dims
    assert es.deleted == ["mem0_jina-ai_jina-embeddings-v2-base-en_1024"]
    # Config passed to reset should be adjusted (without mutating base)
    assert seen_config["vector_store"]["config"]["collection_name"] == "mem0_jina-ai_jina-embeddings-v2-base-en_1024"
    assert seen_config["vector_store"]["config"]["embedding_model_dims"] == 1024
    assert seen_config["embedder"]["config"]["embedding_dims"] == 1024


@pytest.mark.asyncio
async def test_clear_model_memories_handles_es_exists_exception(monkeypatch):
    def _exists_raises(index):  # noqa: ANN001
        raise RuntimeError("exists failed")

    es = _DummyESCore(exists_behavior=_exists_raises)

    # reset is called despite exists() failing
    called = {"reset": 0}

    async def _reset(cfg):  # noqa: ANN001
        called["reset"] += 1
        return True

    monkeypatch.setattr(memory_service, "reset_all_memory", _reset)

    ok = await memory_service.clear_model_memories(
        es_core=es,
        model_repo="",
        model_name="m",
        embedding_dims=128,
        base_memory_config={"vector_store": {
            "config": {}}, "embedder": {"config": {}}},
    )
    assert ok is True
    assert called["reset"] == 1
    assert es.deleted == ["mem0_m_128"]


@pytest.mark.asyncio
async def test_clear_model_memories_swallow_failures_and_no_repo(monkeypatch):
    es = _DummyESCore(exists_behavior=lambda index: True, delete_raises=True)

    async def _reset(_: Dict[str, Any]):
        raise RuntimeError("reset failed")

    monkeypatch.setattr(memory_service, "reset_all_memory", _reset)

    ok = await memory_service.clear_model_memories(
        es_core=es,
        model_repo=None,
        model_name="Model",
        embedding_dims=256,
        base_memory_config={"vector_store": {
            "config": {}}, "embedder": {"config": {}}},
    )
    # Even with reset and delete failures, function reports best-effort True
    assert ok is True
    assert es.deleted == ["mem0_model_256"]


@pytest.mark.asyncio
async def test_clear_model_memories_invalid_model_name():
    es = _DummyESCore(exists_behavior=lambda index: True)
    ok = await memory_service.clear_model_memories(
        es_core=es,
        model_repo="any",
        model_name="",
        embedding_dims=512,
        base_memory_config={"vector_store": {
            "config": {}}, "embedder": {"config": {}}},
    )
    assert ok is False
