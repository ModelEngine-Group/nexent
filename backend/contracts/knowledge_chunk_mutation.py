# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Serializable in-memory mutation intent; durable storage retains only its digest."""

import hashlib
import json
from typing import Literal

from contracts.agentos_knowledge import (
    Contract,
    KnowledgeChunk,
    KnowledgeFileReference,
    ModelVersion,
)
from pydantic import Field, JsonValue, model_validator

CHANGES = "runtime_knowledge_chunk_changes"
STATES = "runtime_knowledge_chunk_states"
ACTIVE_STATUSES = ("reserved", "writing", "unknown")


class ChunkCreateData(Contract):
    content: str
    filename: str | None = None
    location: dict[str, JsonValue] = Field(default_factory=dict)
    embedding_model: ModelVersion | None = None
    embedding_input: str | None = None


class ChunkMutationAuthorization(Contract):
    knowledge_id: int = Field(gt=0)
    chunk_id: str = Field(min_length=1, max_length=1024)
    operation: Literal["create", "update", "delete"]


class ChunkMutationGrant(ChunkMutationAuthorization):
    collection: str = Field(min_length=1, max_length=100)
    resource_tenant_id: str = Field(min_length=1, max_length=100)
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    embedding_model_id: int | None = Field(default=None, gt=0)


class ChunkMutationLookup(ChunkMutationAuthorization):
    resource_revision: str = Field(pattern=r"^[0-9a-f]{64}$")


class ChunkMutationTarget(ChunkMutationLookup):
    change_epoch: int = Field(ge=0)
    chunk: KnowledgeChunk | None = None
    generation: str | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode="after")
    def exact_target(self):
        if (self.chunk is None) != (self.generation is None):
            raise ValueError("A stored chunk and its generation must be present together")
        if self.chunk is not None and (self.chunk.knowledge_id != self.knowledge_id or self.chunk.chunk_id != self.chunk_id):
            raise ValueError("Target must belong to the requested knowledge base and key")
        return self


class ChunkMutationState(ChunkMutationAuthorization):
    mutation_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["reserved", "writing", "unknown", "completed", "failed"]
    writer_ended: bool
    count_delta: Literal[-1, 0, 1] | None = None
    commit_epoch: int | None = Field(default=None, gt=0)
    error_code: str | None = None


class ChunkMutationIntent(Contract):
    knowledge_id: int = Field(gt=0)
    chunk_id: str = Field(min_length=1, max_length=1024)
    request_key: str = Field(min_length=1, max_length=256)
    operation: Literal["create", "update", "delete"]
    resource_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    changes: dict[str, JsonValue] = Field(default_factory=dict)
    file_ref: KnowledgeFileReference | None = None
    generation: str | None = Field(default=None, min_length=1, max_length=256)
    chunk_index: int | None = Field(default=None, ge=0, le=2**63 - 1)
    expected_change_epoch: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def valid_binding(self):
        if self.file_ref is None:
            if self.generation is not None or self.chunk_index is not None:
                raise ValueError("Standalone chunks must not invent file metadata")
        elif (
            self.file_ref.knowledge_id != self.knowledge_id
            or self.generation is None
            or self.chunk_index is None
        ):
            raise ValueError("Expected a complete binding to the same knowledge base")
        if self.operation == "delete" and self.changes:
            raise ValueError("Delete has no field changes")
        json.dumps(self.changes, allow_nan=False)
        return self

    def fingerprint(self):
        payload = self.model_dump(mode="json")
        if self.expected_change_epoch is None:
            payload.pop("expected_change_epoch")
        return hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()


def state_id(tenant_id, knowledge_id):
    return hashlib.sha256(
        json.dumps(
            ["knowledge-chunk-state", tenant_id, knowledge_id], separators=(",", ":")
        ).encode()
    ).hexdigest()


def mutation_id(tenant_id, user_id, intent):
    return hashlib.sha256(
        json.dumps(
            [
                "knowledge-chunk-change",
                tenant_id,
                user_id,
                intent.knowledge_id,
                intent.request_key,
            ],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def chunk_key(tenant_id, knowledge_id, chunk_id):
    return hashlib.sha256(
        json.dumps([tenant_id, knowledge_id, chunk_id], separators=(",", ":")).encode()
    ).hexdigest()
