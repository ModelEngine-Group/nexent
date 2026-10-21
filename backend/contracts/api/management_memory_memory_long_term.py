# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from typing import Optional
from pydantic import BaseModel


class CreateVersionRequest(BaseModel):
    content: str
    expected_active_version_id: Optional[int] = None


class ActivateVersionRequest(BaseModel):
    expected_active_version_id: Optional[int] = None
