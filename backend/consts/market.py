"""Constants and enums for the unified market module."""

from enum import Enum
from typing import Any, Dict

from pydantic import BaseModel, Field


class EntityType(str, Enum):
    """Entity types supported by the unified market."""
    AGENT = "agent"
    SKILL = "skill"
    MCP = "mcp"
    RECIPE = "recipe"
    EXPERT = "expert"


class ReviewStatus(str, Enum):
    """Review visibility status for market reviews."""
    VISIBLE = "visible"
    HIDDEN = "hidden"
    PENDING = "pending"


class SortOrder(str, Enum):
    """Sort order options for market listing queries."""
    LATEST = "latest"
    POPULAR = "popular"
    RATING = "rating"
    NAME = "name"


# Agent repository listing statuses reused by the market layer
STATUS_SHARED = "shared"
STATUS_NOT_SHARED = "not_shared"
STATUS_PENDING_REVIEW = "pending_review"
STATUS_REJECTED = "rejected"

# Source types for market listings
SOURCE_OFFICIAL = "official"
SOURCE_COMMUNITY = "community"

# Expert type values
EXPERT_TYPE_AGENT = "agent"
EXPERT_TYPE_EXPERT = "expert"


class InstantiateRequest(BaseModel):
    """Request body for instantiating an agent from a market template.

    ``variable_values`` carries the Recipe variable values used to replace
    ``<<TO_CONFIG:xxx>>`` placeholders in the frozen template snapshot.
    """

    variable_values: Dict[str, Any] = Field(default_factory=dict)
    force_import: bool = False
