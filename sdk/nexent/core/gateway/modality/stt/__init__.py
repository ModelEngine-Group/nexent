"""STT adapters; importing this package registers Ali/Volc/ModelEngine."""

from .base import STTAdapter, STTRequest, STTStreamRequest, TranscriptionResult
from .ali import AliSTTConfig, AliSTTAdapter
from .volc import VolcSTTConfig, VolcSTTAdapter
from .modelengine import ModelEngineSTTAdapter

__all__ = [
    "STTAdapter", "STTRequest", "STTStreamRequest", "TranscriptionResult",
    "AliSTTConfig", "AliSTTAdapter",
    "VolcSTTConfig", "VolcSTTAdapter",
    "ModelEngineSTTAdapter",
]
