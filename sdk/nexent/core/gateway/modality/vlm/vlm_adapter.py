"""VLM (vision-language model) adapter root + request type."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, BinaryIO, Dict, Optional, Union

from ...multimodal_adapter import MultimodalAdapter


@dataclass
class VLMRequest:
    """VLM understanding request.

    Attributes:
        media_type: ``"image"`` | ``"audio"`` | ``"video"``.
        media_input: A file path or a binary file-like object of the media.
        prompt: System prompt guiding the analysis.
        stream: Whether to stream the response.
        kwargs: Extra arguments forwarded to the ``analyze_*`` method.
    """

    media_type: str  # "image" | "audio" | "video"
    media_input: Union[str, BinaryIO]
    prompt: str = ""
    stream: bool = True
    kwargs: Optional[Dict[str, Any]] = None


class VLMAdapter(MultimodalAdapter):
    """VLM adapter root.

    Attributes:
        modality: ``"vlm"``.
    """

    modality = "vlm"

    @abstractmethod
    async def invoke(self, request: VLMRequest) -> Any:
        """Analyze ``media_input`` with ``prompt`` and return a ChatMessage.

        Args:
            request: The VLM request describing the media and prompt to use.

        Returns:
            A smolagents ``ChatMessage`` for the analyzed media.
        """
