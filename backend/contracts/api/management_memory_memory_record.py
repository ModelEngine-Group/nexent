# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from typing import List, Optional
from pydantic import BaseModel, Field


class CreateMemoryRequest(BaseModel):
    layer: str = Field(..., description="tenant | user | agent")
    content: str = Field(..., min_length=1)
    memory_type: Optional[str] = Field(
        default=None,
        description="long_term | short_term; defaults by layer",
    )
    agent_id: Optional[str] = None
    conversation_id: Optional[str] = None
    concept_tags: List[str] = Field(default_factory=list)
    idempotency_key: Optional[str] = None


class UpdateMemoryRequest(BaseModel):
    content: Optional[str] = None
    status: Optional[str] = None
    concept_tags: Optional[List[str]] = None


class SearchMemoryRequest(BaseModel):
    query: str
    agent_id: Optional[str] = None
    conversation_id: Optional[str] = None
    layers: Optional[List[str]] = None
    top_k: int = 5
    threshold: float = 0.65
    hybrid: bool = Field(
        default=False,
        description=(
            "When true, agent short-term memory is retrieved via a hybrid "
            "(BM25 + kNN) query against Elasticsearch instead of pure "
            "kNN. Defaults to false to preserve prior behavior."
        ),
    )
    weight_accurate: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description=(
            "Weight of the fuzzy (BM25) branch when hybrid=true. The "
            "complementary 1 - weight is given to the semantic kNN branch."
        ),
    )
