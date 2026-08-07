"""STT (speech-to-text) adapter.

Ali / Volc use WebSocket (``WebSocketTransportMixin``). ModelEngine uses HTTP
REST — it turns audio into base64 and reuses the OpenAI Chat Completions
protocol, so its ``_inner`` is :class:`OpenAIModel`, not a dedicated STT class
(the audio↔base64 conversion lives in the adapter's ``invoke``). This proves
the transport Mixin is orthogonal: an HTTP-only STT vendor needs no WebSocket
plumbing.
"""

from __future__ import annotations

import asyncio
import base64
import mimetypes
from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, Optional

from ..base import ModelInfo, MultimodalAdapter
from ..context import ModelContext
from ..registry import register_adapter
from ..transport import HttpTransportMixin, WebSocketTransportMixin


@dataclass
class STTRequest:
    """Batch STT request: transcribe a whole audio file."""

    audio_path: str


@dataclass
class STTStreamRequest:
    """Real-time STT request over an existing websocket."""

    websocket: Any
    config_received: bool = True  # Ali-specific; ignored by Volc


class STTAdapter(MultimodalAdapter):
    """STT adapter root."""

    modality = "stt"

    @abstractmethod
    async def invoke(self, request: STTRequest) -> Dict[str, Any]:
        """Transcribe ``request.audio_path`` → ``{"text": ..., "raw": ...}``."""

    @abstractmethod
    async def stream(self, request: STTStreamRequest) -> AsyncIterator[Dict[str, Any]]:
        """Real-time streaming transcription."""


@register_adapter("ali", "stt")
class AliSTTAdapter(STTAdapter, WebSocketTransportMixin):
    """Wraps :class:`AliSTTModel` (DashScope Realtime, JSON over WS)."""

    factory = "ali"

    def __init__(self, context: ModelContext) -> None:
        MultimodalAdapter.__init__(self, context)
        WebSocketTransportMixin.__init__(
            self,
            ws_url=context.extra.get("ws_url"),
            auth_headers=context.extra.get("auth_headers"),
        )

    def _build_inner(self) -> None:
        from ..ali_stt_model import AliSTTConfig, AliSTTModel

        cfg = AliSTTConfig(
            api_key=self._context.api_key,
            model=self._context.model_name,
            language=self._context.language,
            ws_url=self._ws_url,
            format=self._context.extra.get("format", "pcm"),
            rate=self._context.extra.get("rate", 16000),
            enable_vad=self._context.extra.get("enable_vad", True),
        )
        self._inner = AliSTTModel(cfg, self._context.audio_file_path)

    async def invoke(self, request: STTRequest) -> Dict[str, Any]:
        if self._inner is None:
            self._build_inner()
        return await self._inner.recognize_file(request.audio_path)

    async def stream(self, request: STTStreamRequest) -> AsyncIterator[Dict[str, Any]]:
        if self._inner is None:
            self._build_inner()
        await self._inner.start_streaming_session(
            request.websocket, config_received=request.config_received
        )
        return
        yield  # pragma: no cover  (marks as async generator)

    async def health_check(self) -> bool:
        if self._inner is None:
            self._build_inner()
        return await self._inner.check_connectivity()

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            model_id=self._context.model_name,
            display_name=self._context.display_name or "",
            provider=self.factory,
            capabilities={"audio": True, "realtime": True},
        )


@register_adapter("volc", "stt")
class VolcSTTAdapter(STTAdapter, WebSocketTransportMixin):
    """Wraps :class:`VolcSTTModel` (proprietary binary-frame WS)."""

    factory = "volc"

    def __init__(self, context: ModelContext) -> None:
        MultimodalAdapter.__init__(self, context)
        WebSocketTransportMixin.__init__(
            self,
            ws_url=context.extra.get("ws_url"),
            auth_headers=context.extra.get("auth_headers"),
        )

    def _build_inner(self) -> None:
        from ..volc_stt_model import VolcSTTConfig, VolcSTTModel

        cfg = VolcSTTConfig(
            appid=self._context.model_appid or "",
            access_token=self._context.access_token or "",
            ws_url=self._ws_url or "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel",
            format=self._context.extra.get("format", "pcm"),
            rate=self._context.extra.get("rate", 16000),
            resourceid=self._context.extra.get(
                "resourceid", "volc.bigasr.sauc.duration"
            ),
        )
        self._inner = VolcSTTModel(cfg, self._context.audio_file_path)

    async def invoke(self, request: STTRequest) -> Dict[str, Any]:
        if self._inner is None:
            self._build_inner()
        return await self._inner.recognize_file(request.audio_path)

    async def stream(self, request: STTStreamRequest) -> AsyncIterator[Dict[str, Any]]:
        if self._inner is None:
            self._build_inner()
        await self._inner.start_streaming_session(request.websocket)
        return
        yield  # pragma: no cover

    async def health_check(self) -> bool:
        if self._inner is None:
            self._build_inner()
        return await self._inner.check_connectivity()

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            model_id=self._context.model_name,
            display_name=self._context.display_name or "",
            provider=self.factory,
            capabilities={"audio": True, "realtime": True},
        )


@register_adapter("modelengine", "stt")
class ModelEngineSTTAdapter(STTAdapter, HttpTransportMixin):
    """ModelEngine STT — HTTP REST, audio → base64 → Chat Completions.

    Unlike Ali/Volc: inherits :class:`HttpTransportMixin` (not WS) and reuses
    :class:`OpenAIModel` as ``_inner`` (no dedicated STT class). The audio↔base64
    protocol conversion is the adapter's responsibility.
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

    def _build_inner(self) -> None:
        from ..openai_llm import OpenAIModel

        self._inner = OpenAIModel(
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
        if self._inner is None:
            self._build_inner()
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
        result = await asyncio.to_thread(self._inner, messages)
        return {"text": getattr(result, "content", str(result)), "raw": result}

    async def stream(self, request: STTStreamRequest) -> AsyncIterator[Dict[str, Any]]:
        # ModelEngine realtime STT = Chat Completions stream=True over HTTP (SSE),
        # feeding PCM chunks incrementally. Scaffold; full SSE parsing in Phase 2.
        raise NotImplementedError("ModelEngine STT streaming is a Phase 2 deliverable")

    async def health_check(self) -> bool:
        if self._inner is None:
            self._build_inner()
        return await asyncio.to_thread(self._inner.check_connectivity)

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            model_id=self._context.model_name,
            display_name=self._context.display_name or "",
            provider=self.factory,
            capabilities={"audio": True, "realtime": False},
        )
