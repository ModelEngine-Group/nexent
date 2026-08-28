"""ModelEngine VLM adapter; protocol identical to OpenAI, only factory differs."""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import struct
import wave
from typing import Any, Dict

from ...registry import register_adapter
from .openai import OpenAIVLMAdapter

logger = logging.getLogger(__name__)


@register_adapter("modelengine", "vlm")
class ModelEngineVLMAdapter(OpenAIVLMAdapter):
    """ModelEngine VLM - protocol identical to OpenAI; only ``factory`` differs.

    Attributes:
        factory: ``"modelengine"``.
    """

    factory = "modelengine"

    async def check_connectivity(self) -> bool:
        """Probe connectivity with a media type the model actually supports.

        The inherited VLM probe sends image+text, which audio-only (ASR) models
        reject. An audio-capable, non-image model is probed with a short silent
        clip; everything else falls back to the inherited image probe.
        """
        caps = self.get_model_info().capabilities
        if not caps.get("image", True) and caps.get("audio", False):
            return await self._probe_audio()
        return await super().check_connectivity()

    async def _probe_audio(self) -> bool:
        """Send a short silent WAV to verify the ASR endpoint is reachable."""
        if self._model is None:
            self._build_model()
        content_parts: Dict[str, Any] = {
            "role": "user",
            "content": [
                {"type": "audio_url", "audio_url": {"url": self._silent_wav_data_url()}},
                {"type": "text", "text": "Hello"},
            ],
        }
        try:
            await asyncio.to_thread(
                self._model.client.chat.completions.create,
                model=self._model.model_id,
                messages=[content_parts],
                max_tokens=5,
                stream=False,
            )
            return True
        except Exception:
            logger.exception("ModelEngine audio connectivity check failed")
            return False

    @staticmethod
    def _silent_wav_data_url(rate: int = 8000, duration: float = 0.1) -> str:
        """Build a minimal silent WAV as a ``data:audio/wav;base64,...`` URL."""
        buf = io.BytesIO()
        nframes = int(rate * duration)
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(struct.pack("<" + "h" * nframes, *([0] * nframes)))
        return "data:audio/wav;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
