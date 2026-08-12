"""Unified construction context for all model modalities.

Consolidates the five historically distinct construction-parameter styles
(LLM/VLM observer+model_id+api_base; Embedding api_key+base_url+model_name+dim;
Rerank model_name+base_url+api_key; STT/TTS Config+audio_file_path;
LongContext LLM max_context_tokens+truncation_strategy) into a single dataclass
so :class:`MultimodalGateway` can build any adapter from one source of truth.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ModelContext:
    """Unified construction parameters for every model type.

    ``modality`` is the capability family: ``llm`` | ``llm_long_context`` |
    ``vlm`` | ``stt`` | ``tts`` | ``embedding`` | ``multi_embedding`` |
    ``rerank``.

    ``factory`` is the normalized provider name: ``openai`` | ``ali`` |
    ``volc`` | ``jina`` | ``siliconflow`` | ``dashscope`` | ``cohere`` |
    ``modelengine`` | ...

    ``slot`` mirrors ``MODEL_CONFIG_MAPPING`` keys (``llm``/``vlm``/``vlm2``/
    ``vlm3``/``stt``/``tts``/...) so the gateway can distinguish the VLM slots.
    """

    model_name: str
    base_url: str
    api_key: str
    modality: str
    factory: str
    tenant_id: Optional[str] = None
    slot: Optional[str] = None
    ssl_verify: bool = True
    # Embedding
    embedding_dim: Optional[int] = None
    model_type: Optional[str] = None  # "embedding" | "multi_embedding"
    # Volc
    model_appid: Optional[str] = None
    access_token: Optional[str] = None
    # TTS
    speed_ratio: float = 1.0
    voice: Optional[str] = None
    # STT
    language: str = "zh"
    audio_file_path: Optional[str] = None
    # LLM/VLM need a MessageObserver
    observer: Any = None
    display_name: Optional[str] = None
    # Capability declaration, replaces hardcoded URL sniffing
    capabilities: Dict[str, bool] = field(default_factory=dict)
    # Protocol-specific extras (WS URL, format, rate, max_tokens,
    # truncation_strategy, timeout_seconds, extra_body, ...)
    extra: Dict[str, Any] = field(default_factory=dict)

    def cache_key(self) -> tuple:
        """Returns a stable identity for adapter instance caching.

        Returns:
            A tuple of ``(tenant_id, modality, slot, model_name, factory)``.
        """
        return (
            self.tenant_id or "",
            self.modality,
            self.slot or "",
            self.model_name,
            self.factory,
        )
