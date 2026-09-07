"""DashScope VLM adapter; OpenAI-compatible with a DashScope audio dialect."""

from __future__ import annotations

from typing import Any, Dict, List, Union

from ...registry import register_adapter
from .openai import OpenAIVLMAdapter


@register_adapter("dashscope", "vlm")
class DashScopeVLMAdapter(OpenAIVLMAdapter):
    """DashScope VLM adapter.

    Attributes:
        factory: ``"dashscope"``.
    """

    factory = "dashscope"

    def prepare_media_message(self, media_input: Union[str, Any], media_type: str,
                              content_type: str, system_prompt: str) -> List[Dict[str, Any]]:
        """Build a DashScope-compatible multimodal message for audio or video.

        Args:
            media_input: A file path or a binary file-like object.
            media_type: ``"audio"`` or ``"video"``.
            content_type: MIME content type, e.g. ``"audio/mpeg"``.
            system_prompt: System prompt guiding the analysis.

        Returns:
            A user message list with the media encoded for DashScope.
        """
        if media_type != "audio":
            return super().prepare_media_message(media_input, media_type, content_type, system_prompt)

        base64_media = self.encode_image(media_input)
        audio_format = content_type.rsplit("/", 1)[-1]
        return [
            {
                "role": "user",
                "content": [
                    {"type": "input_audio",
                     "input_audio": {"data": f"data:{content_type};base64,{base64_media}",
                                     "format": audio_format}},
                    {"type": "text", "text": system_prompt},
                ],
            }
        ]
