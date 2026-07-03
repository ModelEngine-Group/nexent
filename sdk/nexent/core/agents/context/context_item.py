"""Context item data models for fine-grained context management."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ContextItemType(str, Enum):
    """Enumeration of all context item types."""

    SYSTEM_PROMPT = "system_prompt"
    TOOL = "tool"
    SKILL = "skill"
    MEMORY = "memory"
    KNOWLEDGE_BASE = "knowledge_base"
    MANAGED_AGENT = "managed_agent"
    EXTERNAL_AGENT = "external_agent"
    HISTORY_TURN = "history_turn"
    TOOL_CALL_RESULT = "tool_call_result"
    WORKING_MEMORY = "working_memory"


class RepresentationTier(str, Enum):
    """Fidelity levels for context item representations."""

    FULL = "full"
    COMPRESSED = "compressed"
    STRUCTURED = "structured"
    POINTER = "pointer"


class AuthorityTier(str, Enum):
    """Authority tiers for context item provenance tracking."""

    PLATFORM = "platform"
    TENANT = "tenant"
    USER = "user"
    WORKING_MEMORY = "working_memory"
    TOOL_RESULT = "tool_result"
    RETRIEVED_MEMORY = "retrieved_memory"
    SUMMARY = "summary"
    AGENT_INFERENCE = "agent_inference"


@dataclass
class ContextItem:
    """Bounded, source-traced context candidate unit.

    Each ContextItem represents a discrete piece of context that can be
    selected, scored, reduced, and tracked independently. Items carry
    provenance metadata (source_refs, authority_tier) and fidelity
    constraints (minimum_fidelity, current_representation) to support
    policy-driven context management.
    """

    item_id: str
    item_type: ContextItemType
    source_refs: List[str] = field(default_factory=list)
    authority_tier: AuthorityTier = AuthorityTier.AGENT_INFERENCE
    minimum_fidelity: RepresentationTier = RepresentationTier.STRUCTURED
    current_representation: RepresentationTier = RepresentationTier.FULL
    content: Any = None
    token_estimate: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    lifecycle_status: str = "active"
    recompute_cost: Optional[int] = None
