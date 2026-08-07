"""TTS (text-to-speech) adapter.

Ali / Volc use WebSocket. ModelEngine uses HTTP REST (text → Chat Completions
→ base64 audio in the response content array → decode to bytes).
"""

from __future__ import annotations

import asyncio
import base64
from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Optional

from ..base import ModelInfo, MultimodalAdapter
from ..context import ModelContext
from ..registry import register_adapter
from ..transport import HttpTransportMixin, WebSocketTransportMixin


@dataclass
class TTSRequest:
    """TTS request: synthesize ``text`` to audio."""

    text: str
    stream: bool = False
    voice: Optional[str] = None
    speed_ratio: float = 1.0


class TTSAdapter(MultimodalAdapter):
    """TTS adapter root."""

    modality = "tts"

    @abstractmethod
    async def invoke(self, request: TTSRequest) -> bytes:
        """Synthesize ``request.text`` → complete audio bytes (stream=False)."""

    @abstractmethod
    async def stream(self, request: TTSRequest) -> AsyncIterator[bytes]:
        """Stream audio chunks for ``request.text`` (stream=True)."""


@register_adapter("ali", "tts")
class AliTTSAdapter(TTSAdapter, WebSocketTransportMixin):
    """Wraps :class:`AliTTSModel` (CosyVoice / Qwen Realtime, JSON over WS)."""

    factory = "ali"

    def __init__(self, context: ModelContext) -> None:
        MultimodalAdapter.__init__(self, context)
        WebSocketTransportMixin.__init__(
            self,
            ws_url=context.extra.get("ws_url"),
            auth_headers=context.extra.get("auth_headers"),
        )

    def _build_inner(self) -> None:
        from ...ali_tts_model import AliTTSConfig, AliTTSModel

        extras = self._context.extra
        cfg = AliTTSConfig(
            api_key=self._context.api_key,
            model=self._context.model_name,
            voice=self._context.voice or "Cherry",
            speech_rate=self._context.speed_ratio,
            ws_url=self._ws_url,
            format=extras.get("format", "mp3"),
            sample_rate=extras.get("sample_rate", 16000),
        )
        self._inner = AliTTSModel(cfg, self._context.audio_file_path)

    async def invoke(self, request: TTSRequest) -> bytes:
        if self._inner is None:
            self._build_inner()
        return await self._inner.generate_speech(request.text, stream=False)

    async def stream(self, request: TTSRequest) -> AsyncIterator[bytes]:
        if self._inner is None:
            self._build_inner()
        gen = await self._inner.generate_speech(request.text, stream=True)
        async for chunk in gen:
            yield chunk

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


@register_adapter("volc", "tts")
class VolcTTSAdapter(TTSAdapter, WebSocketTransportMixin):
    """Wraps :class:`VolcTTSModel` (proprietary binary-frame WS)."""

    factory = "volc"

    def __init__(self, context: ModelContext) -> None:
        MultimodalAdapter.__init__(self, context)
        WebSocketTransportMixin.__init__(
            self,
            ws_url=context.extra.get("ws_url"),
            auth_headers=context.extra.get("auth_headers"),
        )

    def _build_inner(self) -> None:
        from ...volc_tts_model import VolcTTSConfig, VolcTTSModel

        cfg = VolcTTSConfig(
            appid=self._context.model_appid or "",
            token=self._context.access_token or "",
            speed_ratio=self._context.speed_ratio,
            voice_type=self._context.voice or self._context.extra.get(
                "voice_type", "zh_female_vv_uranus_bigtts"
            ),
            ws_url=self._ws_url
            or "wss://openspeech.bytedance.com/api/v1/tts/ws_binary",
        )
        self._inner = VolcTTSModel(cfg, self._context.audio_file_path)

    async def invoke(self, request: TTSRequest) -> bytes:
        if self._inner is None:
            self._build_inner()
        return await self._inner.generate_speech(request.text, stream=False)

    async def stream(self, request: TTSRequest) -> AsyncIterator[bytes]:
        if self._inner is None:
            self._build_inner()
        gen = await self._inner.generate_speech(request.text, stream=True)
        async for chunk in gen:
            yield chunk

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


@register_adapter("modelengine", "tts")
class ModelEngineTTSAdapter(TTSAdapter, HttpTransportMixin):
    """ModelEngine TTS — HTTP REST, text → Chat Completions → base64 audio in
    the response content array → decoded to bytes. Conversion lives here.
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
        from ...openai_llm import OpenAIModel

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

    async def invoke(self, request: TTSRequest) -> bytes:
        if self._inner is None:
            self._build_inner()
        messages = [
            {
                "role": "user",
                "content": [{"type": "text", "text": f"请将以下文字合成语音：{request.text}"}],
            }
        ]
        result = await asyncio.to_thread(self._inner, messages)
        content = getattr(result, "content", result)
        for part in content if isinstance(content, list) else []:
            if isinstance(part, dict) and part.get("type") == "audio_url":
                b64_data = part["audio_url"]["url"].split(",", 1)[1]
                return base64.b64decode(b64_data)
        raise ValueError("ModelEngine TTS response missing audio_url in content")

    async def stream(self, request: TTSRequest) -> AsyncIterator[bytes]:
        if self._inner is None:
            self._build_inner()
        completion_kwargs = {
            "model": self._inner.model_id,
            "messages": [{"role": "user", "content": request.text}],
            "stream": True,
        }
        async for chunk in await self._inner.client.chat.completions.create(
            **completion_kwargs
        ):
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield base64.b64decode(delta.content)

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
