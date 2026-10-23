"""Journal exact DB rows and deletion fences for the delete-chain scenario."""
from __future__ import annotations

import re

from shared.asset_registry import register_asset


def register_knowledge(identity, row):
    index_name = str(row['index_name'])
    if not re.fullmatch(r'kb-delete-fence-[0-9]+-[a-f0-9]{8}', index_name):
        raise ValueError('unexpected delete-fence KB name')
    knowledge_id = int(row['knowledge_id'])
    register_asset('owned_knowledge_records', index_name, knowledge_id,
        owner_case_id='API-AUTO-2B3A078E3CD1B151',
        cleanup={'kind': 'delete_owned_knowledge_record', 'index_name': index_name,
                 'knowledge_id': knowledge_id, 'tenant_id': identity.tenant_id,
                 'user_id': identity.user_id})


def register_file(identity, index_name, knowledge_id, file_id):
    if not re.fullmatch(r'[a-f0-9]{32}', file_id):
        raise ValueError('unexpected delete-fence file ID')
    register_asset('owned_lifecycle_files', file_id, file_id,
        owner_case_id='API-AUTO-2B3A078E3CD1B151',
        cleanup={'kind': 'delete_owned_lifecycle_file', 'file_id': file_id,
                 'index_name': index_name, 'knowledge_id': int(knowledge_id),
                 'tenant_id': identity.tenant_id})


def register_fence(file_id):
    if not re.fullmatch(r'[a-f0-9]{32}', file_id):
        raise ValueError('unexpected delete-fence file ID')
    register_asset('owned_delete_fences', file_id, file_id,
        owner_case_id='API-AUTO-2B3A078E3CD1B151',
        cleanup={'kind': 'delete_owned_redis_fence', 'file_id': file_id})


def delete_knowledge(*, index_name, knowledge_id, tenant_id, user_id):
    from database.knowledge_db import delete_knowledge_record, get_knowledge_record
    row = get_knowledge_record({'index_name': index_name, 'tenant_id': tenant_id})
    if not row:
        return
    if int(row['knowledge_id']) != int(knowledge_id):
        raise RuntimeError('KB ownership mismatch; refusing cleanup')
    if not delete_knowledge_record({'index_name': index_name, 'user_id': user_id}):
        raise RuntimeError('owned KB cleanup did not delete a row')


def delete_file(*, file_id, index_name, knowledge_id, tenant_id):
    from database.knowledge_file_lifecycle_db import get_file_record, delete_file_record
    row = get_file_record(file_id=file_id, include_hidden=True)
    if not row:
        return
    if (row['index_name'] != index_name or row['tenant_id'] != tenant_id
            or int(row['knowledge_id']) != int(knowledge_id)):
        raise RuntimeError('lifecycle row ownership mismatch; refusing cleanup')
    delete_file_record(file_id)
