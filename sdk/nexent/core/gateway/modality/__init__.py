"""Modality adapter aggregation layer.

The only place that re-exports the public adapter API and triggers built-in
adapter registration: importing :mod:`nexent.core.gateway.modality` imports
every built-in adapter module, whose ``@register_adapter`` decorators populate
the process-wide :class:`AdapterRegistry`.

Modality subpackages (``llm`` / ``vlm`` / ``stt`` / ``tts`` / ``embedding`` /
``rerank``) are namespace packages on purpose: they ship no ``__init__.py`` so
this module stays the single aggregation point. Import concrete classes via
this layer or via their leaf module (``modality.vlm.openai``).
"""

from .embedding.dashscope import DashScopeEmbeddingAdapter
from .embedding.embedding_adapter import EmbeddingAdapter, EmbeddingRequest
from .embedding.jina import JinaEmbeddingAdapter
from .embedding.openai import OpenAICompatibleEmbeddingAdapter
from .embedding.siliconflow import SiliconflowEmbeddingAdapter
from .llm.llm_adapter import LLMAdapter, LLMRequest
from .llm.openai import OpenAILLMAdapter, OpenAILongContextLLMAdapter
from .rerank.cohere import CohereRerankAdapter
from .rerank.jina import JinaRerankAdapter
from .rerank.openai import OpenAICompatibleRerankAdapter
from .rerank.rerank_adapter import RerankAdapter, RerankRequest
from .stt.ali import AliSTTAdapter, AliSTTConfig
from .stt.modelengine import ModelEngineSTTAdapter
from .stt.stt_adapter import STTAdapter, STTRequest, STTStreamRequest, TranscriptionResult
from .stt.volc import VolcSTTAdapter, VolcSTTConfig
from .tts.ali import AliTTSAdapter, AliTTSConfig, AliTTSError
from .tts.modelengine import ModelEngineTTSAdapter
from .tts.tts_adapter import TTSAdapter, TTSRequest
from .tts.volc import VolcTTSAdapter, VolcTTSConfig
from .vlm.modelengine import ModelEngineVLMAdapter
from .vlm.openai import OpenAIVLMAdapter
from .vlm.vlm_adapter import VLMAdapter, VLMRequest


__all__ = [
    # LLM
    "LLMAdapter", "LLMRequest", "OpenAILLMAdapter", "OpenAILongContextLLMAdapter",
    # VLM
    "VLMAdapter", "VLMRequest", "OpenAIVLMAdapter", "ModelEngineVLMAdapter",
    # STT
    "STTAdapter", "STTRequest", "STTStreamRequest", "TranscriptionResult",
    "AliSTTAdapter", "AliSTTConfig", "VolcSTTAdapter", "VolcSTTConfig",
    "ModelEngineSTTAdapter",
    # TTS
    "TTSAdapter", "TTSRequest", "AliTTSAdapter", "AliTTSConfig", "AliTTSError",
    "VolcTTSAdapter", "VolcTTSConfig", "ModelEngineTTSAdapter",
    # Embedding
    "EmbeddingAdapter", "EmbeddingRequest", "JinaEmbeddingAdapter",
    "DashScopeEmbeddingAdapter", "SiliconflowEmbeddingAdapter",
    "OpenAICompatibleEmbeddingAdapter",
    # Rerank
    "RerankAdapter", "RerankRequest", "OpenAICompatibleRerankAdapter",
    "JinaRerankAdapter", "CohereRerankAdapter",
]
