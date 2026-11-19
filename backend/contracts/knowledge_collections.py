# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bounded current collection setup ownership, without replayable input data."""

from typing import Literal

from contracts.agentos_knowledge import (
    Contract,
    KnowledgeSearchAuthorization,
    ModelVersion,
)
from pydantic import Field, model_validator


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


class KnowledgeCollectionsAuthorization(KnowledgeSearchAuthorization):
    view: Literal['resources', 'inventory'] = 'resources'


class KnowledgeCollectionsGrant(Contract):
    knowledge_bases: list[KnowledgeCollectionGrant] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def distinct_resources(self):
        if (len({r.knowledge_id for r in self.knowledge_bases}) != len(self.knowledge_bases)
            or len({(r.resource_tenant_id, r.collection) for r in self.knowledge_bases}) != len(self.knowledge_bases)):
            raise ValueError('Expected distinct knowledge metadata resources')
        return self


class KnowledgeCollectionsDescribe(KnowledgeCollectionsAuthorization):
    expected_revisions: dict[int, str] = Field(min_length=1, max_length=100)
    include_statistics: bool = False

    @model_validator(mode='after')
    def pinned_resources(self):
        if set(self.expected_revisions) != set(self.knowledge_ids) or any(
            len(value) != 64 or any(c not in '0123456789abcdef' for c in value)
            for value in self.expected_revisions.values()
        ):
            raise ValueError('Expected a SHA256 revision for every metadata resource')
        return self


class KnowledgeCollectionMetrics(Contract):
    record_count: int = Field(ge=0)
    size_bytes: int = Field(ge=0)
    created_at_ms: int = Field(ge=0)
    query_count: int = Field(ge=0)
    cache_hit_count: int = Field(ge=0)
    source_count: int = Field(ge=0)
    process_source: str = Field(max_length=32766)
    embedding_model_name: str = Field(max_length=32766)


class KnowledgeCollectionDescription(KnowledgeCollectionLookup):
    present: bool
    dimensions: int | None = Field(default=None, gt=0, le=2**31 - 1)
    metric: Literal['cosine'] | None = None
    statistics: KnowledgeCollectionMetrics | None = None

    @model_validator(mode='after')
    def confirmed_presence(self):
        if self.present and self.metric != 'cosine' or not self.present and any(
            value is not None for value in (self.dimensions, self.metric, self.statistics)
        ):
            raise ValueError('Collection metadata must match confirmed presence')
        return self


class KnowledgeCollectionsDescribed(Contract):
    items: list[KnowledgeCollectionDescription] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def distinct_knowledge(self):
        if len({item.knowledge_id for item in self.items}) != len(self.items):
            raise ValueError('Expected distinct knowledge metadata')
        return self
