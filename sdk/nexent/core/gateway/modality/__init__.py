"""Modality adapters for the multimodal gateway.

Importing this package registers all built-in adapters with the process-wide
:class:`AdapterRegistry` via the ``@register_adapter`` decorators.
"""

from .embedding import (
    DashScopeEmbeddingAdapter,
    EmbeddingAdapter,
    EmbeddingRequest,
    JinaEmbeddingAdapter,
    OpenAICompatibleEmbeddingAdapter,
    SiliconflowEmbeddingAdapter,
)
from .llm import (
    LLMAdapter,
    LLMRequest,
    OpenAILLMAdapter,
    OpenAILongContextLLMAdapter,
)
from .rerank import (
    CohereRerankAdapter,
    JinaRerankAdapter,
    OpenAICompatibleRerankAdapter,
    RerankAdapter,
    RerankRequest,
)
from .stt import (
    AliSTTAdapter,
    ModelEngineSTTAdapter,
    STTAdapter,
    STTRequest,
    STTStreamRequest,
    VolcSTTAdapter,
)
from .tts import (
    AliTTSAdapter,
    ModelEngineTTSAdapter,
    TTSAdapter,
    TTSRequest,
    VolcTTSAdapter,
)
from .vlm import (
    ModelEngineVLMAdapter,
    OpenAIVLMAdapter,
    VLMAdapter,
    VLMRequest,
)

__all__ = [
    # LLM
    "LLMAdapter", "LLMRequest", "OpenAILLMAdapter", "OpenAILongContextLLMAdapter",
    # VLM
    "VLMAdapter", "VLMRequest", "OpenAIVLMAdapter", "ModelEngineVLMAdapter",
    # STT
    "STTAdapter", "STTRequest", "STTStreamRequest", "AliSTTAdapter",
    "VolcSTTAdapter", "ModelEngineSTTAdapter",
    # TTS
    "TTSAdapter", "TTSRequest", "AliTTSAdapter", "VolcTTSAdapter",
    "ModelEngineTTSAdapter",
    # Embedding
    "EmbeddingAdapter", "EmbeddingRequest", "JinaEmbeddingAdapter",
    "DashScopeEmbeddingAdapter", "SiliconflowEmbeddingAdapter",
    "OpenAICompatibleEmbeddingAdapter",
    # Rerank
    "RerankAdapter", "RerankRequest", "OpenAICompatibleRerankAdapter",
    "JinaRerankAdapter", "CohereRerankAdapter",
]
