"""
Ali TTS model implementation supporting both CosyVoice and Qwen Realtime APIs.
"""
import asyncio
import base64
import json
import logging
import uuid
from typing import Any, AsyncGenerator, Dict, Optional, Union

import websockets

# Default WebSocket connection timeout (seconds)
DEFAULT_WS_OPEN_TIMEOUT = 60
DEFAULT_WS_CLOSE_TIMEOUT = 10

from .tts_model import BaseTTSModel

logger = logging.getLogger(__name__)


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


class AliTTSModel(BaseTTSModel):
    """Ali TTS model implementation supporting CosyVoice and Qwen Realtime APIs."""

    def __init__(self, config: AliTTSConfig, audio_file_path: Optional[str] = None):
        super().__init__(audio_file_path)
        self.config = config
        self._is_realtime = config.is_realtime_api() or "qwen" in config.model.lower()

    def get_websocket_url(self) -> str:
        """Get the WebSocket URL for the TTS service."""
        base_url = self.config.get_api_url()
        if self._is_realtime:
            separator = "&" if "?" in base_url else "?"
            return f"{base_url}{separator}model={self.config.model}"
        return base_url

    def get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers for the WebSocket connection."""
        return {"Authorization": f"Bearer {self.config.api_key}"}

    async def generate_speech(
            self,
            text: str,
            stream: bool = False
    ) -> Union[bytes, AsyncGenerator[bytes, None]]:
        """
        Generate speech from text using the appropriate API.

        Args:
            text: Input text to synthesize
            stream: If True, return an async generator of audio chunks.
                   If False, return complete audio bytes.

        Returns:
            Audio data either as complete bytes or streaming chunks
        """
        ws_url = self.get_websocket_url()
        headers = self.get_auth_headers()
        logger.info(f"Connecting to Ali TTS service at {ws_url}")
        logger.info(f"Using model: {self.config.model}, voice: {self.config.voice}")
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
                "model": self.config.model,
                "parameters": {
                    "text_type": "PlainText",
                    "voice": self.config.voice,
                    "format": self.config.format,
                    "sample_rate": self.config.sample_rate,
                    "volume": int(self.config.volume),
                    "rate": self.config.speech_rate,
                    "pitch": self.config.pitch_rate,
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
        voice = self.config.voice or "Cherry"
        return {
            "event_id": self._qwen_generate_event_id(),
            "type": "session.update",
            "session": {
                "voice": voice,
                "mode": "server_commit",
                "language_type": "Auto",
                "response_format": self._qwen_format_to_response_format(self.config.format),
                "sample_rate": self.config.sample_rate,
                "speech_rate": self.config.speech_rate,
                "volume": int(self.config.volume)
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
                voice = self.config.voice or "Cherry"
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
                voice = self.config.voice or "Cherry"
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
        """
        Test if the connection to the remote TTS service is normal.

        Returns:
            True if connection successful, False otherwise
        """
        api_type = "Qwen Realtime" if self._is_realtime else "CosyVoice"
        try:
            logger.info(f"Ali TTS connectivity test started with {api_type}")
            logger.info(f"model={self.config.model}, voice={self.config.voice}")
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

