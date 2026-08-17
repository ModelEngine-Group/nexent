"""Modality adapter aggregation layer.

Re-exports the public adapter API and triggers registration of all built-in
adapters via the ``@register_adapter`` decorators on import.
"""

from .vlm.modelengine import ModelEngineVLMAdapter
from .vlm.openai import OpenAIVLMAdapter
from .vlm.vlm_adapter import VLMAdapter, VLMRequest

__all__: list[str] = [
    # VLM
    "VLMAdapter", "VLMRequest", "OpenAIVLMAdapter", "ModelEngineVLMAdapter",
]
