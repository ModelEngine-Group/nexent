from enum import Enum


class ProviderEnum(str, Enum):
    """Supported model providers"""
    SILICON = "silicon"
    OPENAI = "openai"
    MODELENGINE = "modelengine"
    ZHIPU = "zhipu"


# Silicon Flow
SILICON_BASE_URL = "https://api.siliconflow.cn/v1/"
SILICON_GET_URL = "https://api.siliconflow.cn/v1/models"
# Zhipu AI
ZHIPU_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"
ZHIPU_GET_URL = "https://open.bigmodel.cn/api/paas/v4/models"
# Hardcoded Zhipu models (injected due to incomplete API response)
HARDCODED_ZHIPU_MODELS = {
    "llm": [
        {"id": "glm-4-flash", "object": "model", "owned_by": "zhipu"},
        {"id": "glm-4-air", "object": "model", "owned_by": "zhipu"},
        {"id": "glm-4-long", "object": "model", "owned_by": "zhipu"},
    ],
    "vlm": [
        {"id": "glm-4.6v", "object": "model", "owned_by": "zhipu"},
        {"id": "glm-4.6v-flash", "object": "model", "owned_by": "zhipu"},
        {"id": "glm-4v-plus", "object": "model", "owned_by": "zhipu"},
    ],
    "embedding": [
        {"id": "embedding-3", "object": "model", "owned_by": "zhipu"},
        {"id": "embedding-2", "object": "model", "owned_by": "zhipu"},
    ],
    "reranker": [
        {"id": "reranker-3", "object": "model", "owned_by": "zhipu"},
        {"id": "reranker-2", "object": "model", "owned_by": "zhipu"},
    ],
    "tts": [
        {"id": "cogspeech-1", "object": "model", "owned_by": "zhipu"},
    ],
    "stt": [
        {"id": "sensevoice-v1", "object": "model", "owned_by": "zhipu"},
    ],
}

# ModelEngine
# Base URL and API key are loaded from environment variables at runtime
