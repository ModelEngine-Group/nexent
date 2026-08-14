"""Multimodal model unified adaptation gateway.

A protocol-agnostic adapter layer behind a single :class:`MultimodalGateway`
entry point; importing this package registers all built-in adapters.
"""

from .multimodal_adapter import ModelInfo, MultimodalAdapter
from .model_context import (
    EmbeddingContext,
    LLMContext,
    LongContextLLMContext,
    ModelContext,
    STTContext,
    TTSContext,
    VLMContext,
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
    "LongContextLLMContext",
    "VLMContext",
    "EmbeddingContext",
    "STTContext",
    "TTSContext",
    "MultimodalGateway",
    "get_gateway",
    "AdapterRegistry",
    "get_registry",
    "register_adapter",
    "HttpTransportMixin",
    "WebSocketTransportMixin",
    "modality",
]
