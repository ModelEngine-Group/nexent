"""LLM adapters; importing this package registers OpenAI / LongContext."""

from .adapter import (
    LLMAdapter,
    LLMRequest,
    OpenAILLMAdapter,
    OpenAILongContextLLMAdapter,
)

__all__ = [
    "LLMAdapter",
    "LLMRequest",
    "OpenAILLMAdapter",
    "OpenAILongContextLLMAdapter",
]
