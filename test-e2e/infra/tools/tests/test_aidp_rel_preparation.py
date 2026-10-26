# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Offline preparation regressions; live Journey acceptance is separate."""
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
import sys

import httpx
import pytest

INFRA = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(INFRA / "automation"))
sys.path.insert(0, str(INFRA / "mock-services/ext-knowledge-mock"))
import prepare_special_assets as special
import prepare_d4_shared_assets as d4
import aidp_fixture
from fastapi import FastAPI


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["available", "not_detected", "missing"])
async def test_fault_model_admission_and_cleanup_before_failed_lookup(monkeypatch, status):
    actions = []
    def response(body):
        return httpx.Response(200, json=body, request=httpx.Request("GET", "http://fixture"))
    @asynccontextmanager
    async def api(*args, **kwargs):
        async def post(path, json):
            actions.append(("create", json))
            return response({})
        async def get(path):
            assert actions[-1][0] == "register", "Cleanup must precede catalog lookup"
            payload = actions[0][1]
            assert payload["skip_default_backfill"] is True
            assert payload["connect_status"] == "available"
            return response({"data": [] if status == "missing" else [{"display_name": payload["display_name"],
                "model_id": 43, "connect_status": status}]})
        yield SimpleNamespace(post=post, get=get)
    monkeypatch.setattr(special, "client", api)
    monkeypatch.setattr(special, "resolve_asset", lambda *a, **kw: None)
    monkeypatch.setattr(special, "fault_model_base_url", lambda: "http://controlled/v1")
    monkeypatch.setattr(special, "model_request", lambda *a, **kw: {"display_name": kw["display_name"]})
    monkeypatch.setattr(special, "register_asset", lambda *a, **kw: actions.append(("register", (a, kw))))
    if status == "available":
        await special.prepare_fault_model(SimpleNamespace(id="admin", access_token="test"))
        assert actions[-1][1][0][:2] == ("reliability", "fault_model_id")
    else:
        with pytest.raises(AssertionError):
            await special.prepare_fault_model(SimpleNamespace(id="admin", access_token="test"))
        assert len(actions) == 2
    cleanup = actions[1][1][1]["cleanup"]
    assert cleanup["identity"] == "admin"
    assert cleanup["path"] == "/model/delete"


@pytest.mark.asyncio
async def test_aidp_oracle_cannot_mutate_shared_seed_or_unowned_kb():
    owned = "aidp-kb-a1b2c3d4"
    name = "d4-aidp-0123456789abcdef"
    source = [{"id": 1, "text": "oracle", "metadata": {"knowledge_base_id": "aidp-kb-product"}}]
    module = SimpleNamespace(app=FastAPI(), _KNOWLEDGE_BASES={owned: {"kds_name": name}},
        _CHUNKS_BY_KB={"aidp-kb-product": source}, _save_state=lambda: None)
    aidp_fixture.install(module)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=module.app), base_url="http://mock") as api:
        for target, supplied in [("aidp-kb-product", name), (owned, "another-owner")]:
            assert (await api.post("/_mock/owned-aidp-oracle", json={"kb_id": target, "name": supplied})).status_code == 409
        assert (await api.post("/_mock/owned-aidp-oracle", json={"kb_id": owned, "name": name})).status_code == 200
    assert module._CHUNKS_BY_KB[owned][0]["metadata"]["knowledge_base_id"] == owned
    assert source[0]["metadata"]["knowledge_base_id"] == "aidp-kb-product"


@pytest.mark.asyncio
@pytest.mark.parametrize("visible", [True, False])
async def test_aidp_product_creation_registers_cleanup_before_seeding(monkeypatch, visible):
    actions = []
    kb_id = "aidp-kb-a1b2c3d4"
    def response(body):
        return httpx.Response(200, json=body, request=httpx.Request("GET", "http://fixture"))
    @asynccontextmanager
    async def api(*args, **kwargs):
        async def get(path, **kwargs):
            if path.endswith("models"):
                assert kwargs["params"] == {"service": "embedding"}
                return response({"models": [{"model_type": "embedding", "model_name": "fixture-embedding"}]})
            if path.endswith(kb_id):
                return response({"kds_id": kb_id})
            return response({"value": [{"kds_id": kb_id}] if visible else []})
        async def post(path, json):
            assert json["ingroup_permission"] == "PRIVATE"
            actions.append("product_create")
            return response({"kds_id": kb_id})
        yield SimpleNamespace(get=get, post=post)
    class Control:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, path, json):
            assert actions == ["product_create", "cleanup_registered"]
            return response({"chunk_count": 2})
    def register(section, key, value, **kwargs):
        if key == "d4_aidp_id":
            assert kwargs["cleanup"]["path"] == "/aidp-mgmt/knowledge-bases/" + kb_id
            actions.append("cleanup_registered")
    from shared import ext_knowledge, case_evidence
    monkeypatch.setattr(d4, "client", api)
    monkeypatch.setattr(httpx, "AsyncClient", Control)
    monkeypatch.setattr(ext_knowledge, "runner_url", lambda path: "http://mock" + path)
    monkeypatch.setattr(case_evidence, "write_case_evidence", lambda *args: actions.append("proof"))
    monkeypatch.setattr(d4, "register_asset", register)
    if visible:
        assert await d4.prepare_aidp_knowledge(SimpleNamespace(id="admin", access_token="test")) == {}
        assert actions[-1] == "proof"
    else:
        with pytest.raises(AssertionError, match="not visible"):
            await d4.prepare_aidp_knowledge(SimpleNamespace(id="admin", access_token="test"))
        assert actions == ["product_create", "cleanup_registered"]
