"""
Volcano Engine TTS model implementation using proprietary protocol.
"""
import copy
import gzip
import io
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Dict, Optional, Union

import websockets

from .tts_model import BaseTTSModel

logger = logging.getLogger(__name__)


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
    cluster:str="volcano_tts"
    resource_id:str="seed-tts-2.0"
    voice_type: str = "zh_female_vv_uranus_bigtts"

    @property
    def api_url(self) -> str:
        return self.ws_url


class VolcTTSModel(BaseTTSModel):
    """
    Volcano Engine TTS model implementation using proprietary protocol.
    """

    MESSAGE_TYPES = {11: "audio-only server response", 12: "frontend server response", 15: "error message from server"}
    MESSAGE_TYPE_SPECIFIC_FLAGS = {0: "no sequence number", 1: "sequence number > 0",
                                   2: "last message from server (seq < 0)", 3: "sequence number < 0"}
    MESSAGE_SERIALIZATION_METHODS = {0: "no serialization", 1: "JSON", 15: "custom type"}
    MESSAGE_COMPRESSIONS = {0: "no compression", 1: "gzip", 15: "custom compression method"}

    DEFAULT_HEADER = bytearray([0x11, 0x10, 0x11, 0x00])

    def __init__(self, config: VolcTTSConfig, audio_file_path: Optional[str] = None):
        super().__init__(audio_file_path)
        self.config = config
        self._request_template = {
            "app": {"appid": config.appid, "token": config.token, "cluster": config.cluster, "resource_id": config.resource_id},
            "user": {"uid": "388808087185088"},
            "audio": {
                "voice_type": config.voice_type,
                "encoding": config.encoding,
                "speed_ratio": config.speed_ratio,
                "volume_ratio": config.volume_ratio,
                "pitch_ratio": config.pitch_ratio,
            },
            "request": {"reqid": "xxx", "text": "", "text_type": "plain", "operation": "xxx"}
        }

    def get_websocket_url(self) -> str:
        return self.config.api_url

    def get_auth_headers(self) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer; {self.config.token}",
            "X-Api-App-Id": self.config.appid,
            "X-Api-Access-Key": self.config.token,
            "X-Api-Resource-Id": self.config.resource_id
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
