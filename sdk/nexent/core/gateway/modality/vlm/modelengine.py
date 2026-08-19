"""ModelEngine VLM adapter; protocol identical to OpenAI, only factory differs."""

from __future__ import annotations

from ...registry import register_adapter
from .openai import OpenAIVLMAdapter


@register_adapter("modelengine", "vlm")
class ModelEngineVLMAdapter(OpenAIVLMAdapter):
    """ModelEngine VLM - protocol identical to OpenAI; only ``factory`` differs.

    Attributes:
        factory: ``"modelengine"``.
    """

    factory = "modelengine"
