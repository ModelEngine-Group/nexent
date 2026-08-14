"""Modality-specific construction contexts for the gateway."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ModelContext:
    """Base construction context — common + cross-cutting fields.

    Subclasses add modality-specific fields. Passing a field the subclass
    doesn't declare raises TypeError at construction time.
    """

    model_name: str
    base_url: str
    api_key: str
    modality: str
    factory: str
    tenant_id: Optional[str] = None
    slot: Optional[str] = None           # VLM slot key (vlm/vlm3/...)
    ssl_verify: bool = True
    display_name: Optional[str] = None
    observer: Any = None                 # cross-cutting: LLM/VLM/ModelEngine STT/TTS
    timeout_seconds: Optional[float] = None  # cross-cutting: all HTTP-backed adapters

    def cache_key(self) -> tuple:
        return (self.tenant_id or "", self.modality, self.slot or "",
                self.model_name, self.factory)


@dataclass
class LLMContext(ModelContext):
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    stream: Optional[bool] = None
    max_output_tokens: Optional[int] = None
    frequency_penalty: Optional[float] = None
    extra_body: Optional[dict] = None    # OpenAI API passthrough


@dataclass
class LongContextLLMContext(LLMContext):
    max_tokens: Optional[int] = None           # context window size
    truncation_strategy: Optional[str] = None  # "start" | "end" | ...


@dataclass
class VLMContext(LLMContext):
    capabilities: Dict[str, bool] = field(default_factory=dict)  # {"audio": False}
    max_tokens: Optional[int] = None    # max output tokens for image analysis


@dataclass
class EmbeddingContext(ModelContext):
    embedding_dim: Optional[int] = None
    model_type: Optional[str] = None     # "embedding" | "multi_embedding"


@dataclass
class STTContext(ModelContext):
    language: str = "zh"
    audio_file_path: Optional[str] = None
    model_appid: Optional[str] = None    # Volc
    access_token: Optional[str] = None   # Volc
    ws_url: Optional[str] = None         # WS variants
    auth_headers: Optional[dict] = None
    format: str = "pcm"                  # Ali/Volc
    rate: int = 16000                    # Ali/Volc
    resourceid: Optional[str] = None     # Volc
    enable_vad: bool = True              # Ali default
    sample_rate: Optional[int] = None    # Ali/Volc
    timeout: Optional[int] = None        # Ali: per-operation WS timeout


@dataclass
class TTSContext(ModelContext):
    speed_ratio: float = 1.0
    voice: Optional[str] = None
    audio_file_path: Optional[str] = None
    model_appid: Optional[str] = None    # Volc
    access_token: Optional[str] = None   # Volc
    ws_url: Optional[str] = None         # WS variants
    auth_headers: Optional[dict] = None
    voice_type: Optional[str] = None     # Volc
    format: str = "mp3"                  # Ali
    sample_rate: int = 16000             # Ali
