"""Models shared by the three Dreaming phases."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class DreamingCandidate(BaseModel):
    memory_id: int
    tenant_id: str
    user_id: str
    agent_id: str
    content: str
    recall_count: int = 0
    daily_count: int = 0
    grounded_count: int = 0
    total_retrieval_score: float = 0.0
    query_hashes: List[str] = Field(default_factory=list)
    recall_days: List[str] = Field(default_factory=list)
    concept_tags: List[str] = Field(default_factory=list)
    light_hits: int = 0
    rem_hits: int = 0
    last_recalled_at: Optional[datetime] = None
    last_light_at: Optional[datetime] = None
    last_rem_at: Optional[datetime] = None
    noise: bool = False
    already_promoted: bool = False


class DreamingMetrics(BaseModel):
    signal_count: int
    context_diversity: int
    frequency: float
    relevance: float
    query_diversity: float
    recency: float
    consolidation: float
    conceptual_richness: float
    phase_boost: float


class DreamingThresholds(BaseModel):
    min_score: float = 0.72
    min_recall_count: int = 3
    min_unique_queries: int = 2
    include_promoted: bool = False


class DreamingDecision(BaseModel):
    candidate: DreamingCandidate
    metrics: DreamingMetrics
    score: float
    promote: bool
    reason: str
    archive_suggested: bool = False
