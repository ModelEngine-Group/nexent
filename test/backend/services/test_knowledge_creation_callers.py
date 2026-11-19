# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-KB-CREATE-04 preserves Northbound and seed metadata boundaries."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from contracts.agentos import ModelMetadata
from management.services import northbound
from management.services.knowledge_base import creation, seed_documents
from nexent.storage.errors import InvalidInput

from infrastructure.agentos_identity import ServicePrincipal


async def test_northbound_creation_passes_actual_actor_without_vdb_or_credentials(mocker):
    response = {'status': 'success', 'id': '7-new'}
    create = mocker.patch.object(creation, 'create_knowledge_base', new=AsyncMock(return_value=response))
    ctx = SimpleNamespace(user_id='operator', tenant_id='asset_owner_tenant_id', authorization='not-forwarded')
    assert await northbound.create_knowledge_base_for_northbound(ctx=ctx, knowledge_name='KB', embedding_model_id=2,
        embedding_dim=3, group_ids=[8], ingroup_permission='EDIT', preserve_source_file=False) is response
    create.assert_awaited_once_with('KB', ServicePrincipal(ctx.user_id, ctx.tenant_id), embedding_model_id=2,
        embedding_dim=3, group_ids=[8], ingroup_permission='EDIT', preserve_source_file=False)


async def test_seed_source_name_is_metadata_only_and_preserves_repo(mocker):
    actor = ServicePrincipal('operator', 'tenant-a')
    client = mocker.patch.object(seed_documents, 'AgentOSClient').return_value
    client.get_model = AsyncMock(return_value=ModelMetadata(model_id=2, model_type='embedding', display_name='display',
        model_name='embed', qualified_name='repo/embed', revision='v1'))
    assert await seed_documents.get_seed_model_name(2, actor) == 'repo/embed'
    client.get_model.assert_awaited_once_with(2, actor.user_id, actor.tenant_id)


@pytest.mark.parametrize('change', [{'model_id': 9}, {'model_type': 'llm'}, {'qualified_name': None}])
async def test_seed_metadata_error_is_not_replaced_with_display_name(mocker, change):
    data = {'model_id': 2, 'model_type': 'embedding', 'display_name': 'display', 'qualified_name': 'repo/embed',
            'revision': 'v1', **change}
    client = mocker.patch.object(seed_documents, 'AgentOSClient').return_value
    client.get_model = AsyncMock(return_value=ModelMetadata(**data))
    with pytest.raises(InvalidInput):
        await seed_documents.get_seed_model_name(2, ServicePrincipal('operator', 'tenant-a'))
    assert client.get_model.await_count == 1
