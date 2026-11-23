"""Immutable model descriptors and capacity suggestion contracts."""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

ProfileKey = tuple[str, str]
CapabilityProfileLike = Any


class CapacitySuggestionMatchKind(str, Enum):
    CATALOG_EXACT = "catalog_exact"
    CATALOG_FUZZY = "catalog_fuzzy"
    PROVIDER_DISCOVERY = "provider_discovery"
    LITELLM_LOOKUP = "litellm_lookup"
    NONE = "none"


class CapacitySuggestionConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class CapacitySuggestionFields:
    context_window_tokens: Optional[int] = None
    max_input_tokens: Optional[int] = None
    max_output_tokens: Optional[int] = None
    default_output_reserve_tokens: Optional[int] = None
    tokenizer_family: Optional[str] = None


@dataclass(frozen=True)
class CapacitySuggestionResult:
    suggestions: Optional[CapacitySuggestionFields]
    match_kind: CapacitySuggestionMatchKind
    match_confidence: Optional[CapacitySuggestionConfidence]
    match_explanation: str
    suggested_provider: Optional[str] = None
    canonical_model_name: Optional[str] = None
    capability_profile_version: Optional[str] = None
    capacity_source_on_accept: Optional[str] = None


@dataclass(frozen=True)
class ModelDescriptor:
    display_name: str = ""
    is_multimodal: bool = False
