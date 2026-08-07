"""Modality adapters for the multimodal gateway.

Importing this package registers all built-in adapters with the process-wide
:class:`AdapterRegistry` via the ``@register_adapter`` decorators.
"""

from .embedding_adapter import (
    DashScopeEmbeddingAdapter,
    EmbeddingAdapter,
    EmbeddingRequest,
    JinaEmbeddingAdapter,
    OpenAICompatibleEmbeddingAdapter,
    SiliconflowEmbeddingAdapter,
)
from .llm_adapter import (
    LLMAdapter,
    LLMRequest,
    OpenAILLMAdapter,
    OpenAILongContextLLMAdapter,
)
from .realtime_adapter import RealtimeAdapter
from .rerank_adapter import (
    CohereRerankAdapter,
    JinaRerankAdapter,
    OpenAICompatibleRerankAdapter,
    RerankAdapter,
    RerankRequest,
)
from .stt_adapter import (
    AliSTTAdapter,
    ModelEngineSTTAdapter,
    STTAdapter,
    STTRequest,
    STTStreamRequest,
    VolcSTTAdapter,
)
from .tts_adapter import (
    AliTTSAdapter,
    ModelEngineTTSAdapter,
    TTSAdapter,
    TTSRequest,
    VolcTTSAdapter,
)
from .vlm_adapter import (
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
    # Realtime
    "RealtimeAdapter",
]
