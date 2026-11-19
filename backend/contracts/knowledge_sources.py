# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Body-free physical source summaries for Management file projections."""

from contracts.agentos_knowledge import Contract, KnowledgeChunksAuthorization
from pydantic import Field, JsonValue, model_validator


class KnowledgeSources(KnowledgeChunksAuthorization):
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    limit: int = Field(default=1000, ge=1, le=1000)


class KnowledgeSourceSummary(Contract):
    source_key: str = Field(max_length=32766)
    path_or_url: JsonValue
    filename: JsonValue
    file_size: JsonValue
    create_time: JsonValue
    chunk_count: int = Field(gt=0)


class KnowledgeSourcesResult(Contract):
    knowledge_id: int = Field(gt=0)
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    present: bool
    sources: list[KnowledgeSourceSummary] = Field(max_length=1000)

    @model_validator(mode="after")
    def valid_sources(self):
        if (
            not self.present
            and self.sources
            or len({v.source_key for v in self.sources}) != len(self.sources)
        ):
            raise ValueError("Expected unique sources in an existing collection")
        return self
