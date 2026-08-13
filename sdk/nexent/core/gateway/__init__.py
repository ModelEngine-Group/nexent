"""Multimodal model unified adaptation gateway.

Provides a protocol-agnostic adapter layer that *composes* the existing,
stable model classes (``OpenAIModel`` / embedding / rerank …) behind a single
:class:`MultimodalGateway` entry point. For STT/TTS/VLM the protocol lives
directly in the adapter (no wrapped model class); LLM/LongContext stay as thin
``has-a`` delegation to ``OpenAIModel``. Adding a vendor becomes one
``@register_adapter(factory, modality)`` decorator — backend services no
longer hardcode ``if model_factory == ...`` dispatch.

Importing :mod:`nexent.core.gateway` (or its :mod:`.modality` subpackage)
registers all built-in adapters with the process-wide registry.

See ``doc/multimodal-gateway-design.md`` for the full design.
"""

from .multimodal_adapter import ModelInfo, MultimodalAdapter
from .model_context import (
    EmbeddingContext,
    LLMSampling,
    LLMContext,
    ModelContext,
    STTContext,
    TTSContext,
    VLMContext,
    WSTransport,
    build_context,
)
from .multimodal_gateway import MultimodalGateway, get_gateway
from .registry import AdapterRegistry, get_registry, register_adapter
from .transport import (
    HttpTransportMixin,
    WebSocketTransportMixin,
)

# Importing .modality registers all built-in adapters via @register_adapter.
from . import modality  # noqa: F401  (side-effect: registration)

__all__ = [
    "ModelInfo",
    "MultimodalAdapter",
    "ModelContext",
    "LLMContext",
    "VLMContext",
    "EmbeddingContext",
    "STTContext",
    "TTSContext",
    "LLMSampling",
    "WSTransport",
    "build_context",
    "MultimodalGateway",
    "get_gateway",
    "AdapterRegistry",
    "get_registry",
    "register_adapter",
    "HttpTransportMixin",
    "WebSocketTransportMixin",
    "modality",
]
