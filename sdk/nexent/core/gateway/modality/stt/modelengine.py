"""ModelEngine STT adapter (HTTP REST, audio via base64)."""

from __future__ import annotations

import asyncio
import base64
import mimetypes
from typing import Any, AsyncIterator, Dict

from nexent.core.models import OpenAIModel
from ...multimodal_adapter import MultimodalAdapter, ModelInfo
from ...model_context import ModelContext
from ...registry import register_adapter
from ...transport import HttpTransportMixin
from .base import STTAdapter, STTRequest, STTStreamRequest

@register_adapter("modelengine", "stt")
class ModelEngineSTTAdapter(STTAdapter, HttpTransportMixin):
    """ModelEngine STT — HTTP REST, audio → base64 → Chat Completions.

    Attributes:
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

    async def invoke(self, request: STTRequest) -> Dict[str, Any]:
        """Transcribe ``request.audio_path`` via HTTP Chat Completions; returns ``{"text": ..., "raw": ...}``."""
        if self._model is None:
            self._build_model()
        audio_bytes = open(request.audio_path, "rb").read()
        b64 = base64.b64encode(audio_bytes).decode()
        mime = mimetypes.guess_type(request.audio_path)[0] or "audio/wav"
        data_url = f"data:{mime};base64,{b64}"
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "audio_url", "audio_url": {"url": data_url}},
                    {"type": "text", "text": "请将这段音频转写成文字"},
                ],
            }
        ]
        result = await asyncio.to_thread(self._model, messages)
        return {"text": getattr(result, "content", str(result)), "raw": result}

    async def stream(self, request: STTStreamRequest) -> AsyncIterator[Dict[str, Any]]:
        """Real-time streaming is not supported by ModelEngine STT.

        ModelEngine STT is non-realtime file transcription (``realtime: False``);
        the WebSocket duplex mic contract cannot be served over Chat Completions.

        Raises:
            NotImplementedError: Always; this adapter does not stream.
        """
        raise NotImplementedError("ModelEngine STT is non-realtime; streaming is not supported")

    async def health_check(self) -> bool:
        """Probe the wrapped model's connectivity."""
        if self._model is None:
            self._build_model()
        return await asyncio.to_thread(self._model.check_connectivity)

    def get_model_info(self) -> ModelInfo:
        """Return ``ModelInfo`` with audio capability (no realtime)."""
        return ModelInfo(
            model_id=self._context.model_name,
            display_name=self._context.display_name or "",
            provider=self.factory,
            capabilities={"audio": True, "realtime": False},
        )

