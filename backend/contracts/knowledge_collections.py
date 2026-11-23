# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bounded current collection setup ownership, without replayable input data."""

from typing import Literal

from contracts.agentos_knowledge import (
    Contract,
    KnowledgeSearchAuthorization,
    ModelVersion,
)
from pydantic import Field, model_serializer, model_validator


class CollectionSetup(Contract):
    operation_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$')
    actor_id: str = Field(min_length=1, max_length=100)
    resource_revision: str = Field(pattern=r'^[0-9a-f]{64}$')
    dimensions: int | None = Field(default=None, gt=0, le=2**31 - 1)
    operation: Literal['ensure', 'delete_source'] = 'ensure'
    native_documents: bool = False
    model_binding: ModelVersion | None = None
    phase: Literal['reserved', 'writing', 'unknown']
    writer_ended: bool

    @model_validator(mode='after')
    def consistent_operation(self):
        if self.operation == 'ensure' and self.dimensions is None or (
            self.operation == 'delete_source' and (self.dimensions is not None or self.model_binding is not None or self.native_documents)
        ):
            raise ValueError('Unexpected setup fields')
        return self

    @model_serializer(mode='wrap')
    def serialize_setup(self, handler):
        payload = handler(self)
        if self.operation == 'ensure':
            payload.pop('operation', None)
        if not self.native_documents:
            payload.pop('native_documents', None)
        return payload


class KnowledgeCollectionAuthorization(Contract):
    knowledge_id: int = Field(gt=0, le=2**31 - 1)
    untracked_source: str | None = Field(default=None, min_length=1, max_length=2048)

    @model_serializer(mode='wrap')
    def serialize_source_scope(self, handler):
        payload = handler(self)
        if self.untracked_source is None:
            payload.pop('untracked_source', None)
        return payload


class KnowledgeCollectionGrant(KnowledgeCollectionAuthorization):
    collection: str = Field(min_length=1, max_length=100)
    resource_tenant_id: str = Field(min_length=1, max_length=100)
    revision: str = Field(pattern=r'^[0-9a-f]{64}$')
    embedding_model_id: int | None = Field(default=None, gt=0)


class KnowledgeCollectionLookup(KnowledgeCollectionAuthorization):
    expected_revision: str = Field(pattern=r'^[0-9a-f]{64}$')


class KnowledgeCollectionEnsure(KnowledgeCollectionLookup):
    native_documents: bool = False
    dimensions: int = Field(gt=0, le=2**31 - 1)
    model_binding: ModelVersion | None = None


    @model_serializer(mode='wrap')
    def serialize_layout(self, handler):
        payload = handler(self)
        if self.untracked_source is None:
            payload.pop('untracked_source', None)
        if not self.native_documents:
            payload.pop('native_documents', None)
        return payload


class KnowledgeUntrackedSourceDelete(KnowledgeCollectionLookup):
    untracked_source: str = Field(min_length=1, max_length=2048)


class KnowledgeUntrackedSourceDeleted(KnowledgeCollectionLookup):
    deleted_count: int = Field(ge=0)


class KnowledgeCollectionEnsured(KnowledgeCollectionLookup):
    present: Literal[True]
    dimensions: int = Field(gt=0, le=2**31 - 1)
    metric: Literal['cosine']


class KnowledgeCollectionStatus(KnowledgeCollectionLookup):
    setup: CollectionSetup | None


class KnowledgeCollectionsAuthorization(KnowledgeSearchAuthorization):
    view: Literal['resources', 'inventory', 'usage'] = 'resources'
    native_documents: bool = False

    @model_serializer(mode="wrap")
    def serialize_layout(self, handler):
        result = handler(self)
        if not self.native_documents:
            result.pop("native_documents", None)
        if not self.selected_files:
            result.pop("selected_files", None)
        return result


class KnowledgeCollectionsGrant(Contract):
    knowledge_bases: list[KnowledgeCollectionGrant] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def distinct_resources(self):
        if (len({r.knowledge_id for r in self.knowledge_bases}) != len(self.knowledge_bases)
            or len({(r.resource_tenant_id, r.collection) for r in self.knowledge_bases}) != len(self.knowledge_bases)):
            raise ValueError('Expected distinct knowledge metadata resources')
        return self


