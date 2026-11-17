# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Standard KB resource cleanup carries no physical collection or actor authority."""

import json
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from contracts.agentos_knowledge import Contract
from pydantic import Field, model_validator

BASE_DELETION_DATASET = 'runtime_knowledge_base_deletions'
RUNTIME_JOBS = 'runtime_knowledge_jobs'
RUNTIME_FILES = 'runtime_knowledge_files'


class KnowledgeBaseDelete(Contract):
    knowledge_id: int = Field(gt=0, le=2**31 - 1)
    idempotency_key: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$')


class KnowledgeBaseDeleteLookup(Contract):
    knowledge_id: int = Field(gt=0, le=2**31 - 1)
    job_id: str = Field(pattern=r'^[0-9a-f]{32}$')


class KnowledgeBaseDeleteState(KnowledgeBaseDeleteLookup):
    status: Literal['cleanup_pending', 'deleted']
    physical_cleanup_complete: bool = False

    @model_validator(mode='after')
    def confirmed_terminal(self):
        if self.physical_cleanup_complete != (self.status == 'deleted'):
            raise ValueError('Deleted state requires confirmed physical absence')
        return self


class KnowledgeBaseDeleteAuthorization(Contract):
    knowledge_id: int = Field(gt=0, le=2**31 - 1)


class KnowledgeBaseDeleteGrant(KnowledgeBaseDeleteAuthorization):
    collection: str = Field(min_length=1, max_length=100)


def knowledge_base_deletion_id(request, tenant_id, user_id):
    if not isinstance(request, KnowledgeBaseDelete):
        raise TypeError('Expected a standard KB deletion request')
    if any(not isinstance(value, str) or not value for value in (tenant_id, user_id)):
        raise ValueError('Expected trusted tenant and actor identities')
    return uuid5(NAMESPACE_URL, json.dumps([
        'runtime-kb-base-delete', tenant_id, user_id, request.knowledge_id, request.idempotency_key,
    ], separators=(',', ':'))).hex
