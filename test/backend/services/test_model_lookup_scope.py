# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Production model lookups preserve actual identity and share the catalog deadline."""

import asyncio
from unittest.mock import Mock

import pytest
from contracts.agentos_knowledge import ModelVersion
from runtime.model import service as module

from infrastructure.agentos_identity import ServicePrincipal


async def test_lookup_forwards_principal_and_operation_context(mocker):
    actor = ServicePrincipal('operator','tenant')
    def load(model_id, actual, *, context):
        assert model_id==1 and actual==actor
        assert context.remaining() <= module.MODEL_CATALOG_SECONDS
        return {'tenant_id':'tenant','delete_flag':'N','model_type':'embedding','max_tokens':2,'update_time':'2026-11-18T01:02:03'}
    async def direct(name, method, *args, **kwargs):
        return method(*args, context=kwargs['context'])
    mocker.patch.object(module,'run_blocking',side_effect=direct)
    service = module.ModelService(load,Mock())
    assert (await service.get(1,actor)).embedding_dimensions==2
    assert await service.embedding_dimensions(ModelVersion(model_id=1,revision='2026-11-18 01:02:03'),actor)==2


async def test_stalled_lookup_is_bounded_without_retry(mocker,caplog):
    closed=[]
    async def blocked(*args,**kwargs):
        try: await asyncio.Event().wait()
        finally: closed.append(True)
    mocker.patch.object(module,'MODEL_CATALOG_SECONDS',0.02)
    worker=mocker.patch.object(module,'run_blocking',side_effect=blocked)
    with pytest.raises(module.ModelAccessError) as error:
        await asyncio.wait_for(module.ModelService(Mock(),Mock()).get(1,ServicePrincipal('private-operator','private-tenant')),0.1)
    assert (error.value.status,error.value.code)==(504,'MODEL_TIMEOUT')
    assert worker.await_count==1 and closed==[True]
    assert 'agentos_model_lookup_timeout' in caplog.text and 'model_id=1' in caplog.text and 'phase=records' in caplog.text
    assert 'private-operator' not in caplog.text and 'private-tenant' not in caplog.text
