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

    Attributes:
        model_name: Provider model identifier passed to the API.
        base_url: HTTP or WebSocket endpoint base URL.
        api_key: Authorization credential.
        modality: Capability family (see above).
        factory: Normalized provider name (see above).
        tenant_id: Optional tenant scope.
        slot: Optional config-mapping slot key; disambiguates VLM slots.
        ssl_verify: Whether to verify TLS certificates.
        display_name: Optional human-readable label.
        observer: Optional smolagents Observer for LLM/VLM streaming.
        embedding_dim: Optional embedding vector dimension.
        model_type: ``"embedding"`` | ``"multi_embedding"``.
        language: STT language code (default ``"zh"``).
        audio_file_path: Optional STT/TTS audio file path.
        speed_ratio: TTS speech-rate multiplier.
        voice: Optional TTS voice id.
        model_appid: Volc STT/TTS app id.
        access_token: Volc STT/TTS access token.
        capabilities: Per-capability flags, e.g. ``{"audio": True}``.
        extra: Protocol-specific extensions (WS URL, format, rate,
            max_tokens, truncation_strategy, timeout_seconds, extra_body, ...).
    """

    # ---- 通用 ----
    model_name: str
    base_url: str
    api_key: str
    modality: str
    factory: str
    tenant_id: Optional[str] = None
    slot: Optional[str] = None
    ssl_verify: bool = True
    display_name: Optional[str] = None

    # ---- LLM / VLM ----
    observer: Any = None

    # ---- Embedding ----
    embedding_dim: Optional[int] = None
    model_type: Optional[str] = None  # "embedding" | "multi_embedding"

    # ---- STT ----
    language: str = "zh"
    audio_file_path: Optional[str] = None

    # ---- TTS ----
    speed_ratio: float = 1.0
    voice: Optional[str] = None

    # ---- Volc (STT/TTS) ----
    model_appid: Optional[str] = None
    access_token: Optional[str] = None

    # ---- 能力声明 ----
    capabilities: Dict[str, bool] = field(default_factory=dict)

    # ---- 协议特定扩展 ----
    # (WS URL, format, rate, max_tokens, truncation_strategy, timeout_seconds,
    # extra_body, ...)
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
