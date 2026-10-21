# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from pydantic import BaseModel, Field


class IndependentAidpKnowledgeBaseListRequest(BaseModel):
    server_url: str = Field(..., description="Independent AIDP API base URL")
    api_key: str = Field(..., description="Independent AIDP API key")
    tenant_id: str = Field(default="aidp", description="AIDP tenant identifier")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=100, ge=1, le=100)
