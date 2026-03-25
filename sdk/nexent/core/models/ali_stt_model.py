import asyncio
import base64
import json
import logging
import time
import uuid
from io import BytesIO
from typing import Any, Callable, Dict, List, Optional

import aiofiles
import websockets
import wave

from .stt_model import BaseSTTModel

logger = logging.getLogger(__name__)


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
        workspace_id: Optional[str] = None
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
        self.workspace_id = workspace_id


class TranscriptionResult:
    """Container for transcription results."""

    def __init__(self):
        self.text: str = ""
        self.is_final: bool = False
        self.error: Optional[str] = None
        self.vad: Optional[str] = None


class AliSTTModel(BaseSTTModel):
    """Ali STT model implementation using Qwen Realtime API protocol."""

    def __init__(self, config: AliSTTConfig, audio_file_path: Optional[str] = None):
        super().__init__(audio_file_path)
        self.config = config
        self._current_result = TranscriptionResult()

    def get_websocket_url(self) -> str:
        """
        Get the WebSocket URL for the STT service.

        Returns:
            WebSocket URL
        """
        if self.config.ws_url:
            return f"{self.config.ws_url}?model={self.config.model}"
        return f"wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model={self.config.model}"

    def get_auth_headers(self) -> Dict[str, str]:
        """
        Get authentication headers for the WebSocket connection.

        Returns:
            Headers dict with authorization
        """
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "OpenAI-Beta": "realtime=v1"
        }
        if self.config.workspace_id:
            headers["X-DashScope-WorkSpace"] = self.config.workspace_id
        return headers

    def generate_event_id(self) -> str:
        """
        Generate a unique event ID.

        Returns:
            UUID string
        """
        return f"event_{uuid.uuid4().hex[:16]}"

    def construct_session_update(self) -> Dict[str, Any]:
        """
        Construct the session.update event.

        Returns:
            Session update event dict
        """
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
        """
        Construct the input_audio_buffer.append event with base64 encoded audio.

        Args:
            audio_data: Raw audio bytes

        Returns:
            Audio append event dict
        """
        audio_b64 = base64.b64encode(audio_data).decode('utf-8')
        return {
            "event_id": self.generate_event_id(),
            "type": "input_audio_buffer.append",
            "audio": audio_b64
        }

    def construct_audio_commit_event(self) -> Dict[str, Any]:
        """
        Construct the input_audio_buffer.commit event.

        Returns:
            Audio commit event dict
        """
        return {
            "event_id": self.generate_event_id(),
            "type": "input_audio_buffer.commit"
        }

    def construct_session_finish_event(self) -> Dict[str, Any]:
        """
        Construct the session.finish event.

        Returns:
            Session finish event dict
        """
        return {
            "event_id": self.generate_event_id(),
            "type": "session.finish"
        }

    async def _handle_stt_event(self, result: Dict[str, Any], websocket: Any, transcription_texts: List[str]) -> bool:
        """
        Handle STT server event and return True if session should end.

        Returns:
            True if session should terminate, False otherwise
        """
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
        """
        Parse the response from the STT service.

        Args:
            response: Response from WebSocket

        Returns:
            Parsed result dict
        """
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
        """
        Read WAV file information.

        Args:
            data: WAV file data

        Returns:
            Tuple of (channels, sample width, frame rate, nframes, wave bytes)
        """
        with BytesIO(data) as _f:
            wave_fp = wave.open(_f, 'rb')
            nchannels, sampwidth, framerate, nframes = wave_fp.getparams()[:4]
            wave_bytes = wave_fp.readframes(nframes)
        return nchannels, sampwidth, framerate, nframes, wave_bytes

    @staticmethod
    def slice_data(data: bytes, chunk_size: int):
        """
        Slice audio data into chunks.

        Args:
            data: Audio data bytes
            chunk_size: Size of each chunk

        Yields:
            Tuple of (chunk bytes, is_last flag)
        """
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
        """
        Process audio file and perform speech recognition.

        Args:
            audio_path: Path to audio file
            on_result: Optional callback for streaming results

        Returns:
            Recognition result
        """
        async with aiofiles.open(audio_path, mode="rb") as _f:
            data = await _f.read()
        audio_data = bytes(data)

        if self.config.format == "wav":
            nchannels, sampwidth, framerate, nframes, wav_bytes = self.read_wav_info(audio_data)
            size_per_sec = nchannels * sampwidth * framerate
            segment_size = int(size_per_sec * self.config.seg_duration / 1000)
            return await self.process_audio_data(wav_bytes, segment_size, on_result)

        if self.config.format == "pcm":
            if audio_data[:4] == b'RIFF' and audio_data[8:12] == b'WAVE':
                nchannels, sampwidth, framerate, nframes, wav_bytes = self.read_wav_info(audio_data)
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
        """
        Process audio data and perform speech recognition using Qwen Realtime API.

        Args:
            audio_data: Audio data bytes
            segment_size: Segment size in bytes
            on_result: Optional callback for streaming results

        Returns:
            Recognition result
        """
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
        """
        Recognize speech from audio file.

        Args:
            audio_path: Path to audio file

        Returns:
            Recognition result
        """
        return await self.process_audio_file(audio_path)

    async def check_connectivity(self) -> bool:
        """
        Check if the STT service is accessible.

        Returns:
            True if connected successfully, False otherwise
        """
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
        """
        Start a streaming session for real-time STT.
        Processing logic aligned with official Ali VAD example.

        Args:
            websocket: WebSocket connection to client
            config_received: Whether the config was already received externally (default: True)
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
                # VAD settings: threshold 0.5 (balanced), silence 2000ms (wait longer before ending turn)
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
