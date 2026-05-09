"""
Ali TTS model implementation using Qwen Realtime TTS API.
"""
import asyncio
import base64
import json
import logging
import uuid
from typing import Any, AsyncGenerator, Dict, Optional, Union

import websockets

from .base_tts_model import BaseTTSModel

logger = logging.getLogger(__name__)


class AliTTSError(Exception):
    """Exception raised when Ali TTS API returns an error."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)


# Qwen Realtime API default URL
QWEN_REALTIME_API_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"


class AliTTSConfig:
    """Configuration for Ali TTS model."""

    def __init__(
        self,
        api_key: str,
        model: str = "qwen3-tts-flash",
        voice: str = "Cherry",
        speech_rate: float = 1.0,
        pitch_rate: float = 1.0,
        volume: float = 50.0,
        ws_url: Optional[str] = None,
        format: str = "pcm",
        sample_rate: int = 24000,
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

    def get_api_url(self) -> str:
        """Get the WebSocket API URL."""
        if self.ws_url:
            return self.ws_url
        return QWEN_REALTIME_API_URL


class AliTTSModel(BaseTTSModel):
    """Ali TTS model implementation using Qwen Realtime TTS API."""

    def __init__(self, config: AliTTSConfig, audio_file_path: Optional[str] = None):
        super().__init__(audio_file_path)
        self.config = config

    def get_websocket_url(self) -> str:
        """Get the WebSocket URL with model query parameter."""
        base_url = self.config.get_api_url()
        separator = "&" if "?" in base_url else "?"
        return f"{base_url}{separator}model={self.config.model}"

    def get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers for the WebSocket connection."""
        return {"Authorization": f"Bearer {self.config.api_key}"}

    async def generate_speech(
        self,
        text: str,
        stream: bool = False
    ) -> Union[bytes, AsyncGenerator[bytes, None]]:
        """
        Generate speech from text using Qwen Realtime TTS API.

        Args:
            text: Input text to synthesize.
            stream: If True, return an async generator of audio chunks.
                   If False, return complete audio bytes.

        Returns:
            Audio data either as complete bytes or streaming chunks.
        """
        ws_url = self.get_websocket_url()
        headers = self.get_auth_headers()
        logger.info(f"Connecting to Qwen Realtime TTS at {ws_url}")
        logger.info(f"Using model: {self.config.model}, voice: {self.config.voice}")

        if stream:
            return self._generate_streaming(ws_url, headers, text)
        return await self._generate_non_streaming(ws_url, headers, text)

    def _generate_event_id(self) -> str:
        """Generate a unique event ID."""
        return f"event_{uuid.uuid4().hex[:16]}"

    def _construct_session_update(self) -> Dict[str, Any]:
        """Construct session.update request with voice and audio settings."""
        return {
            "event_id": self._generate_event_id(),
            "type": "session.update",
            "session": {
                "voice": self.config.voice or "Cherry",
                "modalities": ["text", "audio"],
                "response_format": self.config.format or "pcm",
                "sample_rate": self.config.sample_rate or 24000,
            }
        }

    def _construct_text_append(self, text: str) -> Dict[str, Any]:
        """Construct input_text_buffer.append request."""
        return {
            "event_id": self._generate_event_id(),
            "type": "input_text_buffer.append",
            "text": text
        }

    def _construct_text_commit(self) -> Dict[str, Any]:
        """Construct input_text_buffer.commit request to trigger synthesis."""
        return {
            "event_id": self._generate_event_id(),
            "type": "input_text_buffer.commit"
        }

    def _construct_response_create(self) -> Dict[str, Any]:
        """Construct response.create request to trigger TTS synthesis."""
        return {
            "event_id": self._generate_event_id(),
            "type": "response.create",
            "response": {
                "modalities": ["text", "audio"],
                "stream": True,
            }
        }

    def _construct_session_finish(self) -> Dict[str, Any]:
        """Construct session.finish request."""
        return {
            "event_id": self._generate_event_id(),
            "type": "session.finish"
        }

    def _parse_event(self, message: str) -> Dict[str, Any]:
        """Parse a JSON event from the API."""
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse JSON: {message[:100]}")
            return {"type": "unknown"}

        event_type = data.get("type", "")
        result: Dict[str, Any] = {"type": event_type, "raw": data}

        if event_type == "error":
            error = data.get("error", {})
            result["error_code"] = error.get("code")
            result["error_message"] = error.get("message")

        return result

    def _is_terminal_event(self, event_type: str) -> bool:
        """Check if event type indicates the session is done."""
        return event_type in ("response.done", "response.audio.done", "session.finished")

    async def _wait_for_session_created(self, ws) -> bool:
        """Wait for session.created event from the API."""
        while True:
            message = await asyncio.wait_for(ws.recv(), timeout=30)
            if isinstance(message, bytes):
                continue
            event = self._parse_event(message)
            event_type = event.get("type")
            logger.info(f"Qwen TTS received event during init: {event_type}, raw: {message[:300]}")

            if event_type == "session.created":
                return True
            if event_type == "error":
                raise AliTTSError(f"Qwen TTS session error: {event.get('error_message', 'Unknown error')}")
        return False

    async def _receive_audio(
        self,
        ws,
        buffer: Optional[bytearray] = None,
        yield_chunks: bool = False
    ) -> AsyncGenerator[bytes, None]:
        """Receive audio from Qwen Realtime TTS API."""
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

                event = self._parse_event(message)
                event_type = event.get("type")
                raw_event = event.get("raw", {})
                logger.info(f"Qwen TTS received event: {event_type}, keys: {list(raw_event.keys())}")

                if event_type == "error":
                    raise AliTTSError(f"Qwen TTS error: {raw_event.get('error', {}).get('message', 'Unknown error')}")

                if event_type == "response.audio.delta":
                    delta = raw_event.get("delta", "")
                    if delta:
                        audio_data = base64.b64decode(delta)
                        if buffer is not None:
                            buffer.extend(audio_data)
                        if yield_chunks:
                            yield audio_data

                audio_done = self._is_terminal_event(event_type)

            except asyncio.TimeoutError:
                logger.warning("Timeout waiting for Qwen TTS response")
                break

    async def _generate_non_streaming(self, ws_url: str, headers: Dict[str, str], text: str) -> bytes:
        """Non-streaming speech generation."""
        buffer = bytearray()

        try:
            async with websockets.connect(ws_url, additional_headers=headers, ping_interval=None) as ws:
                # Step 1: Wait for session.created
                await self._wait_for_session_created(ws)
                logger.info("Qwen TTS session created")

                # Step 2: Send session.update with voice config
                await ws.send(json.dumps(self._construct_session_update()))
                logger.info(f"Qwen TTS sent session.update with voice={self.config.voice}")

                # Step 3: Add text to buffer
                await ws.send(json.dumps(self._construct_text_append(text)))
                logger.info(f"Qwen TTS sent input_text_buffer.append: {text[:50]}...")

                # Step 4: Commit text to trigger synthesis
                await ws.send(json.dumps(self._construct_text_commit()))
                logger.info("Qwen TTS sent input_text_buffer.commit")

                # Step 5: Receive audio chunks
                async for _ in self._receive_audio(ws, buffer=buffer):
                    pass

        except AliTTSError:
            raise
        except Exception as e:
            logger.error(f"Qwen TTS error: {str(e)}")
            raise

        if len(buffer) == 0:
            logger.warning("No audio data received from Qwen TTS")
        return bytes(buffer)

    async def _generate_streaming(self, ws_url: str, headers: Dict[str, str], text: str) -> AsyncGenerator[bytes, None]:
        """Streaming speech generation."""
        try:
            async with websockets.connect(ws_url, additional_headers=headers, ping_interval=None) as ws:
                # Step 1: Wait for session.created
                await self._wait_for_session_created(ws)
                logger.info("Qwen TTS session created (streaming)")

                # Step 2: Send session.update with voice config
                await ws.send(json.dumps(self._construct_session_update()))
                logger.info(f"Qwen TTS sent session.update with voice={self.config.voice}")

                # Step 3: Add text to buffer
                await ws.send(json.dumps(self._construct_text_append(text)))
                logger.info(f"Qwen TTS sent input_text_buffer.append: {text[:50]}...")

                # Step 4: Commit text to trigger synthesis
                await ws.send(json.dumps(self._construct_text_commit()))
                logger.info("Qwen TTS sent input_text_buffer.commit")

                # Step 5: Stream audio chunks
                async for chunk in self._receive_audio(ws, yield_chunks=True):
                    yield chunk

        except AliTTSError:
            raise
        except Exception as e:
            logger.error(f"Qwen TTS streaming error: {str(e)}")
            raise

    async def check_connectivity(self) -> bool:
        """
        Test if the connection to the remote TTS service is normal.

        Returns:
            True if connection successful, False otherwise.
        """
        try:
            logger.info(f"Qwen TTS connectivity test started with model={self.config.model}, voice={self.config.voice}")
            audio_data = await self.generate_speech("Hello", stream=False)
            is_success = self._is_tts_result_successful(audio_data)
            if is_success:
                logger.info("Qwen TTS connectivity test successful")
            else:
                logger.error("Qwen TTS connectivity test failed: empty audio data")
            return is_success
        except AliTTSError as e:
            logger.error(f"Qwen TTS connectivity test failed: {e.message}")
            return False
        except Exception as e:
            logger.error(f"Qwen TTS connectivity test failed with exception: {str(e)}")
            return False
