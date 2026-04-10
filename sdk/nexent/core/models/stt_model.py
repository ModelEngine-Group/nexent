import asyncio
import datetime
import gzip
import json
import logging
import time
import uuid
import wave
from enum import Enum
from io import BytesIO
from typing import Dict, Any

import aiofiles
import websockets
from pydantic import BaseModel

logger = logging.getLogger("stt_model")

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
NO_SEQUENCE = 0b0000  # no check sequence
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


class AudioType(Enum):
    LOCAL = 1  # Use local audio file
    STREAM = 2  # Use streaming audio


class STTConfig(BaseModel):
    appid: str
    token: str
    ws_url: str = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
    uid: str = "streaming_asr_demo"
    format: str = "pcm"
    rate: int = 16000
    bits: int = 16
    channel: int = 1
    codec: str = "raw"
    seg_duration: int = 10
    mp3_seg_size: int = 1000
    resourceid: str = "volc.bigasr.sauc.duration"
    streaming: bool = True
    compression: bool = True


class STTModel:
    def __init__(self, config: STTConfig, test_voice_path: str):
        """
        Initialize the STT Model.
        
        Args:
            config: STT configuration
            test_voice_path: Path to test voice file for connectivity testing
        """
        self.config = config
        self.test_voice_path = test_voice_path
        self.success_code = 1000  # success code, default is 1000

    def generate_header(self, message_type=CLIENT_FULL_REQUEST, message_type_specific_flags=NO_SEQUENCE,
            serial_method=JSON, compression_type=None, reserved_data=0x00):
        """
        Generate protocol header.
        
        Args:
            message_type: Message type
            message_type_specific_flags: Message type specific flags
            serial_method: Serialization method
            compression_type: Compression type (optional, uses config if None)
            reserved_data: Reserved data
            
        Returns:
            Header bytes
        """
        # Use compression setting from config
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
    def generate_before_payload(sequence: int):
        """
        Generate the payload prefix with sequence number.
        
        Args:
            sequence: Sequence number
            
        Returns:
            Payload prefix bytes
        """
        before_payload = bytearray()
        before_payload.extend(sequence.to_bytes(4, 'big', signed=True))  # sequence
        return before_payload

    @staticmethod
    def parse_response(res):
        """
        Parse response from server.
        
        Args:
            res: Response bytes
            
        Returns:
            Parsed response
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
        result = {'is_last_package': False, }
        payload_msg = None
        payload_size = 0

        if message_type_specific_flags & 0x01:
            # Receive frame with sequence
            seq = int.from_bytes(payload[:4], "big", signed=True)
            result['payload_sequence'] = seq
            payload = payload[4:]

        if message_type_specific_flags & 0x02:
            # Receive last package
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
    def read_wav_info(data: bytes = None) -> tuple[int, int, int, int, bytes]:
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

    def construct_request(self, reqid):
        """
        Construct request parameters.
        
        Args:
            reqid: Request ID
            
        Returns:
            Request parameters dict
        """
        req = {"user": {"uid": self.config.uid, },
            "audio": {'format': self.config.format, "sample_rate": self.config.rate, "bits": self.config.bits,
                "channel": self.config.channel, "codec": self.config.codec, },
            "request": {"model_name": "bigmodel", "enable_punc": True, # "result_type": "single",
                # "vad_segment_duration": 800,
            }}
        logger.info(f"req: {req}\n")
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

        # Construct full client request, then serialize and compress
        request_params = self.construct_request(reqid)
        payload_bytes = str.encode(json.dumps(request_params))

        # According to config, decide whether to compress
        if self.config.compression:
            payload_bytes = gzip.compress(payload_bytes)

        full_client_request = bytearray(self.generate_header(message_type_specific_flags=POS_SEQUENCE))
        full_client_request.extend(self.generate_before_payload(sequence=seq))
        full_client_request.extend((len(payload_bytes)).to_bytes(4, 'big'))  # Payload size (4 bytes)
        full_client_request.extend(payload_bytes)  # payload

        # Prepare headers
        header = {"X-Api-Resource-Id": self.config.resourceid, "X-Api-Connect-Id": reqid}

        if self.config.token:
            header["X-Api-Access-Key"] = self.config.token

        if self.config.appid:
            header["X-Api-App-Key"] = self.config.appid

        logger.info(f"Connecting to {self.config.ws_url} with headers: {header}")

        try:
            # Fix: Use additional_headers instead of extra_headers for websockets 15.0.1+
            async with websockets.connect(self.config.ws_url, additional_headers=header, max_size=1000000000) as ws:
                # Send full client request
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

                    # According to config, decide whether to compress
                    if self.config.compression:
                        payload_bytes = gzip.compress(chunk)
                    else:
                        payload_bytes = chunk

                    if last:
                        audio_only_request = bytearray(self.generate_header(message_type=CLIENT_AUDIO_ONLY_REQUEST,
                            message_type_specific_flags=NEG_WITH_SEQUENCE))
                    else:
                        audio_only_request = bytearray(self.generate_header(message_type=CLIENT_AUDIO_ONLY_REQUEST,
                            message_type_specific_flags=POS_SEQUENCE))

                    audio_only_request.extend(self.generate_before_payload(sequence=seq))
                    audio_only_request.extend((len(payload_bytes)).to_bytes(4, 'big'))  # Payload size (4 bytes)
                    audio_only_request.extend(payload_bytes)  # payload

                    # Send audio-only client request
                    await ws.send(audio_only_request)
                    res = await ws.recv()
                    result = self.parse_response(res)

                    logger.info(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}, seq: {seq}, result: {result}")

                    if self.config.streaming:
                        sleep_time = max(0.0, self.config.seg_duration / 1000.0 - (time.time() - start))
                        await asyncio.sleep(sleep_time)

            return result

        except websockets.exceptions.ConnectionClosedError as e:
            logger.error(f"WebSocket connection closed with status code: {e.code}")
            logger.error(f"WebSocket connection closed with reason: {e.reason}")
            return {"error": f"Connection closed: {e.reason}"}

        except websockets.exceptions.WebSocketException as e:
            logger.error(f"WebSocket connection failed: {e}")
            if hasattr(e, "status_code"):
                logger.error(f"Response status code: {e.status_code}")
            if hasattr(e, "headers"):
                logger.error(f"Response headers: {e.headers}")
            if hasattr(e, "response") and hasattr(e.response, "text"):
                logger.error(f"Response body: {e.response.text}")
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
            return await self.process_audio_data(audio_data, segment_size)

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
            
        Returns:
            None
        """
        logger.info("Starting audio processing loop...")
        reqid = str(uuid.uuid4())
        seq = 1
        client_connected = True  # Track client connection status

        # Construct full client request
        request_params = self.construct_request(reqid)
        payload_bytes = str.encode(json.dumps(request_params))

        # According to config, decide whether to compress
        if self.config.compression:
            payload_bytes = gzip.compress(payload_bytes)

        # Generate request header, pass None to let the function decide compression_type based on config
        full_client_request = bytearray(self.generate_header(message_type_specific_flags=POS_SEQUENCE))
        full_client_request.extend(self.generate_before_payload(sequence=seq))
        full_client_request.extend((len(payload_bytes)).to_bytes(4, 'big'))  # Payload size (4 bytes)
        full_client_request.extend(payload_bytes)  # payload

        # Prepare headers
        header = {"X-Api-Resource-Id": self.config.resourceid, "X-Api-Request-Id": reqid}

        if self.config.token:
            header["X-Api-Access-Key"] = self.config.token

        if self.config.appid:
            header["X-Api-App-Key"] = self.config.appid

        logger.info(f"Config: {self.config}")

        try:
            # Connect to STT service
            logger.info(f"Connecting to STT WebSocket service at {self.config.ws_url}...")
            # Fix: Use additional_headers instead of extra_headers for websockets 15.0.1+
            async with websockets.connect(self.config.ws_url, additional_headers=header,
                                          max_size=1000000000) as ws_server:
                logger.info("Connected to STT service")
                if hasattr(ws_server, 'response_headers'):
                    logger.info(f"Response headers: {ws_server.response_headers}")

                # Send initial request
                logger.info("Sending initial request...")
                await ws_server.send(full_client_request)
                logger.info("Waiting for response...")
                response = await ws_server.recv()
                result = self.parse_response(response)
                logger.info(f"Initial response received")

                # Tell client we're ready to receive audio
                logger.info("Sending ready status to client...")
                try:
                    await ws_client.send_json({"status": "ready"})
                except Exception as e:
                    logger.error(f"Client disconnected: {e}")
                    client_connected = False
                    return

                # Process streaming audio chunks
                counter = 0
                last_chunk_received = False

                while client_connected:
                    # Listen for audio data from client
                    try:
                        client_data = await ws_client.receive_bytes()
                    except Exception as e:
                        logger.error(f"Error receiving audio data: {str(e)}")
                        client_connected = False
                        break

                    if not client_data:
                        logger.info("Received empty audio data, indicating end of stream")
                        last_chunk_received = True
                        # Send a small empty buffer as the final chunk
                        client_data = bytes(0)

                    # Next sequence number
                    seq += 1

                    # Only use negative sequence for explicitly marked last chunk
                    if last_chunk_received:
                        seq = -abs(seq)  # Make sequence negative for last chunk
                        logger.info("This is the final chunk, using negative sequence")

                        audio_only_request = bytearray(self.generate_header(message_type=CLIENT_AUDIO_ONLY_REQUEST,
                            message_type_specific_flags=NEG_WITH_SEQUENCE))
                    else:
                        audio_only_request = bytearray(self.generate_header(message_type=CLIENT_AUDIO_ONLY_REQUEST,
                            message_type_specific_flags=POS_SEQUENCE))

                    # According to config, decide whether to compress
                    if self.config.compression:
                        payload_bytes = gzip.compress(client_data)
                    else:
                        payload_bytes = client_data

                    audio_only_request.extend(self.generate_before_payload(sequence=seq))
                    audio_only_request.extend((len(payload_bytes)).to_bytes(4, 'big'))  # Payload size (4 bytes)
                    audio_only_request.extend(payload_bytes)  # payload

                    # Send to STT service
                    logger.info(f"Sending audio chunk {counter + 1} to STT service ({len(audio_only_request)} bytes)...")
                    try:
                        await ws_server.send(audio_only_request)
                    except Exception as e:
                        logger.error(f"Error sending to STT service: {e}")
                        if client_connected:
                            try:
                                await ws_client.send_json({"error": f"STT service error: {str(e)}"})
                                client_connected = False
                            except Exception:
                                pass
                        break

                    # Get response and parse
                    try:
                        response = await ws_server.recv()
                        result = self.parse_response(response)
                        result_text = "empty"
                        try:
                            result_text = result['payload_msg']['result']['text'] if result['payload_msg']['result'][
                                'text'] else "empty"
                        except Exception:
                            logger.error(f"Malformed result: {result}")
                        logger.info(f"Received response: {result_text}")

                        # Send result back to client
                        if client_connected and 'payload_msg' in result:
                            payload = result['payload_msg']

                            # Fix empty text results by adding a status indicator
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
                            logger.error("Expected closure after final chunk")
                            break
                        elif client_connected:
                            try:
                                await ws_client.send_json({"error": f"STT service connection closed unexpectedly: {e}"})
                                client_connected = False
                            except Exception:
                                pass
                            break

                    counter += 1

                    # Exit after processing the last chunk
                    if last_chunk_received:
                        logger.info("Last chunk processed, exiting loop")
                        break

                    # Simulate real-time processing if needed
                    if self.config.streaming:
                        sleep_time = max(0, (self.config.seg_duration / 1000.0))
                        await asyncio.sleep(sleep_time)

        except websockets.exceptions.ConnectionClosedError as e:
            error_msg = f"WebSocket connection closed: {e.reason} (code: {e.code})"
            logger.error(f"{error_msg}")
            if client_connected:
                try:
                    await ws_client.send_json({"error": error_msg})
                except Exception:
                    logger.error("Cannot send error message: client disconnected")

        except websockets.exceptions.WebSocketException as e:
            error_msg = f"WebSocket error: {str(e)}"
            logger.error(f"{error_msg}")
            if client_connected:
                try:
                    await ws_client.send_json({"error": error_msg})
                except Exception:
                    logger.error("Cannot send error message: client disconnected")

        except Exception as e:
            error_msg = f"Error in streaming session: {str(e)}"
            logger.error(f"{error_msg}")
            import traceback
            traceback.print_exc()
            if client_connected:
                try:
                    await ws_client.send_json({"error": error_msg})
                except Exception:
                    logger.error("Cannot send error message: client disconnected")

        finally:
            logger.info("Audio processing loop ended")

    async def start_streaming_session(self, ws_client):
        """
        Start a streaming session for real-time STT.
        
        Args:
            ws_client: Client WebSocket connection
            
        Returns:
            None
        """
        logger.info("Preparing streaming session...")
        # Calculate segment size based on audio parameters
        segment_size = int(self.config.rate * self.config.bits * self.config.channel / 8 * 0.1)  # 100ms chunk
        logger.info(f"Using segment size: {segment_size} bytes (100ms of audio)")

        try:
            # Process streaming audio
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
        Test if the connection to the remote STT service is normal
            
        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            logger.info(f"STT connectivity test started with config: ws_url={self.config.ws_url}, format={self.config.format}")
            logger.info(f"Test voice file path: {self.test_voice_path}")
            
            result = await self.process_audio_file(self.test_voice_path)
            logger.info(f"STT process_audio_file result: {result}")
            
            # Check if the return result indicates success
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

    def _is_stt_result_successful(self, result) -> bool:
        """
        Check if STT result indicates a successful recognition
        
        Args:
            result: STT processing result
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not isinstance(result, dict) or not result:
            return False
            
        # Check for direct error field
        if 'error' in result:
            return False
            
        # Check for error code (STT service uses codes like 45000081 for errors)
        if 'code' in result and result['code'] != 1000:  # 1000 is success code
            return False
            
        # Check for nested error in payload_msg
        if 'payload_msg' in result and isinstance(result['payload_msg'], dict):
            if 'error' in result['payload_msg']:
                return False
                
        # For a successful STT result, we expect either:
        # 1. A payload_msg with result.text, or
        # 2. No error indicators
        payload_msg = result.get('payload_msg', {})
        if isinstance(payload_msg, dict):
            # If there's a result field, check if it contains valid text
            if 'result' in payload_msg:
                return True  # Even empty text can be valid for connectivity test
                
        # If no obvious errors and it's a valid dict, consider it successful
        return True

    def _extract_stt_error_message(self, result) -> str:
        """
        Extract error message from STT result
        
        Args:
            result: STT processing result
            
        Returns:
            str: Error message
        """
        if not isinstance(result, dict):
            return f"Invalid result type: {type(result)}"
            
        # Check for direct error field
        if 'error' in result:
            return str(result['error'])
            
        # Check for error code with message
        if 'code' in result and result['code'] != 1000:
            error_msg = f"STT service error code: {result['code']}"
            if 'payload_msg' in result and isinstance(result['payload_msg'], dict):
                if 'error' in result['payload_msg']:
                    error_msg += f" - {result['payload_msg']['error']}"
            return error_msg
            
        # Check for nested error in payload_msg
        if 'payload_msg' in result and isinstance(result['payload_msg'], dict):
            if 'error' in result['payload_msg']:
                return str(result['payload_msg']['error'])
                
        return f"Unknown error in result: {result}"


async def process_audio_item(audio_item: Dict[str, Any], config: STTConfig, test_voice_path: str) -> Dict[str, Any]:
    """
    Process an audio item with the STT model.
    
    Args:
        audio_item: Audio item with 'id' and 'path' keys
        config: STT configuration
        test_voice_path: Path to test voice file for connectivity testing
        
    Returns:
        Recognition result with id and path
    """
    assert 'id' in audio_item
    assert 'path' in audio_item

    audio_id = audio_item['id']
    audio_path = audio_item['path']

    stt_model = STTModel(config, test_voice_path)
    result = await stt_model.recognize_file(audio_path)

    return {"id": audio_id, "path": audio_path, "result": result}
