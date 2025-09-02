from enum import Enum


class ProviderEnum(str, Enum):
    """Supported model providers"""
    SILICON = "silicon"
    OPENAI = "openai"


# Silicon Flow
SILICON_BASE_URL = "https://api.siliconflow.cn/v1/"
SILICON_GET_URL = "https://api.siliconflow.cn/v1/models"
