"""Shared Agent projections, system references and preparation values."""

from dataclasses import dataclass
from typing import Any

WORKBENCH_OFFICIAL_SKILL_NAMES = (
    "docx",
    "pdf",
    "pptx",
    "xlsx",
    "canvas-design",
    "analyze-image",
)


@dataclass(frozen=True)
class AgentModelProjection:
    """Public model fields plus private availability metadata."""

    fields: dict
    deleted_model_ids: frozenset[int]
    availability_model_ids: list[int]


@dataclass(frozen=True)
class AgentRunContext:
    metadata: Any
    enable_memory: bool


@dataclass(frozen=True)
class SystemAgentRef:
    """Immutable reference to one published system Agent snapshot."""

    tenant_id: str
    system_key: str
    agent_id: int
    version_no: int


@dataclass(frozen=True)
class WorkbenchReleaseManifest:
    """Server-controlled capabilities for one Nexent release."""

    system_revision: str
    persistent_tool_names: tuple[str, ...]
    official_skill_names: tuple[str, ...] = WORKBENCH_OFFICIAL_SKILL_NAMES
