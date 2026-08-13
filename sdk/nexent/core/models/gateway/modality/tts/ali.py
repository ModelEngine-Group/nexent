"""Ali TTS adapter (CosyVoice / Qwen Realtime, JSON over WebSocket)."""

from __future__ import annotations

import asyncio
import base64
import json
import traceback
import uuid
import websockets
import logging
from typing import Any, AsyncGenerator, AsyncIterator, Dict, Optional, Union

from ...multimodal_adapter import MultimodalAdapter, ModelInfo
from ...model_context import ModelContext
from ...registry import register_adapter
from ...transport import WebSocketTransportMixin
from .base import TTSAdapter, TTSRequest

logger = logging.getLogger(__name__)

# Default WebSocket connection timeouts (seconds)
DEFAULT_WS_OPEN_TIMEOUT = 60
DEFAULT_WS_CLOSE_TIMEOUT = 10

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
        """Initialize Ali TTS configuration.

        Args:
            api_key: DashScope API key (Bearer auth on the WS connection).
            model: CosyVoice / Qwen Realtime model id.
            voice: Voice id; ``None`` lets the provider default apply.
            speech_rate: Speech rate multiplier (1.0 = normal).
            pitch_rate: Pitch multiplier (1.0 = normal).
            volume: Output volume (0–100).
            ws_url: Explicit WS URL override; ``None`` selects the default
                based on the model (Qwen Realtime vs CosyVoice).
            format: Audio format (``"mp3"``, ``"wav"`` ...).
            sample_rate: Output sample rate in Hz.
            workspace_id: Optional DashScope workspace id.
        """
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
        """Check whether the configured URL points to the Qwen Realtime API.

        Returns:
            True if the URL contains a ``/realtime`` path segment.
        """
        return "/realtime" in (self.ws_url or "")

    def get_api_url(self) -> str:
        """Get the WebSocket API URL based on the model.

        Returns:
            The explicitly configured ``ws_url``, or the default URL
            matching the selected API (Qwen Realtime or CosyVoice).
        """
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

    Attributes:
        modality: ``"tts"`` (inherited).
        factory: ``"ali"``.
        _config: The :class:`AliTTSConfig` built from the construction context.
        _audio_file_path: Optional path for persisted audio output.
        _is_realtime: True when the Qwen Realtime sub-protocol is selected.
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
        """Get the WebSocket URL for the TTS service.

        Returns:
            The base URL, with the model appended as a query parameter
            for the Qwen Realtime API.
        """
        base_url = self._config.get_api_url()
        if self._is_realtime:
            separator = "&" if "?" in base_url else "?"
            return f"{base_url}{separator}model={self._config.model}"
        return base_url

    def get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers for the WebSocket connection.

        Returns:
            A dict with the Bearer Authorization header.
        """
        return {"Authorization": f"Bearer {self._config.api_key}"}

    async def generate_speech(
            self,
            text: str,
            stream: bool = False
    ) -> Union[bytes, AsyncGenerator[bytes, None]]:
        """Generate speech from text using the appropriate API.

        Dispatches to the Qwen Realtime or CosyVoice sub-protocol based on
        the configured model and URL, in streaming or non-streaming mode.

        Args:
            text: The text to synthesize.
            stream: Whether to stream audio chunks.

        Returns:
            Complete audio bytes when ``stream`` is False, otherwise an
            async generator yielding audio chunks.
        """
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
        """Generate a unique task ID for the CosyVoice API.

        Returns:
            A random hex string usable as a task ID.
        """
        return uuid.uuid4().hex

    def _cosyvoice_construct_run_task_request(self, task_id: str) -> Dict[str, Any]:
        """Construct the run-task request for the CosyVoice API.

        Args:
            task_id: The task ID to associate with the request.

        Returns:
            The run-task request payload.
        """
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
        """Construct the continue-task request for the CosyVoice API.

        Args:
            task_id: The task ID to associate with the request.
            text: The text to continue synthesizing.

        Returns:
            The continue-task request payload.
        """
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
        """Construct the finish-task request for the CosyVoice API.

        Args:
            task_id: The task ID to associate with the request.

        Returns:
            The finish-task request payload.
        """
        return {
            "header": {
                "action": "finish-task",
                "task_id": task_id,
                "streaming": "duplex"
            },
            "payload": {"input": {}}
        }

    def _cosyvoice_parse_event(self, message: str) -> Dict[str, Any]:
        """Parse a JSON event from the CosyVoice API.

        Args:
            message: The raw JSON message received from the server.

        Returns:
            A dict with the event ``type`` and relevant fields.
        """
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
        """Wait for the task_started event from the CosyVoice API.

        Args:
            ws: The open WebSocket connection.

        Returns:
            True once the task has started.

        Raises:
            AliTTSError: If the task fails before starting.
        """
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
        """Receive audio from the CosyVoice API.

        Accumulates audio in ``buffer`` when given, and optionally yields
        chunks as they arrive. Ends when the task-finished event is received.

        Args:
            ws: The open WebSocket connection.
            buffer: Optional buffer to accumulate audio into.
            yield_chunks: Whether to yield audio chunks as they arrive.

        Yields:
            Audio chunks when ``yield_chunks`` is True.

        Raises:
            AliTTSError: If the task fails while receiving audio.
        """
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
        """Synthesize non-streaming speech using the CosyVoice API.

        Args:
            text: The text to synthesize.
            ws_url: The WebSocket URL to connect to.
            headers: The authentication headers to send.

        Returns:
            The complete audio as bytes.
        """
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
        """Synthesize streaming speech using the CosyVoice API.

        Args:
            text: The text to synthesize.
            ws_url: The WebSocket URL to connect to.
            headers: The authentication headers to send.

        Yields:
            Audio chunks as they are received.
        """
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
        """Generate a unique event ID for the Qwen Realtime API.

        Returns:
            A unique event ID string.
        """
        return f"event_{uuid.uuid4().hex[:16]}"

    def _qwen_construct_session_update(self) -> Dict[str, Any]:
        """Construct the session.update request for the Qwen Realtime API.

        Returns:
            The session.update request payload.
        """
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
        """Convert a format name to a Qwen Realtime response_format.

        Args:
            format_str: The encoding name (e.g. ``mp3``, ``pcm``).

        Returns:
            The matching response_format, defaulting to ``pcm``.
        """
        format_map = {"mp3": "mp3", "pcm": "pcm", "wav": "wav", "opus": "opus"}
        return format_map.get(format_str.lower(), "pcm")

    def _qwen_construct_text_append(self, text: str) -> Dict[str, Any]:
        """Construct the input_text_buffer.append request for the Qwen Realtime API.

        Args:
            text: The text to append to the input buffer.

        Returns:
            The input_text_buffer.append request payload.
        """
        return {
            "event_id": self._qwen_generate_event_id(),
            "type": "input_text_buffer.append",
            "text": text
        }

    def _qwen_construct_text_commit(self) -> Dict[str, Any]:
        """Construct the input_text_buffer.commit request for the Qwen Realtime API.

        Returns:
            The input_text_buffer.commit request payload.
        """
        return {
            "event_id": self._qwen_generate_event_id(),
            "type": "input_text_buffer.commit"
        }

    def _qwen_construct_session_finish(self) -> Dict[str, Any]:
        """Construct the session.finish request for the Qwen Realtime API.

        Returns:
            The session.finish request payload.
        """
        return {
            "event_id": self._qwen_generate_event_id(),
            "type": "session.finish"
        }

    def _qwen_parse_event(self, message: str) -> Dict[str, Any]:
        """Parse a JSON event from the Qwen Realtime API.

        Args:
            message: The raw JSON message received from the server.

        Returns:
            A dict with the event ``type`` and relevant fields.
        """
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
        """Wait for the session.created event from the Qwen Realtime API.

        Args:
            ws: The open WebSocket connection.

        Returns:
            True once the session is created.

        Raises:
            AliTTSError: If an error event is received while waiting.
        """
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
        """Check whether an event type indicates the session is done.

        Args:
            event_type: The event type to check.

        Returns:
            True for the terminal audio/session events.
        """
        return event_type in ("response.audio.done", "session.finished")

    async def _qwen_wait_for_response_created(self, ws) -> bool:
        """Wait for the response.created event before collecting audio.

        Args:
            ws: The open WebSocket connection.

        Returns:
            True if the response was created, False if the session finished first.

        Raises:
            AliTTSError: If an error event is received while waiting.
        """
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
        """Handle a response.audio.delta event and return the audio chunk.

        Args:
            event: The parsed Qwen Realtime event dict.
            buffer: Optional buffer to accumulate audio into.
            yield_chunks: Whether to return the decoded chunk.

        Returns:
            The decoded audio bytes when ``yield_chunks`` is True, else None.
        """
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
        """Receive audio from the Qwen Realtime API.

        Accumulates audio in ``buffer`` when given, and optionally yields
        chunks as they arrive. Ends when a terminal event is received.

        Args:
            ws: The open WebSocket connection.
            buffer: Optional buffer to accumulate audio into.
            yield_chunks: Whether to yield audio chunks as they arrive.

        Yields:
            Audio chunks when ``yield_chunks`` is True.

        Raises:
            AliTTSError: If an error event is received while receiving audio.
        """
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
        """Synthesize non-streaming speech using the Qwen Realtime API.

        Args:
            text: The text to synthesize.
            ws_url: The WebSocket URL to connect to.
            headers: The authentication headers to send.

        Returns:
            The complete audio as bytes.
        """
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
        """Synthesize streaming speech using the Qwen Realtime API.

        Args:
            text: The text to synthesize.
            ws_url: The WebSocket URL to connect to.
            headers: The authentication headers to send.

        Yields:
            Audio chunks as they are received.
        """
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
        """Test whether the connection to the remote TTS service is normal.

        Returns:
            True if a short synthesis succeeds and produces audio.
        """
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
            logger.error(f"Traceback: {traceback.format_exc()}")
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

