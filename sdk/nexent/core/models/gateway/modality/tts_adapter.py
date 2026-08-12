"""TTS (text-to-speech) adapter — protocol implementation sunk in.

The WebSocket text-to-speech protocols (Ali CosyVoice / Qwen Realtime JSON over
WS, and Volc proprietary binary frames) live directly in the adapters. The old
``ali_tts_model.py`` / ``volc_tts_model.py`` / ``tts_model.py`` (BaseTTSModel)
classes are deleted; the adapters ARE the implementation.

ModelEngine TTS is different: it is HTTP REST (text → Chat Completions →
base64 audio in the response content array → decode to bytes). Its ``_model``
is :class:`OpenAIModel` (kept — see §3.16 LLM exception); the audio↔base64
conversion lives in the adapter.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import gzip
import io
import json
import logging
import uuid
from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncGenerator, AsyncIterator, Dict, Optional, Union

import websockets

from ..base import ModelInfo, MultimodalAdapter
from ..context import ModelContext
from ..registry import register_adapter
from ..transport import HttpTransportMixin, WebSocketTransportMixin

# Default WebSocket connection timeouts (seconds)
DEFAULT_WS_OPEN_TIMEOUT = 60
DEFAULT_WS_CLOSE_TIMEOUT = 10

logger = logging.getLogger(__name__)


@dataclass
class TTSRequest:
    """TTS request: synthesize ``text`` to audio."""

    text: str
    stream: bool = False
    voice: Optional[str] = None
    speed_ratio: float = 1.0


class TTSAdapter(MultimodalAdapter):
    """TTS adapter root.

    Carries the shared TTS result-inspection helpers that previously lived on
    the deleted ``BaseTTSModel`` ABC, so concrete WS adapters inherit them.
    """

    modality = "tts"

    @abstractmethod
    async def invoke(self, request: TTSRequest) -> bytes:
        """Synthesize ``request.text`` → complete audio bytes (stream=False)."""

    @abstractmethod
    async def stream(self, request: TTSRequest) -> AsyncIterator[bytes]:
        """Stream audio chunks for ``request.text`` (stream=True)."""

    def _is_tts_result_successful(self, result: Any) -> bool:
        """Check if TTS result indicates a successful synthesis."""
        if isinstance(result, bytes):
            return len(result) > 0
        if isinstance(result, dict):
            if 'error' in result:
                return False
            return 'audio' in result or 'text' in result or 'message' in result
        return False

    def _extract_tts_error_message(self, result: Any) -> str:
        """Extract error message from TTS result."""
        if isinstance(result, dict):
            if 'error' in result:
                return str(result['error'])
            if 'message' in result:
                return str(result['message'])
        return f"Unknown error in result: {result}"


# ============================================================================
# Ali TTS — CosyVoice / Qwen Realtime (JSON over WebSocket)
# ============================================================================

class AliTTSError(Exception):
    """Exception raised when Ali TTS API returns an error."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)


# CosyVoice API default URL
COSYVOICE_API_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
# Qwen Realtime API default URL
QWEN_REALTIME_API_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"


class AliTTSConfig:
    """Configuration for Ali TTS model."""

    def __init__(
            self,
            api_key: str,
            model: str = "cosyvoice-v2",
            voice: str = None,
            speech_rate: float = 1.0,
            pitch_rate: float = 1.0,
            volume: float = 50.0,
            ws_url: Optional[str] = None,
            format: str = "mp3",
            sample_rate: int = 16000,
            workspace_id: Optional[str] = None
    ):
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.speech_rate = speech_rate
        self.pitch_rate = pitch_rate
        self.volume = volume
        self.ws_url = ws_url
        self.format = format
        self.sample_rate = sample_rate
        self.workspace_id = workspace_id

    def is_realtime_api(self) -> bool:
        """Check if URL is for Qwen Realtime API."""
        return "/realtime" in (self.ws_url or "")

    def get_api_url(self) -> str:
        """Get the WebSocket API URL based on the model."""
        if self.ws_url:
            return self.ws_url
        if self.is_realtime_api() or "qwen" in self.model.lower():
            return QWEN_REALTIME_API_URL
        return COSYVOICE_API_URL


