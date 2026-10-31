# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


from pydantic import BaseModel, Field


# Voice Service Data Models
# ---------------------------------------------------------------------------
class VoiceConnectivityRequest(BaseModel):
    """Request model for voice service connectivity check"""

    model_type: str = Field(..., description="Type of model to check ('stt' or 'tts')")


class VoiceConnectivityResponse(BaseModel):
    """Response model for voice service connectivity check"""

    connected: bool = Field(..., description="Whether the service is connected")
    model_type: str = Field(..., description="Type of model checked")
    message: str = Field(..., description="Status message")
