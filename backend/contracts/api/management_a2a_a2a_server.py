# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from typing import Any, Dict, Optional
from pydantic import BaseModel


class A2AServerSettings(BaseModel):
    """A2A Server settings for an agent."""

    is_enabled: Optional[bool] = False
    card_overrides: Optional[Dict[str, Any]] = None
