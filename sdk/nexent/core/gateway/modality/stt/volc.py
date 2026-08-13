"""Volc STT adapter (proprietary binary-frame WebSocket)."""

from __future__ import annotations

import asyncio
import datetime
import gzip
import json
import time
import traceback
import uuid
import wave
import aiofiles
import websockets
import logging
from io import BytesIO
from typing import Any, AsyncIterator, Dict

from ...multimodal_adapter import MultimodalAdapter, ModelInfo
from ...model_context import STTContext
from ...registry import register_adapter
from ...transport import WebSocketTransportMixin
from .base import STTAdapter, STTRequest, STTStreamRequest

logger = logging.getLogger(__name__)

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
        """Initialize the Volcano Engine STT configuration.

        Args:
            appid: The Volcano application ID.
            access_token: The access token for authentication.
            ws_url: The SAUC WebSocket endpoint.
            uid: The client user ID.
            format: Audio input format.
            rate: Audio sample rate in Hz.
            bits: Audio bit depth.
            channel: Number of audio channels.
            codec: Audio codec.
            seg_duration: Segment duration in milliseconds.
            mp3_seg_size: Chunk size for mp3 audio.
            resourceid: The BigASR SAUC resource ID.
            streaming: Whether to throttle sending to streaming rate.
            compression: Whether to gzip-compress payloads.
        """
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

    Attributes:
        factory: ``"volc"``.
        _config: The :class:`VolcSTTConfig` for this adapter.
        _audio_file_path: Path to the connectivity-test audio file.
        success_code: The Volc success status code (``1000``).
    """

    factory = "volc"

    def __init__(self, context: STTContext) -> None:
        MultimodalAdapter.__init__(self, context)
        WebSocketTransportMixin.__init__(
            self,
            ws_url=context.ws.ws_url if context.ws else None,
            auth_headers=context.ws.auth_headers if context.ws else None,
        )
        self._config = VolcSTTConfig(
            appid=context.model_appid or "",
            access_token=context.access_token or "",
            ws_url=self._ws_url or "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel",
            format=context.extra.get("format", "pcm"),
            rate=context.extra.get("rate", 16000),
            resourceid=context.extra.get(
                "resourceid", "volc.bigasr.sauc.duration"
            ),
        )
        self._audio_file_path = context.audio_file_path
        self.success_code = 1000

    def get_websocket_url(self) -> str:
        """Get the WebSocket URL for the STT service."""
        return self._config.ws_url

    def get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers for the WebSocket connection."""
        headers = {
            "X-Api-Resource-Id": self._config.resourceid,
            "X-Api-Connect-Id": str(uuid.uuid4())
        }

        if self._config.access_token:
            headers["X-Api-Access-Key"] = self._config.access_token

        if self._config.appid:
            headers["X-Api-App-Key"] = self._config.appid

        return headers

    def generate_header(self, message_type=CLIENT_FULL_REQUEST,
                        message_type_specific_flags=NO_SEQUENCE,
                        serial_method=JSON, compression_type=None,
                        reserved_data=0x00) -> bytearray:
        """Generate a SAUC protocol header.

        Args:
            message_type: The message type bits.
            message_type_specific_flags: The message-type-specific flag bits.
            serial_method: The serialization method bits.
            compression_type: The compression bits; defaults to GZIP or none per config.
            reserved_data: The reserved header byte.

        Returns:
            The 4-byte protocol header as a bytearray.
        """
        if compression_type is None:
            compression_type = GZIP if self._config.compression else NO_COMPRESSION

        header = bytearray()
        header_size = 1
        header.append((PROTOCOL_VERSION << 4) | header_size)
        header.append((message_type << 4) | message_type_specific_flags)
        header.append((serial_method << 4) | compression_type)
        header.append(reserved_data)
        return header

    def generate_before_payload(self, sequence: int) -> bytearray:
        """Generate the sequence-number prefix prepended to a payload.

        Args:
            sequence: The signed 32-bit sequence number; negative marks the last chunk.

        Returns:
            The 4-byte big-endian sequence prefix as a bytearray.
        """
        before_payload = bytearray()
        before_payload.extend(sequence.to_bytes(4, 'big', signed=True))
        return before_payload

    def parse_response(self, res: bytes) -> Dict[str, Any]:
        """Parse a SAUC binary-gzip frame from the server.

        Args:
            res: The raw binary response frame.

        Returns:
            A dict with the parsed header fields, payload metadata, and decoded
            ``payload_msg``.
        """
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
        """Read WAV file information.

        Args:
            data: The raw WAV file bytes.

        Returns:
            A tuple of ``(nchannels, sampwidth, framerate, nframes, wave_bytes)``.
        """
        with BytesIO(data) as _f:
            wave_fp = wave.open(_f, 'rb')
            nchannels, sampwidth, framerate, nframes = wave_fp.getparams()[:4]
            wave_bytes = wave_fp.readframes(nframes)
        return nchannels, sampwidth, framerate, nframes, wave_bytes

    @staticmethod
    def slice_data(data: bytes, chunk_size: int):
        """Slice data into chunks.

        Args:
            data: The bytes to slice.
            chunk_size: The maximum byte size of each chunk.

        Yields:
            Tuples of ``(chunk, is_last)``.
        """
        data_len = len(data)
        offset = 0
        while offset + chunk_size < data_len:
            yield data[offset: offset + chunk_size], False
            offset += chunk_size
        yield data[offset: data_len], True

    def construct_request(self, reqid: str) -> Dict[str, Any]:
        """Construct the full-request parameters.

        Args:
            reqid: The request ID used as the connect ID.

        Returns:
            The request parameter dict.
        """
        req = {
            "user": {"uid": self._config.uid},
            "audio": {
                'format': self._config.format,
                "sample_rate": self._config.rate,
                "bits": self._config.bits,
                "channel": self._config.channel,
                "codec": self._config.codec
            },
            "request": {
                "model_name": "bigmodel",
                "enable_punc": True
            }
        }
        logger.info(f"req: {req}")
        return req

    async def process_audio_data(self, audio_data: bytes, segment_size: int) -> Dict[str, Any]:
        """Process audio data over the SAUC WebSocket.

        Args:
            audio_data: Raw audio bytes to transcribe.
            segment_size: Byte size of each audio chunk sent to the server.

        Returns:
            A dict with the recognition result or an ``error`` key on failure.
        """
        reqid = str(uuid.uuid4())
        seq = 1

        request_params = self.construct_request(reqid)
        payload_bytes = str.encode(json.dumps(request_params))

        if self._config.compression:
            payload_bytes = gzip.compress(payload_bytes)

        full_client_request = bytearray(self.generate_header(message_type_specific_flags=POS_SEQUENCE))
        full_client_request.extend(self.generate_before_payload(sequence=seq))
        full_client_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
        full_client_request.extend(payload_bytes)

        headers = self.get_auth_headers()
        headers["X-Api-Connect-Id"] = reqid
        logger.info(f"Connecting to {self._config.ws_url} with headers: {headers}")

        try:
            async with websockets.connect(self._config.ws_url, additional_headers=headers,
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

                    if self._config.compression:
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

                    if self._config.streaming:
                        sleep_time = max(0.0, self._config.seg_duration / 1000.0 - (time.time() - start))
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
            traceback.print_exc()
            return {"error": f"Unexpected error: {str(e)}"}

    async def process_audio_file(self, audio_path: str) -> Dict[str, Any]:
        """Process an audio file and perform speech recognition.

        Args:
            audio_path: Path to the audio file to transcribe.

        Returns:
            A dict with a ``text`` key on success or an ``error`` key on failure.
        """
        async with aiofiles.open(audio_path, mode="rb") as _f:
            data = await _f.read()
        audio_data = bytes(data)

        if self._config.format == "mp3":
            segment_size = self._config.mp3_seg_size
            return await self.process_audio_data(audio_data, segment_size)

        if self._config.format == "wav":
            nchannels, sampwidth, framerate, _, wav_bytes = self.read_wav_info(audio_data)
            size_per_sec = nchannels * sampwidth * framerate
            segment_size = int(size_per_sec * self._config.seg_duration / 1000)
            return await self.process_audio_data(wav_bytes, segment_size)

        if self._config.format == "pcm":
            segment_size = int(self._config.rate * 2 * self._config.channel * self._config.seg_duration / 500)
            return await self.process_audio_data(audio_data, segment_size)

        raise Exception("Unsupported format, only wav, mp3, and pcm are supported")

    async def process_streaming_audio(self, ws_client, segment_size: int):
        """Process streaming audio from a WebSocket client and send transcription back.

        Args:
            ws_client: The client websocket receiving audio and results.
            segment_size: Byte size of each audio chunk sent to the server.
        """
        logger.info("Starting audio processing loop...")
        reqid = str(uuid.uuid4())
        seq = 1
        client_connected = True

        request_params = self.construct_request(reqid)
        payload_bytes = str.encode(json.dumps(request_params))

        if self._config.compression:
            payload_bytes = gzip.compress(payload_bytes)

        full_client_request = bytearray(self.generate_header(message_type_specific_flags=POS_SEQUENCE))
        full_client_request.extend(self.generate_before_payload(sequence=seq))
        full_client_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
        full_client_request.extend(payload_bytes)

        headers = self.get_auth_headers()
        headers["X-Api-Connect-Id"] = reqid
        logger.info(f"Request headers: {headers}")

        try:
            async with websockets.connect(self._config.ws_url, additional_headers=headers,
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

                    if self._config.compression:
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

                    if self._config.streaming:
                        sleep_time = max(0, (self._config.seg_duration / 1000.0))
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
            traceback.print_exc()
            if client_connected:
                try:
                    await ws_client.send_json({"error": error_msg})
                except:
                    logger.error("Cannot send error message: client disconnected")

        finally:
            logger.info("Audio processing loop ended")

    async def start_streaming_session(self, ws_client):
        """Start a real-time streaming transcription session.

        Args:
            ws_client: The client websocket to receive audio from and send results to.
        """
        logger.info("Preparing streaming session...")
        segment_size = int(self._config.rate * self._config.bits * self._config.channel / 8 * 0.1)
        logger.info(f"Using segment size: {segment_size} bytes")

        try:
            await self.process_streaming_audio(ws_client, segment_size)

        except Exception as e:
            error_msg = f"Error in streaming session: {str(e)}"
            logger.error(f"{error_msg}")
            traceback.print_exc()
            await ws_client.send_json({"error": error_msg})

    async def recognize_file(self, audio_path: str) -> Dict[str, Any]:
        """Recognize speech from an audio file.

        Args:
            audio_path: Path to the audio file to transcribe.

        Returns:
            A dict with a ``text`` key on success or an ``error`` key on failure.
        """
        return await self.process_audio_file(audio_path)

    async def check_connectivity(self) -> bool:
        """Test if the connection to the remote STT service is normal."""
        try:
            logger.info(f"STT connectivity test started with config: ws_url={self._config.ws_url}")
            logger.info(f"Test voice file path: {self._audio_file_path}")

            if not self._audio_file_path:
                logger.warning("No test voice file path provided")
                return False

            result = await self.process_audio_file(self._audio_file_path)
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
            logger.error(f"STT connectivity test exception traceback: {traceback.format_exc()}")
            return False

    async def invoke(self, request: STTRequest) -> Dict[str, Any]:
        """Transcribe ``request.audio_path``; returns ``{"text": ...}`` or ``{"error": ...}``."""
        return await self.recognize_file(request.audio_path)

    async def stream(self, request: STTStreamRequest) -> AsyncIterator[Dict[str, Any]]:
        """Run the streaming session to completion (no incremental yields)."""
        await self.start_streaming_session(request.websocket)
        return
        yield  # pragma: no cover

    async def health_check(self) -> bool:
        """Delegate to :meth:`check_connectivity`."""
        return await self.check_connectivity()

    def get_model_info(self) -> ModelInfo:
        """Return ``ModelInfo`` with audio + realtime capabilities."""
        return ModelInfo(
            model_id=self._context.model_name,
            display_name=self._context.display_name or "",
            provider=self.factory,
            capabilities={"audio": True, "realtime": True},
        )

