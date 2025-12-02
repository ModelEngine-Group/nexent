from enum import Enum


class ProviderEnum(str, Enum):
    """Supported model providers"""
    SILICON = "silicon"
    OPENAI = "openai"
    MODELENGINE = "modelengine"


# Silicon Flow
SILICON_BASE_URL = "https://api.siliconflow.cn/v1/"
SILICON_GET_URL = "https://api.siliconflow.cn/v1/models"

# ModelEngine
# Base URL and API key are loaded from environment variables at runtime
