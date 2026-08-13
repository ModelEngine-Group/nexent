"""Volc TTS adapter (proprietary binary-frame WebSocket)."""

from __future__ import annotations

import copy
import gzip
import io
import json
import traceback
import uuid
import websockets
import logging
from dataclasses import dataclass
from typing import AsyncGenerator, AsyncIterator, Dict, Optional, Union

from ...multimodal_adapter import MultimodalAdapter, ModelInfo
from ...model_context import ModelContext
from ...registry import register_adapter
from ...transport import WebSocketTransportMixin
from .base import TTSAdapter, TTSRequest

logger = logging.getLogger(__name__)

@dataclass
class VolcTTSConfig:
    """Configuration for Volcano Engine TTS model.

    Attributes:
        appid: Volcano Engine app id.
        token: Access token (used for Bearer + X-Api headers).
        speed_ratio: Speech rate multiplier.
        ws_url: WebSocket endpoint for the binary TTS API.
        host: Host header value.
        encoding: Audio encoding (``"mp3"``, ...).
        volume_ratio: Volume multiplier.
        pitch_ratio: Pitch multiplier.
        cluster: Volcano TTS cluster id.
        resource_id: Resource id for the voice model.
        voice_type: Voice id to synthesize with.
    """
    appid: str
    token: str
    speed_ratio: float
    ws_url: str = "wss://openspeech.bytedance.com/api/v1/tts/ws_binary"
    host: str = "openspeech.bytedance.com"
    encoding: str = "mp3"
    volume_ratio: float = 1.0
    pitch_ratio: float = 1.0
    cluster: str = "volcano_tts"
    resource_id: str = "seed-tts-2.0"
    voice_type: str = "zh_female_vv_uranus_bigtts"

    @property
    def api_url(self) -> str:
        """The WebSocket URL used for the binary connection."""
        return self.ws_url


