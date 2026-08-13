"""TTS adapters; importing this package registers Ali/Volc/ModelEngine."""

from .base import TTSAdapter, TTSRequest
from .ali import AliTTSConfig, AliTTSError, AliTTSAdapter
from .volc import VolcTTSConfig, VolcTTSAdapter
from .modelengine import ModelEngineTTSAdapter

__all__ = [
    "TTSAdapter", "TTSRequest",
    "AliTTSConfig", "AliTTSError", "AliTTSAdapter",
    "VolcTTSConfig", "VolcTTSAdapter",
    "ModelEngineTTSAdapter",
]
