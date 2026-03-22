from enum import Enum


class ProviderEnum(str, Enum):
    """Supported model providers"""
    SILICON = "silicon"
    OPENAI = "openai"
    MODELENGINE = "modelengine"
    DASHSCOPE = "dashscope"
    TOKENPONY = "tokenpony"
    MINIMAX = "minimax"


# Silicon Flow
SILICON_BASE_URL = "https://api.siliconflow.cn/v1/"
SILICON_GET_URL = "https://api.siliconflow.cn/v1/models"

# Dashcope
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/"
DASHSCOPE_GET_URL = "https://dashscope.aliyuncs.com/api/v1/models"

# TokenPony
TOKENPONY_BASE_URL = "https://api.tokenpony.cn/v1/"
TOKENPONY_GET_URL = "https://api.tokenpony.cn/v1/models"

# MiniMax
MINIMAX_BASE_URL = "https://api.minimax.io/v1/"
MINIMAX_GET_URL = "https://api.minimax.io/v1/models"

# ModelEngine
# Base URL and API key are loaded from environment variables at runtime
