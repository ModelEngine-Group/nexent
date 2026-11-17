# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management-owned immutable ingestion intent; no credentials or provider setup."""

from typing import Literal

from contracts.agentos_knowledge import (
    KnowledgeFileReference,
    KnowledgeFileUpload,
    ModelVersion,
    ObjectReference,
)
from contracts.knowledge_cleanse import KnowledgeCleanseRequest
from pydantic import Field, model_validator

INGESTION_DATASET = "knowledge_ingestion_files"
LOCAL_SOURCE_DATASET = "management_local_sources"


class KnowledgeIngestionIntent(KnowledgeFileReference):
    schema_version: Literal[1] = 1
    knowledge_id: int = Field(gt=0, le=2**31 - 1)
    file_version: int = Field(ge=0, le=2**31 - 1)
    user_id: str = Field(min_length=1, max_length=100)
    attempt: int = Field(ge=1, le=2**31 - 1)
    source: ObjectReference
    filename: str = Field(min_length=1, max_length=1024)
    parser_version: str = Field(min_length=1, max_length=128)
    embedding_model: ModelVersion
    chunking_strategy: Literal["basic", "by_title", "none"] = "basic"

    @model_validator(mode="after")
    def bounded_snapshot(self):
        if self.source.space != "files":
            raise ValueError("Expected a pinned knowledge file source")
        if len(self.model_dump_json().encode("utf-8")) > 16384:
            raise ValueError("Knowledge ingestion intent exceeds 16 KiB")
        return self

    @property
    def idempotency_key(self):
        return f"kb-ingest:{self.file_id}:{self.file_version}:{self.attempt}"

    def _reference(self):
        return self.model_dump(include={"knowledge_id", "file_id", "file_version"})

    def cleanse_request(self):
        return KnowledgeCleanseRequest(
            **self._reference(),
            source=self.source,
            filename=self.filename,
            idempotency_key=self.idempotency_key,
        )

    def runtime_request(self, artifact):
        return KnowledgeFileUpload(
            **self._reference(),
            artifact=artifact,
            parser_version=self.parser_version,
            idempotency_key=self.idempotency_key,
            embedding_model=self.embedding_model,
            chunking_strategy=self.chunking_strategy,
        )
