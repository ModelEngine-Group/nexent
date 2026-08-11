"""STT (speech-to-text) adapter — protocol implementation sunk in.

The WebSocket speech-to-text protocols (Ali DashScope Realtime JSON-over-WS and
Volc SAUC binary-gzip frames) live directly in the adapters. The old
``ali_stt_model.py`` / ``volc_stt_model.py`` / ``stt_model.py`` (BaseSTTModel)
classes are deleted; the adapters ARE the implementation.

ModelEngine STT is different: it is HTTP REST, turning audio into base64 and
reusing the OpenAI Chat Completions protocol, so its ``_inner`` is
:class:`OpenAIModel` (kept — see §3.16 LLM exception), not a dedicated STT
class. The audio↔base64 conversion lives in the adapter's ``invoke``. This
proves the transport Mixin is orthogonal: an HTTP-only STT vendor needs no
WebSocket plumbing.
"""

from __future__ import annotations

import asyncio
import base64
import datetime
import gzip
import json
import logging
import mimetypes
import time
import uuid
import wave
from abc import abstractmethod
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

import aiofiles
import websockets

from ..base import ModelInfo, MultimodalAdapter
from ..context import ModelContext
from ..registry import register_adapter
from ..transport import HttpTransportMixin, WebSocketTransportMixin

logger = logging.getLogger(__name__)


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
    """STT adapter root.

    Carries the shared STT result-inspection helpers that previously lived on
    the deleted ``BaseSTTModel`` ABC, so concrete WS adapters inherit them.
    """

    modality = "stt"

    @abstractmethod
    async def invoke(self, request: STTRequest) -> Dict[str, Any]:
        """Transcribe ``request.audio_path`` → ``{"text": ..., "raw": ...}``."""

    @abstractmethod
    async def stream(self, request: STTStreamRequest) -> AsyncIterator[Dict[str, Any]]:
        """Real-time streaming transcription."""

    def _is_stt_result_successful(self, result: Any) -> bool:
        """Check if STT result indicates a successful recognition."""
        if not isinstance(result, dict) or not result:
            return False

        if 'error' in result:
            return False

        if 'code' in result and result['code'] != 1000:
            return False

        if 'payload_msg' in result and isinstance(result['payload_msg'], dict):
            if 'error' in result['payload_msg']:
                return False

        return True

    def _extract_stt_error_message(self, result: Any) -> str:
        """Extract error message from STT result."""
        if not isinstance(result, dict):
            return f"Invalid result type: {type(result)}"

        if 'error' in result:
            return str(result['error'])

        if 'code' in result and result['code'] != 1000:
            error_msg = f"STT service error code: {result['code']}"
            if 'payload_msg' in result and isinstance(result['payload_msg'], dict):
                if 'error' in result['payload_msg']:
                    error_msg += f" - {result['payload_msg']['error']}"
            return error_msg

        if 'payload_msg' in result and isinstance(result['payload_msg'], dict):
            if 'error' in result['payload_msg']:
                return str(result['payload_msg']['error'])

        return f"Unknown error in result: {result}"


# ============================================================================
# Ali STT — DashScope Realtime (JSON over WebSocket)
# ============================================================================

class AliSTTConfig:
    """Configuration for Ali STT model (Qwen Realtime API protocol)."""

    def __init__(
        self,
        api_key: str,
        model: str = "qwen3-asr-flash-realtime",
        language: str = "zh",
        ws_url: Optional[str] = None,
        format: str = "pcm",
        rate: int = 16000,
        channel: int = 1,
        seg_duration: int = 100,
        timeout: int = 60,
        enable_vad: bool = True,
        vad_threshold: float = 0.5,
        vad_silence_duration_ms: int = 2000,
    ):
        self.api_key = api_key
        self.model = model
        self.language = language
        self.ws_url = ws_url
        self.format = format
        self.rate = rate
        self.channel = channel
        self.seg_duration = seg_duration
        self.timeout = timeout
        self.enable_vad = enable_vad
        self.vad_threshold = vad_threshold
        self.vad_silence_duration_ms = vad_silence_duration_ms


class TranscriptionResult:
    """Container for transcription results."""

    def __init__(self):
        self.text: str = ""
        self.is_final: bool = False
        self.error: Optional[str] = None
        self.vad: Optional[str] = None


