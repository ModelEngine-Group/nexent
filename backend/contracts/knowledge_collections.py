# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bounded current collection setup ownership, without replayable input data."""

from typing import Literal

from contracts.agentos_knowledge import Contract, ModelVersion
from pydantic import Field


class CollectionSetup(Contract):
    operation_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$')
    actor_id: str = Field(min_length=1, max_length=100)
    resource_revision: str = Field(pattern=r'^[0-9a-f]{64}$')
    dimensions: int = Field(gt=0, le=2**31 - 1)
    model_binding: ModelVersion | None = None
    phase: Literal['reserved', 'writing', 'unknown']
    writer_ended: bool


class KnowledgeCollectionAuthorization(Contract):
    knowledge_id: int = Field(gt=0, le=2**31 - 1)


class KnowledgeCollectionGrant(KnowledgeCollectionAuthorization):
    collection: str = Field(min_length=1, max_length=100)
    resource_tenant_id: str = Field(min_length=1, max_length=100)
    revision: str = Field(pattern=r'^[0-9a-f]{64}$')
    embedding_model_id: int | None = Field(default=None, gt=0)


class KnowledgeCollectionLookup(KnowledgeCollectionAuthorization):
    expected_revision: str = Field(pattern=r'^[0-9a-f]{64}$')


class KnowledgeCollectionEnsure(KnowledgeCollectionLookup):
    dimensions: int = Field(gt=0, le=2**31 - 1)
    model_binding: ModelVersion | None = None


class KnowledgeCollectionEnsured(KnowledgeCollectionLookup):
    present: Literal[True]
    dimensions: int = Field(gt=0, le=2**31 - 1)
    metric: Literal['cosine']


class KnowledgeCollectionStatus(KnowledgeCollectionLookup):
    setup: CollectionSetup | None
