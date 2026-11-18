# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime model catalogs expose only tenant metadata, through a bounded port."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from contracts.agentos import ModelListQuery
from runtime.model.service import ModelService

from infrastructure.agentos_identity import ServicePrincipal


@pytest.mark.asyncio
async def test_catalog_timeout_cancels_wait_without_retry_or_secret_logging(mocker, caplog):
    import asyncio

    from runtime.model import service as module

    closed = []

    async def blocked(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            closed.append(True)

    mocker.patch.object(module, "MODEL_CATALOG_SECONDS", 0.02)
    worker = mocker.patch.object(module, "run_blocking", side_effect=blocked)
    loader = Mock()
    service = ModelService(Mock(), Mock(), list_records=loader)
    with pytest.raises(module.ModelAccessError) as error:
        await service.list(ModelListQuery(), ServicePrincipal("private-user", "private-tenant"))
    assert (error.value.status, error.value.code) == (504, "MODEL_TIMEOUT")
    assert worker.await_count == 1 and closed == [True]
    loader.assert_not_called()
    records = [record for record in caplog.records if record.name == module.__name__]
    assert len(records) == 1 and records[0].levelname == "WARNING"
    assert "phase=records" in records[0].message and "threshold_seconds=0.02" in records[0].message
    assert "private-" not in records[0].message


@pytest.mark.asyncio
async def test_catalog_projects_metadata_without_credentials_or_endpoint(mocker):
    async def blocking(name, method, *args, **kwargs):
        return method(*args, context=kwargs["context"])

    mocker.patch("runtime.model.service.run_blocking", side_effect=blocking)
    actor = ServicePrincipal("user", "tenant")
    rows = SimpleNamespace(items=[{"model_id": 7, "tenant_id": "tenant", "delete_flag": "N", "model_type": "rerank",
                                   "display_name": "Rerank", "model_repo": "repo", "model_name": "ranker", "update_time": "v1",
                                   "api_key": "private-key", "base_url": "https://private.example"}], next_cursor=None)
    loader = Mock(return_value=rows)
    adapters = Mock()
    service = ModelService(Mock(), adapters, list_records=loader)
    query = ModelListQuery(model_type="rerank", page_size=20)
    result = await service.list(query, actor)
    assert result.models[0].model_id == 7 and result.models[0].qualified_name == "repo/ranker"
    assert "private-key" not in result.model_dump_json() and "private.example" not in result.model_dump_json()
    assert loader.call_count == 1 and loader.call_args.args == (query, actor)
    assert loader.call_args.kwargs["context"].remaining() > 0
    adapters.assert_not_called()


@pytest.mark.asyncio
async def test_catalog_does_not_return_foreign_or_deleted_rows(mocker):
    from runtime.model.service import ModelAccessError

    async def blocking(name, method, *args, **kwargs):
        return method(*args, context=kwargs["context"])

    mocker.patch("runtime.model.service.run_blocking", side_effect=blocking)
    for row in ({"tenant_id": "foreign", "delete_flag": "N"}, {"tenant_id": "tenant", "delete_flag": "Y"}):
        service = ModelService(Mock(), Mock(), list_records=Mock(return_value=SimpleNamespace(items=[row], next_cursor=None)))
        with pytest.raises(ModelAccessError):
            await service.list(ModelListQuery(), ServicePrincipal("user", "tenant"))


@pytest.mark.parametrize('model_type,configured,expected', [('embedding', 1536, 1536), ('multi_embedding', 512, 512),
    ('llm', 4096, None), ('embedding', None, None), ('embedding', True, None), ('embedding', '2', None)])
async def test_catalog_and_get_report_the_same_dimension_without_creating_an_adapter(mocker, model_type, configured, expected):
    async def blocking(name, method, *args, **kwargs):
        kwargs.pop('lane', None); kwargs.pop('owner', None)
        return method(*args, **kwargs)
    mocker.patch('runtime.model.service.run_blocking', side_effect=blocking)
    row = {'model_id': 7, 'tenant_id': 'tenant', 'delete_flag': 'N', 'model_type': model_type, 'max_tokens': configured}
    records = Mock(return_value=SimpleNamespace(items=[row], next_cursor=None))
    adapters = Mock()
    service = ModelService(Mock(return_value=row), adapters, list_records=records)
    actor = ServicePrincipal('user', 'tenant')
    catalog = await service.list(ModelListQuery(), actor)
    metadata = await service.get(7, actor)
    assert catalog.models[0].embedding_dimensions == metadata.embedding_dimensions == expected
    assert 'max_tokens' not in catalog.model_dump_json()
    adapters.assert_not_called()


@pytest.mark.asyncio
async def test_signed_catalog_http_round_trip_and_invalid_page(mocker):
    from unittest.mock import AsyncMock

    import httpx
    from contracts.agentos import ModelCatalogEntry, ModelCatalogPage
    from contracts.constants import environment
    from contracts.errors.exceptions import RuntimeUpstreamError
    from fastapi import FastAPI
    from runtime.agentos.middleware import AgentOSMiddleware
    from runtime.agentos.model import create_model_router

    from infrastructure.agentos_client import AgentOSClient

    mocker.patch.object(environment, "JWT_SECRET", "synthetic-model-catalog")
    service = SimpleNamespace(list=AsyncMock(return_value=ModelCatalogPage(models=[ModelCatalogEntry(
        model_id=7, model_type="rerank", display_name="Rerank", qualified_name="repo/model", revision="v1")], next_cursor="next")))
    app = FastAPI(root_path="/api")
    app.add_middleware(AgentOSMiddleware)
    app.include_router(create_model_router(service))
    client = AgentOSClient("http://runtime", lambda **kwargs: httpx.AsyncClient(transport=httpx.ASGITransport(app), **kwargs))
    result = await client.list_models(ModelListQuery(model_type="rerank"), "user", "tenant")
    assert result.next_cursor == "next" and result.models[0].qualified_name == "repo/model"
    assert service.list.await_args.args[1] == ServicePrincipal("user", "tenant")
    from nexent.storage.errors import ScopeDenied
    service.list.side_effect = ScopeDenied()
    with pytest.raises(RuntimeUpstreamError) as error:
        await client.list_models(ModelListQuery(cursor="wrong-scope"), "user", "tenant")
    assert error.value.status_code == 403
