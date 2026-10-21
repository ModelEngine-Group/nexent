# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from pydantic import BaseModel, Field


class HaotianListRequest(BaseModel):
    list_url: str = Field(..., description="Haotian knowledge sets list URL")
    authorization: str = Field(..., description="Authorization header value, e.g. 'Bearer xxx'")


class HaotianTestConnectionRequest(BaseModel):
    list_url: str = Field(..., description="Haotian knowledge sets list URL")
    authorization: str = Field(..., description="Authorization header value, e.g. 'Bearer xxx'")
