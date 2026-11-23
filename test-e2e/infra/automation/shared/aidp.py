# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Build valid owned-KB requests from the active AIDP model catalog."""
from shared.asset_registry import AssetDependencyError
from shared.http import assert_status, client


async def create_payload(identity, name, *, description=None, **fields):
    """Resolve a catalog name, never a fixed model ID or a health-check gate."""
    async with client('config', token=identity.access_token) as api:
        response = await api.get('/aidp-mgmt/models', params={'service': 'embedding', 'app': 'KnowledgeBase'})
    assert_status(response, 200)
    names = sorted({row['model_name'] for row in response.json().get('models', [])
                    if isinstance(row, dict) and isinstance(row.get('model_name'), str) and row['model_name'].strip()})
    if not names:
        raise AssetDependencyError('models', 'aidp_embedding', detail='Active AIDP catalog has no embedding model')
    return {'name': name, 'description': name[:255] if description is None else description,
            'embedding_model': names[0], **fields}
