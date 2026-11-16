# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class SkillInstanceInfoRequest(BaseModel):
    """Request model for skill instance update.

    Note: skill_description and skill_content are no longer accepted.
    These fields are now retrieved from ag_skill_info_t table.
    """

    skill_id: int
    agent_id: int
    enabled: bool = True
    version_no: int = 0
    config_values: Optional[Dict[str, Any]] = None


class SkillRepositoryListingCreateRequest(BaseModel):
    """Request body for creating a marketplace listing from a skill snapshot."""

    icon: Optional[str] = Field(
        None, description="Marketplace card icon (emoji or URL)"
    )
    downloads: int = Field(
        0, ge=0, description="Initial download count for card display"
    )
    tags: Optional[List[str]] = Field(None, description="Marketplace tags")
    category_id: Optional[int] = Field(
        0, description="Optional marketplace category ID"
    )
    content: Optional[str] = Field(
        None, description="Listing note when submitting for review"
    )


class SkillRepositoryInstallRequest(BaseModel):
    """Request body for installing a repository skill into current tenant."""

    target_name: Optional[str] = Field(
        None,
        max_length=100,
        description="Target skill name in current tenant",
    )


class SkillRepositoryListingDetailResponse(BaseModel):
    """Detailed marketplace listing payload for skill repository detail view."""

    skill_repository_id: int
    skill_id: Optional[int] = None
    name: str
    description: Optional[str] = None
    source: Optional[str] = None
    submitted_by: Optional[str] = None
    icon: Optional[str] = None
    status: str
    category_id: Optional[int] = None
    tags: List[str] = Field(default_factory=list)
    downloads: int = 0
    created_at: Optional[str] = None
    content: Optional[str] = None
    config_schemas: Optional[Dict[str, Any]] = None
    config_values: Optional[Dict[str, Any]] = None
    tool_ids: List[int] = Field(default_factory=list)


class SkillZipEntry(BaseModel):
    """A skill bundled inside an agent export ZIP."""

    skill_name: str
    skill_zip_base64: str


class SkillResolution(BaseModel):
    """User-selected resolution for a duplicate skill during agent import."""

    skill_name: str
    action: Literal["rename", "use_existing"]
    new_name: Optional[str] = None


# Skill Management Data Models
# ---------------------------------------------------------------------------
class SkillCreateRequest(BaseModel):
    """Request model for creating a skill via JSON."""

    name: str
    description: str
    content: str
    tool_ids: Optional[List[int]] = []
    tool_names: Optional[List[str]] = []
    tags: Optional[List[str]] = []
    source: Optional[str] = "custom"
    group_ids: Optional[List[int]] = None
    ingroup_permission: Optional[str] = None
    config_schemas: Optional[Dict[str, Any]] = None
    config_values: Optional[Dict[str, Any]] = None
    files: Optional[List[Dict[str, str]]] = Field(
        default_factory=list,
        description="Additional skill files beyond SKILL.md. "
        "Each entry has 'path' (relative path) and 'content'. "
        "SKILL.md may also be sent here; the 'content' field is the primary SKILL.md source.",
    )


class SkillFileData(BaseModel):
    """A single file within a skill."""

    path: str = Field(
        description="Relative file path within the skill (e.g. 'SKILL.md', 'scripts/run.py')"
    )
    content: str = Field(description="Full file content")
    encoding: Optional[str] = Field(
        default=None, description="Source character encoding to preserve when writing"
    )
    encoding: Optional[str] = Field(
        default=None, description="Source character encoding to preserve when writing"
    )


class SkillUpdateRequest(BaseModel):
    """Request model for updating a skill."""

    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    tool_ids: Optional[List[int]] = None
    tool_names: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    source: Optional[str] = None
    group_ids: Optional[List[int]] = None
    ingroup_permission: Optional[str] = None
    config_schemas: Optional[Dict[str, Any]] = None
    config_values: Optional[Dict[str, Any]] = None
    files: Optional[List[SkillFileData]] = Field(
        default_factory=list,
        description="Updated skill files. Each entry has file_path and content. "
        "Pass 'SKILL.md' here to update the main skill file; other files are written as-is.",
    )


class SkillResponse(BaseModel):
    """Response model for skill data."""

    skill_id: int
    name: str
    description: str
    content: str
    tool_ids: List[int]
    tags: List[str]
    source: str
    group_ids: Optional[List[int]] = None
    ingroup_permission: Optional[str] = None
    config_schemas: Optional[Dict[str, Any]] = None
    config_values: Optional[Dict[str, Any]] = None
    created_by: Optional[str] = None
    create_time: Optional[str] = None
    updated_by: Optional[str] = None
    update_time: Optional[str] = None


class InstallSkillsRequest(BaseModel):
    skill_names: List[str] = Field(..., description="List of skill names to install")
    locale: Optional[str] = Field(
        default="en", description="Frontend locale (zh or en)"
    )
