# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Resolving business-test assets must not require model-management rights."""

from contextlib import asynccontextmanager
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "automation"))

from d3 import assets
import prepare_d4_shared_assets as d4_preparation
from shared import model_catalog, model_health
from shared.factories import model as model_factory


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["USER", "DEV", "ADMIN"])
@pytest.mark.parametrize("kind", ["llm", "embedding"])
async def test_business_resolution_does_not_probe_or_elevate(monkeypatch, role, kind):
    identity = SimpleNamespace(role=role, access_token="fixture-business-session")
    config = {"id": "logical-model", "model": "fixture-model"}
    row = {"model_id": 7, "model_name": "fixture-model", "model_type": kind}
    paths = []

    class API:
        async def get(self, path):
            paths.append(path)
            body = {"data": [row]} if path == "/model/list" else {}
            return httpx.Response(200, json=body, request=httpx.Request("GET", "http://fixture" + path))

        async def post(self, *args, **kwargs):
            pytest.fail("Business model resolution invoked a mutating/probe endpoint")

    @asynccontextmanager
    async def client(service, *, token):
        assert service == "config" and token == identity.access_token
        yield API()

    probe = AsyncMock(side_effect=AssertionError("Health requires model:update"))
    elevate = AsyncMock(side_effect=AssertionError("Unnecessary administrator login"))
    monkeypatch.setattr(assets, "configured_model", lambda _: config)
    monkeypatch.setattr(model_catalog, "client", client)
    monkeypatch.setattr(model_catalog, "catalog_reader", elevate)
    monkeypatch.setattr(model_health, "ensure_model_health", probe)

    assert await assets.model_id(kind, identity) == 7
    assert paths == ["/model/list", "/config/load_config"]
    probe.assert_not_awaited()
    elevate.assert_not_awaited()
    assert identity.access_token == "fixture-business-session"


@pytest.mark.asyncio
async def test_explicit_health_diagnostic_remains_opt_in(monkeypatch):
    identity = SimpleNamespace(role="ADMIN")
    config = {"id": "logical-model", "model": "fixture-model"}
    row = {"model_id": 7, "model_name": "fixture-model", "model_type": "llm"}
    monkeypatch.setattr(assets, "configured_model", lambda _: config)
    monkeypatch.setattr(model_catalog, "load_model_catalog", AsyncMock(return_value=([row], {}, identity)))
    probe = AsyncMock()
    monkeypatch.setattr(model_health, "ensure_model_health", probe)

    assert await assets.model_id("llm", identity, force_health=True) == 7
    probe.assert_awaited_once_with(identity, config, row, force=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "business", "activation"])
async def test_new_owned_model_is_activated_once_and_always_cleaned(monkeypatch, failure):
    posts = []
    identity = SimpleNamespace(id="fixture-admin", access_token="fixture-session")

    class API:
        async def post(self, path, **kwargs):
            posts.append((path, kwargs))
            assert path in {"/model/create", "/model/delete"}
            return httpx.Response(200, json={}, request=httpx.Request("POST", "http://fixture" + path))

        async def get(self, path):
            assert path == "/model/list"
            row = {"model_id": 19, "model_type": "llm", "display_name": posts[0][1]["json"]["display_name"]}
            return httpx.Response(200, json={"data": [row]}, request=httpx.Request("GET", "http://fixture" + path))

    @asynccontextmanager
    async def client(*args, **kwargs):
        assert kwargs["token"] == identity.access_token
        yield API()

    monkeypatch.setattr(model_factory, "client", client)
    monkeypatch.setattr(model_factory, "model_request", lambda kind, display_name: {
        "model_type": kind, "model_name": "fixture-model", "display_name": display_name})
    monkeypatch.setattr(model_factory, "configured_model", lambda _: {"id": "logical-model"}, raising=False)
    monkeypatch.setattr(model_factory, "register_asset", Mock())
    state = Mock()
    monkeypatch.setattr(model_factory, "mark_asset_state", state)
    probe = AsyncMock(side_effect=RuntimeError("New model activation failed") if failure == "activation" else None)
    monkeypatch.setattr(model_health, "ensure_model_health", probe)
    # Catch the old imported alias as well as future dynamic imports.
    monkeypatch.setattr(model_factory, "ensure_model_health", probe, raising=False)

    async def run_business():
        async with model_factory.owned_configured_model(identity, "FIXTURE") as model_id:
            assert model_id == 19
            if failure == "business":
                raise RuntimeError("Business assertion failed")

    if failure:
        with pytest.raises(RuntimeError, match="Business assertion failed" if failure == "business" else "New model activation failed"):
            await run_business()
    else:
        await run_business()
    probe.assert_awaited_once()
    assert probe.await_args.args[0] is identity and probe.await_args.kwargs == {"force": True}
    assert [path for path, _ in posts] == ["/model/create", "/model/delete"]
    assert posts[0][1]["json"]["skip_default_backfill"] is True
    assert posts[-1][1]["params"]["display_name"] == posts[0][1]["json"]["display_name"]
    assert state.call_args.args[-1] == "DELETED"


@pytest.mark.asyncio
@pytest.mark.parametrize("exists", [False, True])
async def test_d4_embedding_only_activates_a_new_record(monkeypatch, exists):
    identity = SimpleNamespace(access_token="fixture-session")
    payload = {"model_name": "fixture-embedding", "model_type": "embedding", "display_name": "logical"}
    calls = []

    class API:
        async def get(self, path):
            assert path == "/model/list"
            rows = [{"model_name": "fixture-embedding", "model_type": "embedding"}] if exists else []
            return httpx.Response(200, json={"data": rows}, request=httpx.Request("GET", "http://fixture" + path))

        async def post(self, path, **kwargs):
            assert path in {"/model/create", "/model/healthcheck"}
            calls.append((path, kwargs.get("json") or kwargs.get("params")))
            return httpx.Response(200, json={"data": {"connectivity": True}},
                                  request=httpx.Request("POST", "http://fixture" + path))

    @asynccontextmanager
    async def client(service, *, token):
        assert service == "config" and token == identity.access_token
        yield API()

    resolver = AsyncMock(return_value=7)
    monkeypatch.setattr(d4_preparation, "client", client)
    monkeypatch.setattr(d4_preparation, "model_request", lambda _: dict(payload))
    monkeypatch.setattr(d4_preparation, "model_id", resolver)
    assert await d4_preparation._ensure_embedding_anchor(identity) == 7
    resolver.assert_awaited_once_with("embedding", identity)
    assert [path for path, _ in calls] == ([] if exists else ["/model/create", "/model/healthcheck"])
    if calls:
        assert calls[0][1]["display_name"] == "fixture-embedding"
