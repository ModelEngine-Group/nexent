"""MiniMax Text-to-Audio v2 model implementation."""
import json
from dataclasses import dataclass
from typing import AsyncGenerator, Dict, Optional, Union

import httpx

from .tts_model import BaseTTSModel


@dataclass
class MiniMaxTTSConfig:
    api_key: str
    model: str = "speech-2.8-hd"
    base_url: str = "https://api.minimax.io/v1/t2a_v2"
    output_format: str = "mp3"


class MiniMaxTTSModel(BaseTTSModel):
    """Synthesize speech through MiniMax's OpenAI-style HTTP endpoint."""

    def __init__(self, config: MiniMaxTTSConfig, audio_file_path: Optional[str] = None):
        super().__init__(audio_file_path)
        self.config = config

    def get_websocket_url(self) -> str:
        return self.config.base_url

    def get_auth_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.config.api_key}"}

    @staticmethod
    def _audio_from_payload(payload: dict) -> bytes:
        audio = payload.get("data", {}).get("audio")
        if not audio:
            base_resp = payload.get("base_resp", {})
            raise RuntimeError(base_resp.get("status_msg", "MiniMax TTS returned no audio"))
        return bytes.fromhex(audio)

    async def generate_speech(
        self, text: str, stream: bool = False
    ) -> Union[bytes, AsyncGenerator[bytes, None]]:
        request = {
            "model": self.config.model,
            "text": text,
            "stream": stream,
            "output_format": self.config.output_format,
        }
        headers = {**self.get_auth_headers(), "Content-Type": "application/json"}

        async def chunks() -> AsyncGenerator[bytes, None]:
            async with httpx.AsyncClient(timeout=60) as client:
                async with client.stream("POST", self.config.base_url, headers=headers, json=request) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line or line.startswith("data:") is False:
                            continue
                        value = line[5:].strip()
                        if value == "[DONE]":
                            break
                        yield self._audio_from_payload(json.loads(value))

        if stream:
            return chunks()
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(self.config.base_url, headers=headers, json=request)
            response.raise_for_status()
            return self._audio_from_payload(response.json())

    async def check_connectivity(self) -> bool:
        try:
            return bool(await self.generate_speech("Hello", stream=False))
        except Exception:
            return False
