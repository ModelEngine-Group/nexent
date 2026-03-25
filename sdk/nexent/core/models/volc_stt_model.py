import asyncio
import base64
import datetime
import gzip
import json
import logging
import time
import uuid
import wave
from io import BytesIO
from typing import Any, Dict, Optional

import aiofiles
import websockets

from .stt_model import BaseSTTModel

logger = logging.getLogger("volc_stt_model")

# Protocol constants
PROTOCOL_VERSION = 0b0001
DEFAULT_HEADER_SIZE = 0b0001

# Message Type:
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


class VolcSTTModel(BaseSTTModel):
    """
    Volcano Engine STT model implementation using proprietary protocol.

    This class handles real-time speech recognition using the Volcano Engine
    (ByteDance) speech-to-text service.
    """

    def __init__(self, config: VolcSTTConfig, audio_file_path: Optional[str] = None):
        """
        Initialize the Volcano Engine STT model.

        Args:
            config: STT configuration for Volcano Engine
            audio_file_path: Path to test audio file for connectivity testing
        """
        super().__init__(audio_file_path)
        self.config = config
        self.success_code = 1000

    def get_websocket_url(self) -> str:
        """
        Get the WebSocket URL for the STT service.

        Returns:
            WebSocket URL
        """
        return self.config.ws_url

    def get_auth_headers(self) -> Dict[str, str]:
        """
        Get authentication headers for the WebSocket connection.

        Returns:
            Headers dict with X-Api-Access-Key and X-Api-App-Key
        """
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
        """
        Generate protocol header.

        Args:
            message_type: Message type
            message_type_specific_flags: Message type specific flags
            serial_method: Serialization method
            compression_type: Compression type (optional)
            reserved_data: Reserved data

        Returns:
            Header bytes
        """
        if compression_type is None:
            compression_type = GZIP if self.config.compression else NO_COMPRESSION

        header = bytearray()
        header_size = 1
        header.append((PROTOCOL_VERSION << 4) | header_size)
        header.append((message_type << 4) | message_type_specific_flags)
        header.append((serial_method << 4) | compression_type)
        header.append(reserved_data)
        return header

    @staticmethod
    def generate_before_payload(sequence: int) -> bytearray:
        """
        Generate the payload prefix with sequence number.

        Args:
            sequence: Sequence number

        Returns:
            Payload prefix bytes
        """
        before_payload = bytearray()
        before_payload.extend(sequence.to_bytes(4, 'big', signed=True))
        return before_payload

    def parse_response(self, res: bytes) -> Dict[str, Any]:
        """
        Parse response from server.

        Args:
            res: Response bytes

        Returns:
            Parsed response dict
        """
        protocol_version = res[0] >> 4
        header_size = res[0] & 0x0f
        message_type = res[1] >> 4
        message_type_specific_flags = res[1] & 0x0f
        serialization_method = res[2] >> 4
        message_compression = res[2] & 0x0f
        reserved = res[3]
        header_extensions = res[4:header_size * 4]
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

        if serialization_method == JSON:
            payload_msg = json.loads(str(payload_msg, "utf-8"))
        elif serialization_method != NO_SERIALIZATION:
            payload_msg = str(payload_msg, "utf-8")

        result['payload_msg'] = payload_msg
        result['payload_size'] = payload_size
        return result

    @staticmethod
    def read_wav_info(data: bytes) -> tuple:
        """
        Read WAV file information.

        Args:
            data: WAV file data

        Returns:
            Tuple of (channels, sample width, frame rate, frames, wave bytes)
        """
        with BytesIO(data) as _f:
            wave_fp = wave.open(_f, 'rb')
            nchannels, sampwidth, framerate, nframes = wave_fp.getparams()[:4]
            wave_bytes = wave_fp.readframes(nframes)
        return nchannels, sampwidth, framerate, nframes, wave_bytes

    @staticmethod
    def slice_data(data: bytes, chunk_size: int):
        """
        Slice data into chunks.

        Args:
            data: Data to slice
            chunk_size: Chunk size

        Yields:
            Tuple of (chunk, last flag)
        """
        data_len = len(data)
        offset = 0
        while offset + chunk_size < data_len:
            yield data[offset: offset + chunk_size], False
            offset += chunk_size
        else:
            yield data[offset: data_len], True

    def construct_request(self, reqid: str) -> Dict[str, Any]:
        """
        Construct request parameters.

        Args:
            reqid: Request ID

        Returns:
            Request parameters dict
        """
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
        """
        Process audio data and perform speech recognition.

        Args:
            audio_data: Audio data bytes
            segment_size: Segment size

        Returns:
            Recognition result
        """
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
        """
        Process audio file and perform speech recognition.

        Args:
            audio_path: Path to audio file

        Returns:
            Recognition result
        """
        async with aiofiles.open(audio_path, mode="rb") as _f:
            data = await _f.read()
        audio_data = bytes(data)

        if self.config.format == "mp3":
            segment_size = self.config.mp3_seg_size
            return await self.process_audio_data(audio_data, segment_size)

        if self.config.format == "wav":
            nchannels, sampwidth, framerate, nframes, wav_bytes = self.read_wav_info(audio_data)
            size_per_sec = nchannels * sampwidth * framerate
            segment_size = int(size_per_sec * self.config.seg_duration / 1000)
            return await self.process_audio_data(wav_bytes, segment_size)

        if self.config.format == "pcm":
            segment_size = int(self.config.rate * 2 * self.config.channel * self.config.seg_duration / 500)
            return await self.process_audio_data(audio_data, segment_size)

        raise Exception("Unsupported format, only wav, mp3, and pcm are supported")

    async def process_streaming_audio(self, ws_client, segment_size: int):
        """
        Process streaming audio from WebSocket client and send transcription back.

        Args:
            ws_client: Client WebSocket connection
            segment_size: Audio segment size
        """
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

                counter = 0
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

                    counter += 1

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
        """
        Start a streaming session for real-time STT.

        Args:
            ws_client: Client WebSocket connection
        """
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
        Test if the connection to the remote STT service is normal.

        Returns:
            True if connection successful, False otherwise
        """
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
