# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from typing import List, Optional
from pydantic import BaseModel, Field

ASSET_OWNER_SKILL_VIEW_DENIED = {"content": "您无权限查看"}


_NOT_FOUND_TEXT = "not found"


class InstallSkillsRequest(BaseModel):
    skill_names: List[str] = Field(..., description="List of skill names to install")
    locale: Optional[str] = Field(default="en", description="Frontend locale (zh or en)")
