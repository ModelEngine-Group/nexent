# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel


class CreateConversationShareRequest(BaseModel):
    mode: str = "selected"
    selected_user_message_ids: Optional[List[int]] = None
    expire_time: Optional[datetime] = None
    render_version: str = "legacy"