@register_adapter("ali", "tts")
class AliTTSAdapter(TTSAdapter, WebSocketTransportMixin):
    """Ali TTS — CosyVoice / Qwen Realtime, JSON over WebSocket.

    Both sub-protocols (CosyVoice run/continue/finish-task and Qwen Realtime
    session.update / input_text_buffer / response.audio.delta) live here.
    """

    factory = "ali"

    def __init__(self, context: ModelContext) -> None:
        MultimodalAdapter.__init__(self, context)
        WebSocketTransportMixin.__init__(
            self,
            ws_url=context.extra.get("ws_url"),
            auth_headers=context.extra.get("auth_headers"),
        )
        extras = context.extra
        self._config = AliTTSConfig(
            api_key=context.api_key,
            model=context.model_name,
            voice=context.voice or "Cherry",
            speech_rate=context.speed_ratio,
            ws_url=self._ws_url,
            format=extras.get("format", "mp3"),
            sample_rate=extras.get("sample_rate", 16000),
        )
        self._audio_file_path = context.audio_file_path
        self._is_realtime = self._config.is_realtime_api() or "qwen" in self._config.model.lower()

    def get_websocket_url(self) -> str:
        """Get the WebSocket URL for the TTS service."""
        base_url = self._config.get_api_url()
        if self._is_realtime:
            separator = "&" if "?" in base_url else "?"
            return f"{base_url}{separator}model={self._config.model}"
        return base_url

    def get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers for the WebSocket connection."""
        return {"Authorization": f"Bearer {self._config.api_key}"}

    async def generate_speech(
            self,
            text: str,
            stream: bool = False
    ) -> Union[bytes, AsyncGenerator[bytes, None]]:
        """Generate speech from text using the appropriate API."""
        ws_url = self.get_websocket_url()
        headers = self.get_auth_headers()
        logger.info(f"Connecting to Ali TTS service at {ws_url}")
        logger.info(f"Using model: {self._config.model}, voice: {self._config.voice}")
        logger.info(f"API type: {'Qwen Realtime' if self._is_realtime else 'CosyVoice'}")

        if self._is_realtime:
            if stream:
                return self._generate_qwen_realtime_streaming(text, ws_url, headers)
            return await self._generate_qwen_realtime_non_streaming(text, ws_url, headers)
        else:
            if stream:
                return self._generate_cosyvoice_streaming(text, ws_url, headers)
            return await self._generate_cosyvoice_non_streaming(text, ws_url, headers)

    # ==================== CosyVoice API Implementation ====================

    def _cosyvoice_generate_task_id(self) -> str:
        """Generate a unique task ID for CosyVoice API."""
        return uuid.uuid4().hex

    def _cosyvoice_construct_run_task_request(self, task_id: str) -> Dict[str, Any]:
        """Construct the run-task request for CosyVoice API."""
        return {
            "header": {
                "action": "run-task",
                "task_id": task_id,
                "streaming": "duplex"
            },
            "payload": {
                "task_group": "audio",
                "task": "tts",
                "function": "SpeechSynthesizer",
                "model": self._config.model,
                "parameters": {
                    "text_type": "PlainText",
                    "voice": self._config.voice,
                    "format": self._config.format,
                    "sample_rate": self._config.sample_rate,
                    "volume": int(self._config.volume),
                    "rate": self._config.speech_rate,
                    "pitch": self._config.pitch_rate,
                    "enable_ssml": False
                },
                "input": {}
            }
        }

    def _cosyvoice_construct_continue_request(self, task_id: str, text: str) -> Dict[str, Any]:
        """Construct the continue-task request for CosyVoice API."""
        return {
            "header": {
                "action": "continue-task",
                "task_id": task_id,
                "streaming": "duplex"
            },
            "payload": {
                "input": {"text": text}
            }
        }

    def _cosyvoice_construct_finish_request(self, task_id: str) -> Dict[str, Any]:
        """Construct the finish-task request for CosyVoice API."""
        return {
            "header": {
                "action": "finish-task",
                "task_id": task_id,
                "streaming": "duplex"
            },
            "payload": {"input": {}}
        }

    def _cosyvoice_parse_event(self, message: str) -> Dict[str, Any]:
        """Parse a JSON event from CosyVoice API."""
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse JSON: {message[:100]}")
            return {"type": "unknown"}

        header = data.get("header", {})
        event_type = header.get("event", "")
        result: Dict[str, Any] = {"type": event_type, "task_id": header.get("task_id")}

        if event_type == "task-failed":
            result["error_code"] = header.get("error_code")
            result["error_message"] = header.get("error_message")
        elif event_type == "task-finished":
            payload = data.get("payload", {})
            usage = payload.get("usage", {})
            result["characters"] = usage.get("characters")

        return result

    async def _cosyvoice_wait_for_task_started(self, ws) -> bool:
        """Wait for task_started event from CosyVoice API."""
        while True:
            message = await asyncio.wait_for(ws.recv(), timeout=30)
            if isinstance(message, bytes):
                continue
            event = self._cosyvoice_parse_event(message)
            logger.info(f"CosyVoice received event: {event.get('type')}")

            if event.get("type") == "task-started":
                return True
            if event.get("type") == "task-failed":
                raise AliTTSError(f"CosyVoice task failed: {event.get('error_message', 'Unknown error')}")
        return False

    async def _cosyvoice_receive_audio(
            self,
            ws,
            buffer: Optional[bytearray] = None,
            yield_chunks: bool = False
    ) -> AsyncGenerator[bytes, None]:
        """Receive audio from CosyVoice API."""
        while True:
            try:
                message = await asyncio.wait_for(ws.recv(), timeout=60)
                if isinstance(message, bytes):
                    if buffer is not None:
                        buffer.extend(message)
                    if yield_chunks:
                        yield message
                    continue

                event = self._cosyvoice_parse_event(message)
                event_type = event.get("type")
                logger.info(f"CosyVoice received event: {event_type}")

                if event_type == "task-failed":
                    raise AliTTSError(f"CosyVoice task failed: {event.get('error_message', 'Unknown error')}")
                if event_type == "task-finished":
                    break

            except asyncio.TimeoutError:
                logger.warning("Timeout waiting for CosyVoice task-finished event")
                break

    async def _generate_cosyvoice_non_streaming(self, text: str, ws_url: str, headers: Dict[str, str]) -> bytes:
        """Non-streaming speech generation using CosyVoice API."""
        buffer = bytearray()
        task_id = self._cosyvoice_generate_task_id()

        try:
            async with websockets.connect(ws_url, additional_headers=headers, ping_interval=None,
                                          open_timeout=DEFAULT_WS_OPEN_TIMEOUT,
                                          close_timeout=DEFAULT_WS_CLOSE_TIMEOUT) as ws:
                request = self._cosyvoice_construct_run_task_request(task_id)
                await ws.send(json.dumps(request))
                logger.info(f"Sent CosyVoice run-task request: task_id={task_id}")

                await self._cosyvoice_wait_for_task_started(ws)

                await ws.send(json.dumps(self._cosyvoice_construct_continue_request(task_id, text)))
                logger.info(f"Sent CosyVoice continue-task with text: {text[:50]}...")

                await ws.send(json.dumps(self._cosyvoice_construct_finish_request(task_id)))
                logger.info("Sent CosyVoice finish-task request")

                # Consume audio chunks to accumulate in buffer
                async for _ in self._cosyvoice_receive_audio(ws, buffer=buffer):
                    pass  # Audio is accumulated in buffer

        except AliTTSError:
            raise
        except Exception as e:
            logger.error(f"CosyVoice TTS error: {str(e)}")
            raise

        if len(buffer) == 0:
            logger.warning("No audio data received from CosyVoice")
        return bytes(buffer)

    async def _generate_cosyvoice_streaming(self, text: str, ws_url: str, headers: Dict[str, str]) -> AsyncGenerator[
        bytes, None]:
        """Streaming speech generation using CosyVoice API."""
        task_id = self._cosyvoice_generate_task_id()

        try:
            async with websockets.connect(ws_url, additional_headers=headers, ping_interval=None,
                                          open_timeout=DEFAULT_WS_OPEN_TIMEOUT,
                                          close_timeout=DEFAULT_WS_CLOSE_TIMEOUT) as ws:
                await ws.send(json.dumps(self._cosyvoice_construct_run_task_request(task_id)))
                logger.info(f"Sent CosyVoice run-task request: task_id={task_id}")

                await self._cosyvoice_wait_for_task_started(ws)

                await ws.send(json.dumps(self._cosyvoice_construct_continue_request(task_id, text)))
                logger.info(f"Sent CosyVoice continue-task with text: {text[:50]}...")

                await ws.send(json.dumps(self._cosyvoice_construct_finish_request(task_id)))
                logger.info("Sent CosyVoice finish-task request")

                async for chunk in self._cosyvoice_receive_audio(ws, yield_chunks=True):
                    yield chunk

        except AliTTSError:
            raise
        except Exception as e:
            logger.error(f"CosyVoice TTS streaming error: {str(e)}")
            raise

    # ==================== Qwen Realtime API Implementation ====================

    def _qwen_generate_event_id(self) -> str:
        """Generate a unique event ID for Qwen Realtime API."""
        return f"event_{uuid.uuid4().hex[:16]}"

    def _qwen_construct_session_update(self) -> Dict[str, Any]:
        """Construct session.update request for Qwen Realtime API."""
        # Use default voice if not specified
        voice = self._config.voice or "Cherry"
        return {
            "event_id": self._qwen_generate_event_id(),
            "type": "session.update",
            "session": {
                "voice": voice,
                "mode": "server_commit",
                "language_type": "Auto",
                "response_format": self._qwen_format_to_response_format(self._config.format),
                "sample_rate": self._config.sample_rate,
                "speech_rate": self._config.speech_rate,
                "volume": int(self._config.volume)
            }
        }

    def _qwen_format_to_response_format(self, format_str: str) -> str:
        """Convert format to Qwen Realtime response_format."""
        format_map = {"mp3": "mp3", "pcm": "pcm", "wav": "wav", "opus": "opus"}
        return format_map.get(format_str.lower(), "pcm")

    def _qwen_construct_text_append(self, text: str) -> Dict[str, Any]:
        """Construct input_text_buffer.append request for Qwen Realtime API."""
        return {
            "event_id": self._qwen_generate_event_id(),
            "type": "input_text_buffer.append",
            "text": text
        }

    def _qwen_construct_text_commit(self) -> Dict[str, Any]:
        """Construct input_text_buffer.commit request for Qwen Realtime API."""
        return {
            "event_id": self._qwen_generate_event_id(),
            "type": "input_text_buffer.commit"
        }

    def _qwen_construct_session_finish(self) -> Dict[str, Any]:
        """Construct session.finish request for Qwen Realtime API."""
        return {
            "event_id": self._qwen_generate_event_id(),
            "type": "session.finish"
        }

    def _qwen_parse_event(self, message: str) -> Dict[str, Any]:
        """Parse a JSON event from Qwen Realtime API."""
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse Qwen event JSON: {message[:100]}")
            return {"type": "unknown"}

        event_type = data.get("type", "")
        result: Dict[str, Any] = {"type": event_type, "raw": data}

        if event_type == "error":
            error = data.get("error", {})
            result["error_code"] = error.get("code")
            result["error_message"] = error.get("message")

        return result

    async def _qwen_wait_for_session_created(self, ws) -> bool:
        """Wait for session.created event from Qwen Realtime API."""
        while True:
            message = await asyncio.wait_for(ws.recv(), timeout=30)
            if isinstance(message, bytes):
                continue
            event = self._qwen_parse_event(message)
            logger.info(f"Qwen Realtime received event: {event.get('type')}")

            if event.get("type") == "session.created":
                return True
            if event.get("type") == "error":
                raise AliTTSError(f"Qwen Realtime session error: {event.get('error_message', 'Unknown error')}")
        return False

    def _qwen_is_terminal_event(self, event_type: str) -> bool:
        """Check if event type indicates the session is done."""
        return event_type in ("response.audio.done", "session.finished")

    async def _qwen_wait_for_response_created(self, ws) -> bool:
        """Wait for response.created event before collecting audio."""
        while True:
            message = await asyncio.wait_for(ws.recv(), timeout=60)
            if isinstance(message, bytes):
                continue
            event = self._qwen_parse_event(message)
            event_type = event.get("type")
            logger.info(f"Qwen Realtime received event: {event_type}")

            if event_type == "error":
                raise AliTTSError(f"Qwen Realtime error: {event.get('error_message', 'Unknown error')}")
            if event_type == "response.created":
                logger.info("Response created, audio synthesis started")
                return True
            if event_type == "session.finished":
                logger.warning("Session finished before audio started")
                return False
        return False

    def _qwen_handle_audio_delta(self, event: Dict[str, Any], buffer: Optional[bytearray], yield_chunks: bool) -> \
            Optional[bytes]:
        """Handle response.audio.delta event and return audio chunk."""
        delta = event.get("raw", {}).get("delta", "")
        if not delta:
            return None
        audio_data = base64.b64decode(delta)
        if buffer is not None:
            buffer.extend(audio_data)
        return audio_data if yield_chunks else None

    async def _qwen_receive_audio(
            self,
            ws,
            buffer: Optional[bytearray] = None,
            yield_chunks: bool = False
    ) -> AsyncGenerator[bytes, None]:
        """Receive audio from Qwen Realtime API."""
        audio_done = False
        while not audio_done:
            try:
                message = await asyncio.wait_for(ws.recv(), timeout=60)
                if isinstance(message, bytes):
                    if buffer is not None:
                        buffer.extend(message)
                    if yield_chunks:
                        yield message
                    continue

                event = self._qwen_parse_event(message)
                event_type = event.get("type")
                logger.info(f"Qwen Realtime received event: {event_type}")

                if event_type == "error":
                    raise AliTTSError(f"Qwen Realtime error: {event.get('error_message', 'Unknown error')}")

                if event_type == "response.created":
                    logger.info("Response created, audio synthesis started")
                    continue

                if event_type == "response.audio.delta":
                    chunk = self._qwen_handle_audio_delta(event, buffer, yield_chunks)
                    if chunk:
                        yield chunk

                if self._qwen_is_terminal_event(event_type):
                    audio_done = True

            except asyncio.TimeoutError:
                logger.warning("Timeout waiting for Qwen Realtime response")
                break

    async def _generate_qwen_realtime_non_streaming(self, text: str, ws_url: str, headers: Dict[str, str]) -> bytes:
        """Non-streaming speech generation using Qwen Realtime API."""
        buffer = bytearray()

        try:
            async with websockets.connect(ws_url, additional_headers=headers, ping_interval=None,
                                          open_timeout=DEFAULT_WS_OPEN_TIMEOUT,
                                          close_timeout=DEFAULT_WS_CLOSE_TIMEOUT) as ws:
                # Wait for session.created
                await self._qwen_wait_for_session_created(ws)
                logger.info("Qwen Realtime session created")

                # Send session update
                await ws.send(json.dumps(self._qwen_construct_session_update()))
                voice = self._config.voice or "Cherry"
                logger.info(f"Sent Qwen Realtime session.update with voice={voice}")

                # Send text
                await ws.send(json.dumps(self._qwen_construct_text_append(text)))
                logger.info(f"Sent Qwen Realtime text: {text[:50]}...")

                # Commit and trigger synthesis
                await ws.send(json.dumps(self._qwen_construct_text_commit()))
                logger.info("Sent Qwen Realtime text commit")

                # Wait for response.created before finishing session
                await self._qwen_wait_for_response_created(ws)

                # Finish session
                await ws.send(json.dumps(self._qwen_construct_session_finish()))
                logger.info("Sent Qwen Realtime session.finish")

                # Receive audio chunks to accumulate in buffer
                async for _ in self._qwen_receive_audio(ws, buffer=buffer):
                    pass  # Audio is accumulated in buffer

        except AliTTSError:
            raise
        except Exception as e:
            logger.error(f"Qwen Realtime TTS error: {str(e)}")
            raise

        if len(buffer) == 0:
            logger.warning("No audio data received from Qwen Realtime")
        return bytes(buffer)

    async def _generate_qwen_realtime_streaming(self, text: str, ws_url: str, headers: Dict[str, str]) -> \
            AsyncGenerator[bytes, None]:
        """Streaming speech generation using Qwen Realtime API."""
        try:
            async with websockets.connect(ws_url, additional_headers=headers, ping_interval=None,
                                          open_timeout=DEFAULT_WS_OPEN_TIMEOUT,
                                          close_timeout=DEFAULT_WS_CLOSE_TIMEOUT) as ws:
                # Wait for session.created
                await self._qwen_wait_for_session_created(ws)
                logger.info("Qwen Realtime session created")

                # Send session update
                await ws.send(json.dumps(self._qwen_construct_session_update()))
                voice = self._config.voice or "Cherry"
                logger.info(f"Sent Qwen Realtime session.update with voice={voice}")

                # Send text
                await ws.send(json.dumps(self._qwen_construct_text_append(text)))
                logger.info(f"Sent Qwen Realtime text: {text[:50]}...")

                # Commit and trigger synthesis
                await ws.send(json.dumps(self._qwen_construct_text_commit()))
                logger.info("Sent Qwen Realtime text commit")

                # Wait for response.created before finishing session
                await self._qwen_wait_for_response_created(ws)

                # Finish session
                await ws.send(json.dumps(self._qwen_construct_session_finish()))
                logger.info("Sent Qwen Realtime session.finish")

                # Receive audio
                async for chunk in self._qwen_receive_audio(ws, yield_chunks=True):
                    yield chunk

        except AliTTSError:
            raise
        except Exception as e:
            logger.error(f"Qwen Realtime TTS streaming error: {str(e)}")
            raise

    # ==================== Connectivity Check ====================

    async def check_connectivity(self) -> bool:
        """Test if the connection to the remote TTS service is normal."""
        api_type = "Qwen Realtime" if self._is_realtime else "CosyVoice"
        try:
            logger.info(f"Ali TTS connectivity test started with {api_type}")
            logger.info(f"model={self._config.model}, voice={self._config.voice}")
            audio_data = await self.generate_speech("Hello", stream=False)
            is_success = self._is_tts_result_successful(audio_data)
            if is_success:
                logger.info("Ali TTS connectivity test successful")
            else:
                logger.error("Ali TTS connectivity test failed: empty audio data")
            return is_success
        except AliTTSError as e:
            error_msg = str(e)
            logger.error(f"Ali TTS connectivity test failed: {error_msg}")
            return False
        except Exception as e:
            logger.error(f"Ali TTS connectivity test failed with exception: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    async def invoke(self, request: TTSRequest) -> bytes:
        return await self.generate_speech(request.text, stream=False)

    async def stream(self, request: TTSRequest) -> AsyncIterator[bytes]:
        gen = await self.generate_speech(request.text, stream=True)
        async for chunk in gen:
            yield chunk

    async def health_check(self) -> bool:
        return await self.check_connectivity()

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            model_id=self._context.model_name,
            display_name=self._context.display_name or "",
            provider=self.factory,
            capabilities={"audio": True, "realtime": True},
        )


# ============================================================================
# Volc TTS — proprietary binary-frame WebSocket
# ============================================================================

@dataclass
class VolcTTSConfig:
    """Configuration for Volcano Engine TTS model."""
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
        return self.ws_url


@register_adapter("volc", "tts")
class VolcTTSAdapter(TTSAdapter, WebSocketTransportMixin):
    """Volc TTS — proprietary binary-frame WS.

    The full binary protocol (DEFAULT_HEADER framing, gzip-compressed JSON
    payload, response parsing for audio-only / error message types) lives here.
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
        return self._config.api_url

    def get_auth_headers(self) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer; {self._config.token}",
            "X-Api-App-Id": self._config.appid,
            "X-Api-Access-Key": self._config.token,
            "X-Api-Resource-Id": self._config.resource_id
        }
        return headers

    def _prepare_request(self, text: str, operation: str = "submit") -> bytes:
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
            import traceback
            logger.error("Volc TTS connectivity test exception traceback: " + traceback.format_exc())
            return False

    async def invoke(self, request: TTSRequest) -> bytes:
        return await self.generate_speech(request.text, stream=False)

    async def stream(self, request: TTSRequest) -> AsyncIterator[bytes]:
        gen = await self.generate_speech(request.text, stream=True)
        async for chunk in gen:
            yield chunk

    async def health_check(self) -> bool:
        return await self.check_connectivity()

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            model_id=self._context.model_name,
            display_name=self._context.display_name or "",
            provider=self.factory,
            capabilities={"audio": True, "realtime": True},
        )


# ============================================================================
# ModelEngine TTS — HTTP REST, text → Chat Completions → base64 audio in the
# response content array → decoded to bytes. _model is OpenAIModel (kept per
# §3.16 LLM exception); audio↔base64 conversion lives in the adapter.
# ============================================================================

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
        self._model: Any = None  # wrapped OpenAIModel, built lazily

    def _build_model(self) -> None:
        from ...openai_llm import OpenAIModel

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
        if self._model is None:
            self._build_model()
        return await asyncio.to_thread(self._model.check_connectivity)

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            model_id=self._context.model_name,
            display_name=self._context.display_name or "",
            provider=self.factory,
            capabilities={"audio": True, "realtime": False},
        )
