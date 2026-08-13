"""ModelEngine TTS adapter (HTTP REST, audio via base64)."""

from __future__ import annotations

import asyncio
import base64
from typing import Any, AsyncIterator

from ....openai_llm import OpenAIModel
from ...multimodal_adapter import MultimodalAdapter, ModelInfo
from ...model_context import ModelContext
from ...registry import register_adapter
from ...transport import HttpTransportMixin
from .base import TTSAdapter, TTSRequest

@register_adapter("modelengine", "tts")
class ModelEngineTTSAdapter(TTSAdapter, HttpTransportMixin):
    """ModelEngine TTS — HTTP REST, text → Chat Completions → base64 audio in
    the response content array → decoded to bytes. Conversion lives here.

    Attributes:
        modality: ``"tts"`` (inherited).
        factory: ``"modelengine"``.
        _model: The wrapped :class:`OpenAIModel`, built lazily.
    """

    factory = "modelengine"

    def __init__(self, context: ModelContext) -> None:
        MultimodalAdapter.__init__(self, context)
        HttpTransportMixin.__init__(
            self,
            base_url=context.base_url,
            api_key=context.api_key,
            ssl_verify=context.ssl_verify,
            timeout=context.extra.get("timeout_seconds", 30.0),
        )
        self._model: Any = None  # wrapped OpenAIModel, built lazily

    def _build_model(self) -> None:
        """Construct the wrapped :class:`OpenAIModel` on first use."""
        self._model = OpenAIModel(
            observer=self._context.observer,
            model_id=self._context.model_name,
            api_base=self._base_url,
            api_key=self._api_key,
            ssl_verify=self._ssl_verify,
            model_factory=self.factory,
            display_name=self._context.display_name,
            timeout_seconds=self._context.extra.get("timeout_seconds"),
        )

    async def invoke(self, request: TTSRequest) -> bytes:
        """Synthesize audio via the ModelEngine Chat Completions API.

        Returns:
            The decoded audio bytes from the response's ``audio_url`` part.

        Raises:
            ValueError: If the response content has no ``audio_url`` part.
        """
        if self._model is None:
            self._build_model()
        messages = [
            {
                "role": "user",
                "content": [{"type": "text", "text": f"请将以下文字合成语音：{request.text}"}],
            }
        ]
        result = await asyncio.to_thread(self._model, messages)
        content = getattr(result, "content", result)
        for part in content if isinstance(content, list) else []:
            if isinstance(part, dict) and part.get("type") == "audio_url":
                b64_data = part["audio_url"]["url"].split(",", 1)[1]
                return base64.b64decode(b64_data)
        raise ValueError("ModelEngine TTS response missing audio_url in content")

    async def stream(self, request: TTSRequest) -> AsyncIterator[bytes]:
        """Stream audio chunks via the ModelEngine Chat Completions API.

        Yields:
            Decoded audio chunks from each streamed ``delta.content``.
        """
        if self._model is None:
            self._build_model()
        completion_kwargs = {
            "model": self._model.model_id,
            "messages": [{"role": "user", "content": request.text}],
            "stream": True,
        }
        async for chunk in await self._model.client.chat.completions.create(
            **completion_kwargs
        ):
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield base64.b64decode(delta.content)

    async def health_check(self) -> bool:
        """Probe the wrapped model's connectivity."""
        if self._model is None:
            self._build_model()
        return await asyncio.to_thread(self._model.check_connectivity)

    def get_model_info(self) -> ModelInfo:
        """Return ``ModelInfo`` advertising audio (non-realtime) capability."""
        return ModelInfo(
            model_id=self._context.model_name,
            display_name=self._context.display_name or "",
            provider=self.factory,
            capabilities={"audio": True, "realtime": False},
        )

