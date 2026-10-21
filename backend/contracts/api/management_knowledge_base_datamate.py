# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from typing import Optional
from pydantic import BaseModel


class SyncDatamateRequest(BaseModel):
    """Request body for syncing DataMate knowledge bases."""

    datamate_url: Optional[str] = None