@register_adapter("volc", "tts")
class VolcTTSAdapter(TTSAdapter, WebSocketTransportMixin):
    """Volc TTS — proprietary binary-frame WS.

    The full binary protocol (DEFAULT_HEADER framing, gzip-compressed JSON
    payload, response parsing for audio-only / error message types) lives here.

    Attributes:
        modality: ``"tts"`` (inherited).
        factory: ``"volc"``.
        _config: The :class:`VolcTTSConfig` built from the construction context.
        _audio_file_path: Optional path for persisted audio output.
        _request_template: Base request dict deep-copied per synthesis call.
    """

    factory = "volc"

    MESSAGE_TYPES = {11: "audio-only server response", 12: "frontend server response", 15: "error message from server"}
    MESSAGE_TYPE_SPECIFIC_FLAGS = {0: "no sequence number", 1: "sequence number > 0",
                                   2: "last message from server (seq < 0)", 3: "sequence number < 0"}
    MESSAGE_SERIALIZATION_METHODS = {0: "no serialization", 1: "JSON", 15: "custom type"}
    MESSAGE_COMPRESSIONS = {0: "no compression", 1: "gzip", 15: "custom compression method"}

    DEFAULT_HEADER = bytearray([0x11, 0x10, 0x11, 0x00])

    def __init__(self, context: ModelContext) -> None:
        MultimodalAdapter.__init__(self, context)
        WebSocketTransportMixin.__init__(
            self,
            ws_url=context.extra.get("ws_url"),
            auth_headers=context.extra.get("auth_headers"),
        )
        self._config = VolcTTSConfig(
            appid=context.model_appid or "",
            token=context.access_token or "",
            speed_ratio=context.speed_ratio,
            voice_type=context.voice or context.extra.get(
                "voice_type", "zh_female_vv_uranus_bigtts"
            ),
            ws_url=self._ws_url
            or "wss://openspeech.bytedance.com/api/v1/tts/ws_binary",
        )
        self._audio_file_path = context.audio_file_path
        self._request_template = {
            "app": {"appid": self._config.appid, "token": self._config.token, "cluster": self._config.cluster, "resource_id": self._config.resource_id},
            "user": {"uid": "388808087185088"},
            "audio": {
                "voice_type": self._config.voice_type,
                "encoding": self._config.encoding,
                "speed_ratio": self._config.speed_ratio,
                "volume_ratio": self._config.volume_ratio,
                "pitch_ratio": self._config.pitch_ratio,
            },
            "request": {"reqid": "xxx", "text": "", "text_type": "plain", "operation": "xxx"}
        }

    def get_websocket_url(self) -> str:
        """Get the WebSocket URL for the TTS service."""
        return self._config.api_url

    def get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers for the WebSocket connection."""
        headers = {
            "Authorization": f"Bearer; {self._config.token}",
            "X-Api-App-Id": self._config.appid,
            "X-Api-Access-Key": self._config.token,
            "X-Api-Resource-Id": self._config.resource_id
        }
        return headers

    def _prepare_request(self, text: str, operation: str = "submit") -> bytes:
        """Build the gzip-compressed binary request payload."""
        request_json = copy.deepcopy(self._request_template)
        request_json["request"]["reqid"] = str(uuid.uuid4())
        request_json["request"]["text"] = text
        request_json["request"]["operation"] = operation
        payload_bytes = str.encode(json.dumps(request_json))
        payload_bytes = gzip.compress(payload_bytes)
        full_request = bytearray(self.DEFAULT_HEADER)
        full_request.extend(len(payload_bytes).to_bytes(4, 'big'))
        full_request.extend(payload_bytes)
        return bytes(full_request)

    def _parse_response(self, res: bytes, buffer: Optional[io.BytesIO] = None) -> tuple[bool, Optional[bytes]]:
        """Parse a binary response frame from the Volc TTS server.

        Args:
            res: The raw binary frame received from the server.
            buffer: Optional accumulator; audio chunks are written into it
                when provided (non-streaming mode).

        Returns:
            A ``(done, chunk)`` tuple where ``done`` is True when this is the
            last frame of the synthesis, and ``chunk`` is the audio bytes
            (or ``None`` for non-audio frames).

        Raises:
            Exception: When the frame is an error message (message type 0xf).
        """
        protocol_version = res[0] >> 4
        header_size = res[0] & 0x0f
        message_type = res[1] >> 4
        message_type_specific_flags = res[1] & 0x0f
        payload = res[header_size * 4:]
        logger.info(f"Volc TTS protocol: version={protocol_version}, header_size={header_size}, msg_type={message_type:#x}, flags={message_type_specific_flags}")

        if message_type == 0xb:
            if message_type_specific_flags == 0:
                return False, None
            sequence_number = int.from_bytes(payload[:4], "big", signed=True)
            audio_chunk = payload[8:]
            if buffer is not None:
                buffer.write(audio_chunk)
            return sequence_number < 0, audio_chunk
        elif message_type == 0xf:
            code = int.from_bytes(payload[:4], "big", signed=False)
            error_msg = payload[8:]
            if (res[2] & 0x0f) == 1:
                error_msg = gzip.decompress(error_msg)
            err_str = "Volc TTS Error " + str(code) + ": " + error_msg.decode('utf-8')
            logger.error(err_str)
            raise Exception(err_str)
        return True, None

    async def generate_speech(
        self,
        text: str,
        stream: bool = False
    ) -> Union[bytes, AsyncGenerator[bytes, None]]:
        """Generate speech from text using the Volc TTS API.

        Args:
            text: The text to synthesize.
            stream: Whether to stream audio chunks.

        Returns:
            Complete audio bytes when ``stream`` is False, otherwise an async
            generator yielding audio chunks.
        """
        request = self._prepare_request(text)
        headers = self.get_auth_headers()
        logger.info(f"Volc TTS request prepared, text_len={len(text)}, stream={stream}")
        if not stream:
            buffer = io.BytesIO()
            async with websockets.connect(self._config.api_url, additional_headers=headers, ping_interval=None) as ws:
                await ws.send(request)
                while True:
                    response = await ws.recv()
                    done, _ = self._parse_response(response, buffer)
                    if done:
                        break
            return buffer.getvalue()
        else:
            async def audio_generator():
                async with websockets.connect(self._config.api_url, additional_headers=headers,
                                              ping_interval=None) as ws:
                    await ws.send(request)
                    while True:
                        response = await ws.recv()
                        logger.info(f"Volc TTS raw response ({len(response)} bytes): {response[:50]!r}")
                        done, chunk = self._parse_response(response)
                        logger.info(f"Volc TTS parsed: done={done}, chunk_len={len(chunk) if chunk else 0}")
                        if chunk:
                            yield chunk
                        if done:
                            break
            return audio_generator()

    async def check_connectivity(self) -> bool:
        """Check whether the Volc TTS service is reachable.

        Returns:
            True if a short synthesis succeeds and produces audio, False on
            any exception or empty result.
        """
        try:
            logger.info("Volc TTS connectivity test started...")
            audio_data = await self.generate_speech("Hello", stream=False)
            is_success = self._is_tts_result_successful(audio_data)
            if is_success:
                logger.info("Volc TTS connectivity test successful")
            else:
                logger.error("Volc TTS connectivity test failed: empty or invalid audio data")
            return is_success
        except Exception as e:
            logger.error("Volc TTS connectivity test failed with exception: " + str(e))
            logger.error("Volc TTS connectivity test exception traceback: " + traceback.format_exc())
            return False

    async def invoke(self, request: TTSRequest) -> bytes:
        """Return the full synthesized audio bytes for ``request.text``."""
        return await self.generate_speech(request.text, stream=False)

    async def stream(self, request: TTSRequest) -> AsyncIterator[bytes]:
        """Yield audio chunks for ``request.text`` from the streaming API."""
        gen = await self.generate_speech(request.text, stream=True)
        async for chunk in gen:
            yield chunk

    async def health_check(self) -> bool:
        """Delegate to :meth:`check_connectivity`."""
        return await self.check_connectivity()

    def get_model_info(self) -> ModelInfo:
        """Return ``ModelInfo`` advertising audio + realtime capabilities."""
        return ModelInfo(
            model_id=self._context.model_name,
            display_name=self._context.display_name or "",
            provider=self.factory,
            capabilities={"audio": True, "realtime": True},
        )

