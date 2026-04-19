import copy
import gzip
import io
import json
import uuid
from dataclasses import dataclass
from typing import Optional, Union, AsyncGenerator, Dict, Any

import websockets

@dataclass
class TTSConfig:
    appid: str
    token: str
    cluster: str
    voice_type: str
    speed_ratio: float
    host: str = "openspeech.bytedance.com"

    @property
    def api_url(self) -> str:
        return f"wss://{self.host}/api/v1/tts/ws_binary"


class TTSModel:
    # Message type constants
    MESSAGE_TYPES = {11: "audio-only server response", 12: "frontend server response", 15: "error message from server"}
    MESSAGE_TYPE_SPECIFIC_FLAGS = {0: "no sequence number", 1: "sequence number > 0",
                                   2: "last message from server (seq < 0)", 3: "sequence number < 0"}
    MESSAGE_SERIALIZATION_METHODS = {0: "no serialization", 1: "JSON", 15: "custom type"}
    MESSAGE_COMPRESSIONS = {0: "no compression", 1: "gzip", 15: "custom compression method"}

    # Default binary header
    DEFAULT_HEADER = bytearray(b'\x11\x10\x11\x00')

    def __init__(self, config: TTSConfig):
        self.config = config
        self._request_template = {"app": {"appid": config.appid, "token": config.token, "cluster": config.cluster},
            "user": {"uid": "388808087185088"},
            "audio": {"voice_type": config.voice_type, "encoding": "mp3", "speed_ratio": config.speed_ratio,
                "volume_ratio": 1.0, "pitch_ratio": 1.0, },
            "request": {"reqid": "xxx", "text": "", "text_type": "plain", "operation": "xxx"}}

    def _prepare_request(self, text: str, operation: str = "submit") -> bytes:
        """Prepare the binary request payload"""
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
        """Parse server response and return (is_done, audio_chunk)"""
        protocol_version = res[0] >> 4
        header_size = res[0] & 0x0f
        message_type = res[1] >> 4
        message_type_specific_flags = res[1] & 0x0f
        payload = res[header_size * 4:]

        if message_type == 0xb:  # audio-only server response
            if message_type_specific_flags == 0:
                return False, None

            sequence_number = int.from_bytes(payload[:4], "big", signed=True)
            payload_size = int.from_bytes(payload[4:8], "big", signed=False)
            audio_chunk = payload[8:]

            if buffer is not None:
                buffer.write(audio_chunk)

            return sequence_number < 0, audio_chunk

        elif message_type == 0xf:  # error message
            code = int.from_bytes(payload[:4], "big", signed=False)
            error_msg = payload[8:]
            if (res[2] & 0x0f) == 1:  # if compressed
                error_msg = gzip.decompress(error_msg)
            raise Exception(f"TTS Error {code}: {error_msg.decode('utf-8')}")

        return True, None

    async def generate_speech(self, text: str, stream: bool = False) -> Union[bytes, AsyncGenerator[bytes, None]]:
        """
        Generate speech from text. Returns either complete audio bytes or an async generator of audio chunks.
        
        Args:
            text: Input text to synthesize
            stream: If True, return an async generator of audio chunks. If False, return complete audio bytes.
            
        Returns:
            Union[bytes, AsyncGenerator[bytes, None]]: Audio data either as complete bytes or streaming chunks
        """
        request = self._prepare_request(text)
        headers = {"Authorization": f"Bearer {self.config.token}"}

        if not stream:
            buffer = io.BytesIO()
            async with websockets.connect(self.config.api_url, additional_headers=headers, ping_interval=None) as ws:
                await ws.send(request)
                while True:
                    response = await ws.recv()
                    done, _ = self._parse_response(response, buffer)
                    if done:
                        break
            return buffer.getvalue()
        else:
            async def audio_generator():
                async with websockets.connect(self.config.api_url, additional_headers=headers,
                                              ping_interval=None) as ws:
                    await ws.send(request)
                    while True:
                        response = await ws.recv()
                        done, chunk = self._parse_response(response)
                        if chunk:
                            yield chunk
                        if done:
                            break

            return audio_generator()

    async def query_status(self, text: str) -> Dict[str, Any]:
        """Query the status of text synthesis"""
        request = self._prepare_request(text, operation="query")
        headers = {"Authorization": f"Bearer {self.config.token}"}

        async with websockets.connect(self.config.api_url, additional_headers=headers, ping_interval=None) as ws:
            await ws.send(request)
            response = await ws.recv()
            # Parse and return query response
            return self._parse_query_response(response)

    def _parse_query_response(self, response: bytes) -> Dict[str, Any]:
        """Parse query response into a dictionary"""
        # Implementation depends on the actual query response format
        # This is a placeholder - implement based on actual query response structure
        return {"status": "unknown"}

    async def check_connectivity(self) -> bool:
        """
        Test the connectivity to the remote TTS service
        
        Returns:
            bool: Returns True if the connection is successful, False if it fails
        """
        try:
            # Generate speech using the shortest test text, non-streaming
            audio_data = await self.generate_speech("Hello", stream=False)
            # Check if audio data was successfully retrieved
            return isinstance(audio_data, bytes) and len(audio_data) > 0
        except Exception:
            return False