@register_adapter("ali", "stt")
class AliSTTAdapter(STTAdapter, WebSocketTransportMixin):
    """Ali STT — DashScope Realtime, JSON over WebSocket.

    Protocol (session.update / input_audio_buffer.append|commit / session.finish,
    VAD events, transcription text/completed events) lives here.
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
        self.config = AliSTTConfig(
            api_key=context.api_key,
            model=context.model_name,
            language=context.language,
            ws_url=self._ws_url,
            format=extras.get("format", "pcm"),
            rate=extras.get("rate", 16000),
            enable_vad=extras.get("enable_vad", True),
            timeout=extras.get("timeout", 60),
        )
        self.audio_file_path = context.audio_file_path
        self._current_result = TranscriptionResult()

    def get_websocket_url(self) -> str:
        """Get the WebSocket URL for the STT service."""
        if self.config.ws_url:
            return f"{self.config.ws_url}?model={self.config.model}"
        return f"wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model={self.config.model}"

    def get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers for the WebSocket connection."""
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "OpenAI-Beta": "realtime=v1"
        }

    def generate_event_id(self) -> str:
        """Generate a unique event ID."""
        return f"event_{uuid.uuid4().hex[:16]}"

    def construct_session_update(self) -> Dict[str, Any]:
        """Construct the session.update event."""
        if self.config.enable_vad:
            turn_detection = {
                "type": "server_vad",
                "threshold": self.config.vad_threshold,
                "silence_duration_ms": self.config.vad_silence_duration_ms
            }
        else:
            turn_detection = None

        return {
            "event_id": self.generate_event_id(),
            "type": "session.update",
            "session": {
                "modalities": ["text"],
                "input_audio_format": self.config.format,
                "sample_rate": self.config.rate,
                "input_audio_transcription": {
                    "model": self.config.model,
                    "language": self.config.language
                },
                "turn_detection": turn_detection
            }
        }

    def construct_audio_append_event(self, audio_data: bytes) -> Dict[str, Any]:
        """Construct the input_audio_buffer.append event with base64 encoded audio."""
        audio_b64 = base64.b64encode(audio_data).decode('utf-8')
        return {
            "event_id": self.generate_event_id(),
            "type": "input_audio_buffer.append",
            "audio": audio_b64
        }

    def construct_audio_commit_event(self) -> Dict[str, Any]:
        """Construct the input_audio_buffer.commit event."""
        return {
            "event_id": self.generate_event_id(),
            "type": "input_audio_buffer.commit"
        }

    def construct_session_finish_event(self) -> Dict[str, Any]:
        """Construct the session.finish event."""
        return {
            "event_id": self.generate_event_id(),
            "type": "session.finish"
        }

    async def _handle_stt_event(self, result: Dict[str, Any], websocket: Any, transcription_texts: List[str]) -> bool:
        """Handle STT server event and return True if session should end."""
        event_type = result.get("event", "")

        if event_type == "error":
            error_msg = result.get("error", "Unknown error")
            logger.error(f"STT error: {error_msg}")
            try:
                await websocket.send_json({"error": error_msg})
            except Exception:
                pass
            return True

        elif event_type == "input_audio_buffer.speech_started":
            logger.info("VAD detected speech start")
            try:
                await websocket.send_json({"vad": "started"})
            except Exception:
                pass
            return False

        elif event_type == "input_audio_buffer.speech_stopped":
            logger.info("VAD detected speech stop")
            try:
                await websocket.send_json({"vad": "stopped"})
            except Exception:
                pass
            return False

        elif event_type == "conversation.item.input_audio_transcription.text":
            text = result.get("text", "")
            if text:
                transcription_texts.append(text)
            try:
                await websocket.send_json({"text": text, "is_final": False})
            except Exception:
                pass
            return False

        elif event_type == "conversation.item.input_audio_transcription.completed":
            text = result.get("text", "")
            if text:
                transcription_texts.append(text)
            try:
                await websocket.send_json({"text": text, "is_final": True})
            except Exception:
                pass
            return False

        elif event_type == "session.finished":
            transcript = result.get("transcript", "")
            if transcript:
                transcription_texts.append(transcript)
            final_text = transcript or " ".join(transcription_texts)
            try:
                await websocket.send_json({"text": final_text, "is_final": True})
            except Exception:
                pass
            return True

        elif event_type in ["session.created", "session.updated"]:
            logger.info(f"Session event: {event_type}")
            return False

        else:
            logger.info(f"Unhandled STT event type: {event_type}")
            return False

    def parse_response(self, response: Any) -> Dict[str, Any]:
        """Parse the response from the STT service."""
        if isinstance(response, str):
            try:
                response = json.loads(response)
            except json.JSONDecodeError:
                return {"event": "unknown", "raw": response}

        if not isinstance(response, dict):
            return {"event": "unknown", "raw": str(response)}

        result = {"event": response.get("type", "")}

        event_type = response.get("type", "")

        if event_type == "session.created":
            result["session_id"] = response.get("session", {}).get("id")

        elif event_type == "session.updated":
            result["session_id"] = response.get("session", {}).get("id")

        elif event_type == "conversation.item.input_audio_transcription.completed":
            result["is_last_package"] = True
            result["text"] = response.get("transcript", "")

        elif event_type == "conversation.item.input_audio_transcription.text":
            result["text"] = response.get("text", "")

        elif event_type == "input_audio_buffer.speech_started":
            result["vad"] = "started"

        elif event_type == "input_audio_buffer.speech_stopped":
            result["vad"] = "stopped"

        elif event_type == "session.finished":
            result["finished"] = True
            result["transcript"] = response.get("transcript", "")

        elif event_type == "error":
            result["error"] = response.get("message", "Unknown error")

        return result

    @staticmethod
    def read_wav_info(data: bytes) -> tuple:
        """Read WAV file information."""
        with BytesIO(data) as _f:
            wave_fp = wave.open(_f, 'rb')
            nchannels, sampwidth, framerate, nframes = wave_fp.getparams()[:4]
            wave_bytes = wave_fp.readframes(nframes)
        return nchannels, sampwidth, framerate, nframes, wave_bytes

    @staticmethod
    def slice_data(data: bytes, chunk_size: int):
        """Slice audio data into chunks."""
        offset = 0
        total_len = len(data)

        while offset < total_len:
            end = min(offset + chunk_size, total_len)
            chunk = data[offset:end]
            is_last = end >= total_len
            yield chunk, is_last
            offset = end

    async def process_audio_file(
        self,
        audio_path: str,
        on_result: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """Process audio file and perform speech recognition."""
        async with aiofiles.open(audio_path, mode="rb") as _f:
            data = await _f.read()
        audio_data = bytes(data)

        if self.config.format == "wav":
            nchannels, sampwidth, framerate, _, wav_bytes = self.read_wav_info(audio_data)
            size_per_sec = nchannels * sampwidth * framerate
            segment_size = int(size_per_sec * self.config.seg_duration / 1000)
            return await self.process_audio_data(wav_bytes, segment_size, on_result)

        if self.config.format == "pcm":
            if audio_data[:4] == b'RIFF' and audio_data[8:12] == b'WAVE':
                nchannels, sampwidth, framerate, _, wav_bytes = self.read_wav_info(audio_data)
                segment_size = int(self.config.rate * 2 * self.config.channel * self.config.seg_duration / 1000)
                return await self.process_audio_data(wav_bytes, segment_size, on_result)
            else:
                segment_size = int(self.config.rate * 2 * self.config.channel * self.config.seg_duration / 1000)
                return await self.process_audio_data(audio_data, segment_size, on_result)

        raise Exception("Unsupported format, only wav and pcm are supported")

    async def process_audio_data(
        self,
        audio_data: bytes,
        segment_size: int,
        on_result: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """Process audio data and perform speech recognition using Qwen Realtime API."""
        ws_url = self.get_websocket_url()
        headers = self.get_auth_headers()
        logger.info(f"Connecting to {ws_url}")

        self._current_result = TranscriptionResult()
        transcription_texts = []

        try:
            async with websockets.connect(ws_url, additional_headers=headers, max_size=1000000000) as ws:
                response_text = await asyncio.wait_for(ws.recv(), timeout=self.config.timeout)
                response = json.loads(response_text)
                logger.info(f"Session created: {response}")

                result = self.parse_response(response)
                if result.get("event") == "session.created":
                    logger.info("Session created successfully")

                session_update = self.construct_session_update()
                await ws.send(json.dumps(session_update))
                logger.info(f"Session.update sent: {session_update}")

                audio_chunks_sent = 0
                for chunk, last in self.slice_data(audio_data, segment_size):
                    audio_event = self.construct_audio_append_event(chunk)
                    await ws.send(json.dumps(audio_event))
                    audio_chunks_sent += 1

                    if last:
                        break

                logger.info(f"Sent {audio_chunks_sent} audio chunks")

                if not self.config.enable_vad:
                    commit_event = self.construct_audio_commit_event()
                    await ws.send(json.dumps(commit_event))
                    logger.info("Audio buffer committed")

                finish_event = self.construct_session_finish_event()
                await ws.send(json.dumps(finish_event))
                logger.info("Session.finish sent")

                for _ in range(100):
                    try:
                        response_text = await asyncio.wait_for(ws.recv(), timeout=self.config.timeout)
                        response = json.loads(response_text)
                        result = self.parse_response(response)
                        logger.info(f"Received: {result}")

                        if "error" in result:
                            self._current_result.error = result["error"]
                            return {"error": result["error"]}

                        event_type = result.get("event", "")

                        if event_type == "conversation.item.input_audio_transcription.completed":
                            text = result.get("text", "")
                            if text:
                                transcription_texts.append(text)
                                if on_result:
                                    await on_result(text)

                        elif event_type == "conversation.item.input_audio_transcription.text":
                            # Only send intermediate results via callback, don't accumulate
                            text = result.get("text", "")
                            if text and on_result:
                                await on_result(text)

                        elif event_type == "session.finished":
                            transcript = response.get("transcript", "")
                            if transcript:
                                transcription_texts.append(transcript)
                            break

                    except asyncio.TimeoutError:
                        logger.warning("Timeout waiting for response")
                        break

                final_text = " ".join(transcription_texts)
                self._current_result.text = final_text

                if final_text:
                    return {"text": final_text}
                elif self._current_result.error:
                    return {"error": self._current_result.error}
                else:
                    return {"text": ""}

        except Exception as e:
            logger.error(f"WebSocket error: {str(e)}")
            return {"error": f"WebSocket error: {str(e)}"}

    async def recognize_file(self, audio_path: str) -> Dict[str, Any]:
        """Recognize speech from audio file."""
        return await self.process_audio_file(audio_path)

    async def check_connectivity(self) -> bool:
        """Check if the STT service is accessible."""
        try:
            logger.info("STT connectivity test started...")
            result = await self.process_audio_file(self.audio_file_path)
            is_success = self._is_stt_result_successful(result)
            if is_success:
                logger.info("STT connectivity test successful")
            else:
                error_msg = self._extract_stt_error_message(result)
                logger.error(f"STT connectivity test failed with error: {error_msg}")
            return is_success
        except Exception as e:
            logger.error(f"STT connectivity test failed with exception: {str(e)}")
            import traceback
            logger.error(f"STT connectivity test exception traceback: {traceback.format_exc()}")
            return False

    async def start_streaming_session(self, websocket, config_received: bool = True):
        """Start a streaming session for real-time STT.

        Processing logic aligned with the official Ali VAD example.
        """
        ws_url = self.get_websocket_url()
        headers = self.get_auth_headers()
        logger.info(f"Starting Ali STT streaming session, connecting to {ws_url}")

        try:
            async with websockets.connect(ws_url, additional_headers=headers, max_size=1000000000) as ws_server:
                response_text = await asyncio.wait_for(ws_server.recv(), timeout=self.config.timeout)
                response = json.loads(response_text)
                logger.info(f"STT server session created: {response}")

                # Session update with VAD (matching official example)
                session_update = {
                    "event_id": "event_123",
                    "type": "session.update",
                    "session": {
                        "modalities": ["text"],
                        "input_audio_format": self.config.format,
                        "sample_rate": self.config.rate,
                        "input_audio_transcription": {
                            "language": self.config.language
                        },
                        "turn_detection": {
                            "type": "server_vad",
                            "threshold": self.config.vad_threshold,
                            "silence_duration_ms": self.config.vad_silence_duration_ms
                        }
                    }
                }
                await ws_server.send(json.dumps(session_update))
                logger.info(f"Session.update sent with VAD (threshold={self.config.vad_threshold}, silence={self.config.vad_silence_duration_ms}ms)")

                # Wait for session.updated event
                try:
                    response_text = await asyncio.wait_for(ws_server.recv(), timeout=self.config.timeout)
                    response = json.loads(response_text)
                    logger.info(f"Session updated: {response}")
                except asyncio.TimeoutError:
                    logger.warning("Timeout waiting for session.updated")

                # Tell client we're ready to receive audio
                try:
                    await websocket.send_json({"status": "ready"})
                except Exception as e:
                    logger.error(f"Client disconnected: {e}")
                    return

                transcription_texts = []
                counter = 0
                client_connected = True

                while client_connected:
                    # Reset for new audio turn
                    counter = 0
                    turn_complete = False

                    # Listen for audio data from client
                    while client_connected and not turn_complete:
                        try:
                            client_data = await asyncio.wait_for(websocket.receive_bytes(), timeout=0.5)
                        except asyncio.TimeoutError:
                            # No audio data, turn is complete
                            # Commit the buffered audio
                            try:
                                commit_event = {
                                    "event_id": f"event_{int(time.time() * 1000)}",
                                    "type": "input_audio_buffer.commit"
                                }
                                await ws_server.send(json.dumps(commit_event))
                                logger.info("Audio buffer committed for turn")
                            except Exception as e:
                                logger.error(f"Error sending commit: {e}")
                            turn_complete = True
                            break
                        except websockets.exceptions.ConnectionClosed:
                            logger.info("Client WebSocket connection closed")
                            client_connected = False
                            break
                        except Exception as e:
                            logger.error(f"Error receiving audio data: {str(e)}")
                            client_connected = False
                            break

                        if not client_data:
                            continue

                        counter += 1
                        logger.debug(f"Received audio chunk {counter}: {len(client_data)} bytes")

                        # Send audio to STT server (base64 encoded)
                        try:
                            audio_b64 = base64.b64encode(client_data).decode('utf-8')
                            audio_event = {
                                "event_id": f"event_{int(time.time() * 1000)}",
                                "type": "input_audio_buffer.append",
                                "audio": audio_b64
                            }
                            await ws_server.send(json.dumps(audio_event))
                        except Exception as e:
                            logger.error(f"Error sending to STT service: {e}")
                            client_connected = False
                            break

                        # Process STT responses
                        try:
                            response_text = await asyncio.wait_for(ws_server.recv(), timeout=0.5)
                            response = json.loads(response_text)
                            event_type = response.get("type", "")
                            logger.info(f"STT server event: {event_type}")

                            if event_type == "error":
                                error_msg = response.get("error", "Unknown error")
                                logger.error(f"STT error: {error_msg}")
                                if client_connected:
                                    await websocket.send_json({"error": error_msg})
                                client_connected = False
                                break

                            elif event_type == "input_audio_buffer.speech_started":
                                logger.info("VAD: speech started")
                                if client_connected:
                                    await websocket.send_json({"vad": "started"})

                            elif event_type == "input_audio_buffer.speech_stopped":
                                logger.info("VAD: speech stopped")
                                if client_connected:
                                    await websocket.send_json({"vad": "stopped"})

                            elif event_type == "input_audio_buffer.committed":
                                logger.info("VAD: audio buffer committed")
                                # Buffer committed, turn is complete
                                turn_complete = True
                                break

                            elif event_type == "conversation.item.input_audio_transcription.text":
                                text = response.get("text", "") or response.get("stash", "")
                                if not text:
                                    item = response.get("item", {})
                                    content = item.get("content", [])
                                    if content and isinstance(content, list):
                                        text = content[0].get("transcript", "")
                                if client_connected:
                                    logger.info(f"Sending transcription to client: {text}")
                                    await websocket.send_json({"text": text, "is_final": False})

                            elif event_type == "conversation.item.input_audio_transcription.completed":
                                text = response.get("text", "") or response.get("transcript", "")
                                if not text:
                                    item = response.get("item", {})
                                    content = item.get("content", [])
                                    if content and isinstance(content, list):
                                        text = content[0].get("transcript", "")
                                if text:
                                    transcription_texts.append(text)
                                if client_connected:
                                    full_text = " ".join(transcription_texts)
                                    logger.info(f"Sending final transcription to client: {full_text}")
                                    await websocket.send_json({"text": full_text, "is_final": True})

                            elif event_type in ["session.finished", "session.created", "session.updated", "conversation.item.created"]:
                                pass

                            else:
                                logger.debug(f"Unhandled STT event: {event_type}")

                        except asyncio.TimeoutError:
                            # No pending responses, continue waiting for audio
                            pass
                        except websockets.exceptions.ConnectionClosed:
                            logger.info("STT server connection closed")
                            client_connected = False
                            break

                    # Wait for user to speak again (VAD will trigger speech_started)
                    logger.info("Waiting for next speech input...")

        except websockets.exceptions.ConnectionClosed:
            logger.info("STT server connection closed")
        except Exception as e:
            logger.error(f"STT streaming session error: {str(e)}")
            try:
                await websocket.send_json({"error": str(e)})
            except Exception:
                pass

    async def invoke(self, request: STTRequest) -> Dict[str, Any]:
        return await self.recognize_file(request.audio_path)

    async def stream(self, request: STTStreamRequest) -> AsyncIterator[Dict[str, Any]]:
        await self.start_streaming_session(
            request.websocket, config_received=request.config_received
        )
        return
        yield  # pragma: no cover  (marks as async generator)

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
# Volc STT — proprietary binary-frame WebSocket (SAUC, gzip compressed)
# ============================================================================

# Protocol constants
PROTOCOL_VERSION = 0b0001
DEFAULT_HEADER_SIZE = 0b0001

# Message Type
CLIENT_FULL_REQUEST = 0b0001
CLIENT_AUDIO_ONLY_REQUEST = 0b0010
SERVER_FULL_RESPONSE = 0b1001
SERVER_ACK = 0b1011
SERVER_ERROR_RESPONSE = 0b1111

# Message Type Specific Flags
NO_SEQUENCE = 0b0000
POS_SEQUENCE = 0b0001
NEG_SEQUENCE = 0b0010
NEG_WITH_SEQUENCE = 0b0011
NEG_SEQUENCE_1 = 0b0011

# Message Serialization
NO_SERIALIZATION = 0b0000
JSON = 0b0001
THRIFT = 0b0011
CUSTOM_TYPE = 0b1111

# Message Compression
NO_COMPRESSION = 0b0000
GZIP = 0b0001
CUSTOM_COMPRESSION = 0b1111


class VolcSTTConfig:
    """Configuration for Volcano Engine STT model."""

    def __init__(
        self,
        appid: str,
        access_token: str,
        ws_url: str = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel",
        uid: str = "streaming_asr_demo",
        format: str = "pcm",
        rate: int = 16000,
        bits: int = 16,
        channel: int = 1,
        codec: str = "raw",
        seg_duration: int = 10,
        mp3_seg_size: int = 1000,
        resourceid: str = "volc.bigasr.sauc.duration",
        streaming: bool = True,
        compression: bool = True
    ):
        self.appid = appid
        self.access_token = access_token
        self.ws_url = ws_url
        self.uid = uid
        self.format = format
        self.rate = rate
        self.bits = bits
        self.channel = channel
        self.codec = codec
        self.seg_duration = seg_duration
        self.mp3_seg_size = mp3_seg_size
        self.resourceid = resourceid
        self.streaming = streaming
        self.compression = compression


@register_adapter("volc", "stt")
class VolcSTTAdapter(STTAdapter, WebSocketTransportMixin):
    """Volc STT — proprietary binary-frame WS (SAUC, gzip compressed).

    The full binary protocol (header/payload construction, sequence numbers,
    gzip framing, response parsing) lives here.
    """

    factory = "volc"

    def __init__(self, context: ModelContext) -> None:
        MultimodalAdapter.__init__(self, context)
        WebSocketTransportMixin.__init__(
            self,
            ws_url=context.extra.get("ws_url"),
            auth_headers=context.extra.get("auth_headers"),
        )
        self.config = VolcSTTConfig(
            appid=context.model_appid or "",
            access_token=context.access_token or "",
            ws_url=self._ws_url or "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel",
            format=context.extra.get("format", "pcm"),
            rate=context.extra.get("rate", 16000),
            resourceid=context.extra.get(
                "resourceid", "volc.bigasr.sauc.duration"
            ),
        )
        self.audio_file_path = context.audio_file_path
        self.success_code = 1000

    def get_websocket_url(self) -> str:
        """Get the WebSocket URL for the STT service."""
        return self.config.ws_url

    def get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers for the WebSocket connection."""
        headers = {
            "X-Api-Resource-Id": self.config.resourceid,
            "X-Api-Connect-Id": str(uuid.uuid4())
        }

        if self.config.access_token:
            headers["X-Api-Access-Key"] = self.config.access_token

        if self.config.appid:
            headers["X-Api-App-Key"] = self.config.appid

        return headers

    def generate_header(self, message_type=CLIENT_FULL_REQUEST,
                        message_type_specific_flags=NO_SEQUENCE,
                        serial_method=JSON, compression_type=None,
                        reserved_data=0x00) -> bytearray:
        """Generate protocol header."""
        if compression_type is None:
            compression_type = GZIP if self.config.compression else NO_COMPRESSION

        header = bytearray()
        header_size = 1
        header.append((PROTOCOL_VERSION << 4) | header_size)
        header.append((message_type << 4) | message_type_specific_flags)
        header.append((serial_method << 4) | compression_type)
        header.append(reserved_data)
        return header

    def generate_before_payload(self, sequence: int) -> bytearray:
        """Generate the payload prefix with sequence number."""
        before_payload = bytearray()
        before_payload.extend(sequence.to_bytes(4, 'big', signed=True))
        return before_payload

    def parse_response(self, res: bytes) -> Dict[str, Any]:
        """Parse response from server."""
        header_size = res[0] & 0x0f
        message_type = res[1] >> 4
        message_type_specific_flags = res[1] & 0x0f
        serialization_methods = res[2] >> 4
        message_compression = res[2] & 0x0f
        payload = res[header_size * 4:]
        result: Dict[str, Any] = {'is_last_package': False}
        payload_msg = None
        payload_size = 0

        if message_type_specific_flags & 0x01:
            seq = int.from_bytes(payload[:4], "big", signed=True)
            result['payload_sequence'] = seq
            payload = payload[4:]

        if message_type_specific_flags & 0x02:
            result['is_last_package'] = True

        if message_type == SERVER_FULL_RESPONSE:
            payload_size = int.from_bytes(payload[:4], "big", signed=True)
            payload_msg = payload[4:]
        elif message_type == SERVER_ACK:
            seq = int.from_bytes(payload[:4], "big", signed=True)
            result['seq'] = seq
            if len(payload) >= 8:
                payload_size = int.from_bytes(payload[4:8], "big", signed=False)
                payload_msg = payload[8:]
        elif message_type == SERVER_ERROR_RESPONSE:
            code = int.from_bytes(payload[:4], "big", signed=False)
            result['code'] = code
            payload_size = int.from_bytes(payload[4:8], "big", signed=False)
            payload_msg = payload[8:]

        if payload_msg is None:
            return result

        if message_compression == GZIP:
            payload_msg = gzip.decompress(payload_msg)

        if serialization_methods == JSON:
            payload_msg = json.loads(str(payload_msg, "utf-8"))
        elif serialization_methods != NO_SERIALIZATION:
            payload_msg = str(payload_msg, "utf-8")

        result['payload_msg'] = payload_msg
        result['payload_size'] = payload_size
        return result

    @staticmethod
    def read_wav_info(data: bytes) -> tuple:
        """Read WAV file information."""
        with BytesIO(data) as _f:
            wave_fp = wave.open(_f, 'rb')
            nchannels, sampwidth, framerate, nframes = wave_fp.getparams()[:4]
            wave_bytes = wave_fp.readframes(nframes)
        return nchannels, sampwidth, framerate, nframes, wave_bytes

    @staticmethod
    def slice_data(data: bytes, chunk_size: int):
        """Slice data into chunks."""
        data_len = len(data)
        offset = 0
        while offset + chunk_size < data_len:
            yield data[offset: offset + chunk_size], False
            offset += chunk_size
        yield data[offset: data_len], True

    def construct_request(self, reqid: str) -> Dict[str, Any]:
        """Construct request parameters."""
        req = {
            "user": {"uid": self.config.uid},
            "audio": {
                'format': self.config.format,
                "sample_rate": self.config.rate,
                "bits": self.config.bits,
                "channel": self.config.channel,
                "codec": self.config.codec
            },
            "request": {
                "model_name": "bigmodel",
                "enable_punc": True
            }
        }
        logger.info(f"req: {req}")
        return req

    async def process_audio_data(self, audio_data: bytes, segment_size: int) -> Dict[str, Any]:
        """Process audio data and perform speech recognition."""
        reqid = str(uuid.uuid4())
        seq = 1

        request_params = self.construct_request(reqid)
        payload_bytes = str.encode(json.dumps(request_params))

        if self.config.compression:
            payload_bytes = gzip.compress(payload_bytes)

        full_client_request = bytearray(self.generate_header(message_type_specific_flags=POS_SEQUENCE))
        full_client_request.extend(self.generate_before_payload(sequence=seq))
        full_client_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
        full_client_request.extend(payload_bytes)

        headers = self.get_auth_headers()
        headers["X-Api-Connect-Id"] = reqid
        logger.info(f"Connecting to {self.config.ws_url} with headers: {headers}")

        try:
            async with websockets.connect(self.config.ws_url, additional_headers=headers,
                                          max_size=1000000000) as ws:
                await ws.send(full_client_request)
                res = await ws.recv()
                if hasattr(ws, 'response_headers'):
                    logger.info(f"Response headers: {ws.response_headers}")
                result = self.parse_response(res)
                logger.info(f"Initial response: {result}")

                for _, (chunk, last) in enumerate(self.slice_data(audio_data, segment_size), 1):
                    seq += 1
                    if last:
                        seq = -seq

                    start = time.time()

                    if self.config.compression:
                        payload_bytes = gzip.compress(chunk)
                    else:
                        payload_bytes = chunk

                    if last:
                        audio_only_request = bytearray(
                            self.generate_header(message_type=CLIENT_AUDIO_ONLY_REQUEST,
                                                 message_type_specific_flags=NEG_WITH_SEQUENCE))
                    else:
                        audio_only_request = bytearray(
                            self.generate_header(message_type=CLIENT_AUDIO_ONLY_REQUEST,
                                                 message_type_specific_flags=POS_SEQUENCE))

                    audio_only_request.extend(self.generate_before_payload(sequence=seq))
                    audio_only_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
                    audio_only_request.extend(payload_bytes)

                    await ws.send(audio_only_request)
                    res = await ws.recv()
                    result = self.parse_response(res)

                    logger.info(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}, seq: {seq}, result: {result}")

                    if self.config.streaming:
                        sleep_time = max(0.0, self.config.seg_duration / 1000.0 - (time.time() - start))
                        await asyncio.sleep(sleep_time)

            return result

        except websockets.exceptions.ConnectionClosedError as e:
            logger.error(f"WebSocket connection closed: {e.reason}")
            return {"error": f"Connection closed: {e.reason}"}

        except websockets.exceptions.WebSocketException as e:
            logger.error(f"WebSocket error: {e}")
            if hasattr(e, "status_code"):
                logger.error(f"Status code: {e.status_code}")
            if hasattr(e, "headers"):
                logger.error(f"Headers: {e.headers}")
            if hasattr(e, "response") and hasattr(e.response, "text"):
                logger.error(f"Response: {e.response.text}")
            return {"error": f"WebSocket error: {str(e)}"}

        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            import traceback
            traceback.print_exc()
            return {"error": f"Unexpected error: {str(e)}"}

    async def process_audio_file(self, audio_path: str) -> Dict[str, Any]:
        """Process audio file and perform speech recognition."""
        async with aiofiles.open(audio_path, mode="rb") as _f:
            data = await _f.read()
        audio_data = bytes(data)

        if self.config.format == "mp3":
            segment_size = self.config.mp3_seg_size
            return await self.process_audio_data(audio_data, segment_size)

        if self.config.format == "wav":
            nchannels, sampwidth, framerate, _, wav_bytes = self.read_wav_info(audio_data)
            size_per_sec = nchannels * sampwidth * framerate
            segment_size = int(size_per_sec * self.config.seg_duration / 1000)
            return await self.process_audio_data(wav_bytes, segment_size)

        if self.config.format == "pcm":
            segment_size = int(self.config.rate * 2 * self.config.channel * self.config.seg_duration / 500)
            return await self.process_audio_data(audio_data, segment_size)

        raise Exception("Unsupported format, only wav, mp3, and pcm are supported")

    async def process_streaming_audio(self, ws_client, segment_size: int):
        """Process streaming audio from WebSocket client and send transcription back."""
        logger.info("Starting audio processing loop...")
        reqid = str(uuid.uuid4())
        seq = 1
        client_connected = True

        request_params = self.construct_request(reqid)
        payload_bytes = str.encode(json.dumps(request_params))

        if self.config.compression:
            payload_bytes = gzip.compress(payload_bytes)

        full_client_request = bytearray(self.generate_header(message_type_specific_flags=POS_SEQUENCE))
        full_client_request.extend(self.generate_before_payload(sequence=seq))
        full_client_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
        full_client_request.extend(payload_bytes)

        headers = self.get_auth_headers()
        headers["X-Api-Connect-Id"] = reqid
        logger.info(f"Request headers: {headers}")

        try:
            async with websockets.connect(self.config.ws_url, additional_headers=headers,
                                          max_size=1000000000) as ws_server:
                logger.info("Connected to STT service")

                await ws_server.send(full_client_request)
                response = await ws_server.recv()
                result = self.parse_response(response)
                logger.info("Initial response received")

                try:
                    await ws_client.send_json({"status": "ready"})
                except Exception as e:
                    logger.error(f"Client disconnected: {e}")
                    client_connected = False
                    return

                last_chunk_received = False

                while client_connected:
                    try:
                        client_data = await ws_client.receive_bytes()
                    except Exception as e:
                        logger.error(f"Error receiving audio data: {str(e)}")
                        client_connected = False
                        break

                    if not client_data:
                        logger.info("Received empty audio data, indicating end of stream")
                        last_chunk_received = True
                        client_data = bytes(0)

                    seq += 1

                    if last_chunk_received:
                        seq = -abs(seq)
                        logger.info("This is the final chunk, using negative sequence")
                        audio_only_request = bytearray(
                            self.generate_header(message_type=CLIENT_AUDIO_ONLY_REQUEST,
                                                 message_type_specific_flags=NEG_WITH_SEQUENCE))
                    else:
                        audio_only_request = bytearray(
                            self.generate_header(message_type=CLIENT_AUDIO_ONLY_REQUEST,
                                                 message_type_specific_flags=POS_SEQUENCE))

                    if self.config.compression:
                        payload_bytes = gzip.compress(client_data)
                    else:
                        payload_bytes = client_data

                    audio_only_request.extend(self.generate_before_payload(sequence=seq))
                    audio_only_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
                    audio_only_request.extend(payload_bytes)

                    try:
                        await ws_server.send(audio_only_request)
                    except Exception as e:
                        logger.error(f"Error sending to STT service: {e}")
                        if client_connected:
                            try:
                                await ws_client.send_json({"error": f"STT service error: {str(e)}"})
                                client_connected = False
                            except:
                                pass
                        break

                    try:
                        response = await ws_server.recv()
                        result = self.parse_response(response)
                        result_text = "empty"
                        try:
                            result_text = result['payload_msg']['result']['text'] if result['payload_msg']['result']['text'] else "empty"
                        except:
                            logger.error(f"Malformed result: {result}")
                        logger.info(f"Received response: {result_text}")

                        if client_connected and 'payload_msg' in result:
                            payload = result['payload_msg']

                            if 'result' in payload and 'text' in payload['result'] and not payload['result']['text']:
                                payload['status'] = 'processing'

                            try:
                                await ws_client.send_json(payload)
                            except Exception as e:
                                logger.error(f"Client disconnected while sending result: {e}")
                                client_connected = False
                                break
                        elif client_connected:
                            logger.info("Sending processing status to client")
                            try:
                                await ws_client.send_json({"status": "processing"})
                            except Exception as e:
                                logger.error(f"Client disconnected while sending status: {e}")
                                client_connected = False
                                break
                    except websockets.exceptions.ConnectionClosed as e:
                        logger.error(f"STT service connection closed: {e}")
                        if last_chunk_received:
                            break
                        elif client_connected:
                            try:
                                await ws_client.send_json({"error": f"STT service connection closed unexpectedly: {e}"})
                                client_connected = False
                            except:
                                pass
                            break

                    if last_chunk_received:
                        logger.info("Last chunk processed, exiting loop")
                        break

                    if self.config.streaming:
                        sleep_time = max(0, (self.config.seg_duration / 1000.0))
                        await asyncio.sleep(sleep_time)

        except websockets.exceptions.ConnectionClosedError as e:
            error_msg = f"WebSocket connection closed: {e.reason} (code: {e.code})"
            logger.error(f"{error_msg}")
            if client_connected:
                try:
                    await ws_client.send_json({"error": error_msg})
                except:
                    logger.error("Cannot send error message: client disconnected")

        except websockets.exceptions.WebSocketException as e:
            error_msg = f"WebSocket error: {str(e)}"
            logger.error(f"{error_msg}")
            if client_connected:
                try:
                    await ws_client.send_json({"error": error_msg})
                except:
                    logger.error("Cannot send error message: client disconnected")

        except Exception as e:
            error_msg = f"Error in streaming session: {str(e)}"
            logger.error(f"{error_msg}")
            import traceback
            traceback.print_exc()
            if client_connected:
                try:
                    await ws_client.send_json({"error": error_msg})
                except:
                    logger.error("Cannot send error message: client disconnected")

        finally:
            logger.info("Audio processing loop ended")

    async def start_streaming_session(self, ws_client):
        """Start a streaming session for real-time STT."""
        logger.info("Preparing streaming session...")
        segment_size = int(self.config.rate * self.config.bits * self.config.channel / 8 * 0.1)
        logger.info(f"Using segment size: {segment_size} bytes")

        try:
            await self.process_streaming_audio(ws_client, segment_size)

        except Exception as e:
            error_msg = f"Error in streaming session: {str(e)}"
            logger.error(f"{error_msg}")
            import traceback
            traceback.print_exc()
            await ws_client.send_json({"error": error_msg})

    async def recognize_file(self, audio_path: str) -> Dict[str, Any]:
        """Recognize speech from audio file."""
        return await self.process_audio_file(audio_path)

    async def check_connectivity(self) -> bool:
        """Test if the connection to the remote STT service is normal."""
        try:
            logger.info(f"STT connectivity test started with config: ws_url={self.config.ws_url}")
            logger.info(f"Test voice file path: {self.audio_file_path}")

            if not self.audio_file_path:
                logger.warning("No test voice file path provided")
                return False

            result = await self.process_audio_file(self.audio_file_path)
            logger.info(f"STT process_audio_file result: {result}")

            is_success = self._is_stt_result_successful(result)

            if is_success:
                logger.info("STT connectivity test successful")
            else:
                error_msg = self._extract_stt_error_message(result)
                logger.error(f"STT connectivity test failed with error: {error_msg}")

            return is_success
        except Exception as e:
            logger.error(f"STT connectivity test failed with exception: {str(e)}")
            import traceback
            logger.error(f"STT connectivity test exception traceback: {traceback.format_exc()}")
            return False

    async def invoke(self, request: STTRequest) -> Dict[str, Any]:
        return await self.recognize_file(request.audio_path)

    async def stream(self, request: STTStreamRequest) -> AsyncIterator[Dict[str, Any]]:
        await self.start_streaming_session(request.websocket)
        return
        yield  # pragma: no cover

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
# ModelEngine STT — HTTP REST, audio → base64 → Chat Completions.
# _inner is OpenAIModel (kept per §3.16 LLM exception); audio↔base64 conversion
# lives in the adapter's invoke.
# ============================================================================

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
