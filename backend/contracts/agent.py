# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

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


from typing import Optional as Opt


@dataclass
class OptimizeRequest:
    """优化请求的统一数据结构"""

    agent_id: int
    model_id: int
    task_description: str
    section_type: str
    section_title: str
    current_content: str
    feedback: str
    mode: str = "general"
    start_pos: Opt[int] = None
    end_pos: Opt[int] = None
    tool_ids: Opt[list[int]] = None
    sub_agent_ids: Opt[list[int]] = None
    knowledge_base_display_names: Opt[list[str]] = None


@dataclass
class OptimizeResult:
    """优化结果的统一数据结构"""

    optimized_content: str
    source: str
    section_type: str = ""
    section_title: str = ""
    original_content: str = ""
