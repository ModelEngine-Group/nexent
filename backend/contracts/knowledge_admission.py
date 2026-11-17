# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management-owned KB admission and its preallocated upload identity."""

from typing import Literal

from contracts.agentos_knowledge import Contract
from pydantic import Field, model_validator

KNOWLEDGE_ADMISSION_DATASET = 'management_knowledge_admission'
UPLOAD_ADMISSION_DATASET = 'management_knowledge_uploads'
OWNER_CLEANUP_IDENTITIES = 'knowledge_owner_cleanup_identities'


class KnowledgeUploadFile(Contract):
    file_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    tenant_id: str = Field(min_length=1, max_length=100)
    knowledge_id: int = Field(gt=0, le=2**31 - 1)
    index_name: str = Field(min_length=1, max_length=100)
    original_filename: str = Field(min_length=1, max_length=1024)
    bucket_name: str | None = Field(default=None, min_length=1, max_length=255)
    object_name: str | None = Field(default=None, min_length=1, max_length=1024)
    file_size: int | None = Field(default=None, ge=0, le=2**63 - 1)
    upload_owner_service: str | None = Field(default=None, min_length=1, max_length=100)
    status: Literal['UPLOADING'] = 'UPLOADING'
    stage: Literal['UPLOAD'] = 'UPLOAD'
    created_by: str = Field(min_length=1, max_length=100)


class KnowledgeOwnerCleanup(Contract):
    purpose: Literal['user_deletion', 'tenant_deletion']
    owner_user_id: str = Field(min_length=1, max_length=100)
    actor_tenant_id: str = Field(min_length=1, max_length=100)


class KnowledgeTenantCleanup(Contract):
    actor_tenant_id: str = Field(min_length=1, max_length=100)


class KnowledgeBaseDeletionIntent(Contract):
    schema_version: Literal[1] = 1
    knowledge_id: int = Field(gt=0, le=2**31 - 1)
    index_name: str = Field(min_length=1, max_length=100)
    user_id: str = Field(min_length=1, max_length=100)
    phase: Literal['files', 'collection_submitting', 'metadata_pending', 'deleted'] = 'files'
    owner_cleanup: KnowledgeOwnerCleanup | None = None
    tenant_cleanup: KnowledgeTenantCleanup | None = None

    @model_validator(mode='after')
    def exclusive_cleanup_authority(self):
        if self.owner_cleanup is not None and self.tenant_cleanup is not None:
            raise ValueError('A KB deletion has exactly one deprovision authority')
        return self