class PinnedKnowledgeCollections(KnowledgeCollectionsAuthorization):
    expected_revisions: dict[int, str] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def pinned_resources(self):
        if set(self.expected_revisions) != set(self.knowledge_ids) or any(
            len(value) != 64 or any(c not in '0123456789abcdef' for c in value)
            for value in self.expected_revisions.values()
        ):
            raise ValueError('Expected a SHA256 revision for every metadata resource')
        return self


class KnowledgeCollectionsDescribe(PinnedKnowledgeCollections):
    view: Literal['resources', 'inventory'] = 'resources'
    include_statistics: bool = False
    include_vector_media: bool = False

    @model_serializer(mode="wrap")
    def serialize_describe(self, handler):
        result = handler(self)
        if not self.native_documents:
            result.pop("native_documents", None)
        if not self.selected_files:
            result.pop("selected_files", None)
        if not self.include_vector_media:
            result.pop("include_vector_media", None)
        return result


class KnowledgeCollectionsUsage(PinnedKnowledgeCollections):
    view: Literal['usage'] = 'usage'


class KnowledgeUsageMetrics(Contract):
    record_count: int = Field(ge=0)
    size_bytes: int = Field(ge=0)
    source_count: int = Field(ge=0)


class KnowledgeCollectionUsage(KnowledgeCollectionLookup):
    present: bool
    statistics: KnowledgeUsageMetrics | None = None
    statistics_error: Literal['unavailable', 'conflict', 'not_found', 'unsupported', 'invalid_input'] | None = None

    @model_validator(mode='after')
    def consistent_statistics(self):
        if (not self.present and (self.statistics is not None or self.statistics_error is not None)
            or self.present and (self.statistics is None) == (self.statistics_error is None)):
            raise ValueError('Usage requires either statistics or an explicit error for an existing collection')
        return self


class KnowledgeCollectionsUsageResult(Contract):
    items: list[KnowledgeCollectionUsage] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def distinct_knowledge(self):
        if len({item.knowledge_id for item in self.items}) != len(self.items):
            raise ValueError('Expected distinct collection usage')
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


class KnowledgeModelDisplay(Contract):
    display_name: str | None = ''
    is_multimodal: bool = False


class KnowledgeVectorMedia(Contract):
    text: int = Field(ge=0)
    image: int = Field(ge=0)
    unclassified: int = Field(ge=0)


class KnowledgeCollectionDescription(KnowledgeCollectionLookup):
    present: bool
    dimensions: int | None = Field(default=None, gt=0, le=2**31 - 1)
    metric: Literal['cosine'] | None = None
    statistics: KnowledgeCollectionMetrics | None = None
    statistics_error: Literal['unavailable', 'conflict', 'not_found', 'unsupported', 'invalid_input'] | None = None
    model_display: KnowledgeModelDisplay | None = None
    vector_media: KnowledgeVectorMedia | None = None

    @model_serializer(mode="wrap")
    def serialize_description(self, handler):
        result = handler(self)
        if self.vector_media is None:
            result.pop("vector_media", None)
        return result

    @model_validator(mode='after')
    def confirmed_presence(self):
        if self.present and self.metric != 'cosine' or not self.present and any(
            value is not None for value in (self.dimensions, self.metric, self.statistics, self.statistics_error,
                                             self.model_display, self.vector_media)
        ):
            raise ValueError('Collection metadata must match confirmed presence')
        if self.statistics is not None and self.statistics_error is not None:
            raise ValueError('Statistics and their failure are mutually exclusive')
        return self


class KnowledgeCollectionsDescribed(Contract):
    items: list[KnowledgeCollectionDescription] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def distinct_knowledge(self):
        if len({item.knowledge_id for item in self.items}) != len(self.items):
            raise ValueError('Expected distinct knowledge metadata')
        return self
