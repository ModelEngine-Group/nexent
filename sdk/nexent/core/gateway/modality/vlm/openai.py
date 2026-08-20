"""OpenAI-compatible VLM adapter (protocol lives on the adapter)."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from typing import Any, BinaryIO, Dict, List, Union

from ....models import OpenAIModel

from ...model_context import VLMContext
from ...multimodal_adapter import ModelInfo, MultimodalAdapter
from ...registry import register_adapter
from ...transport import HttpTransportMixin
from .vlm_adapter import VLMAdapter, VLMRequest


logger = logging.getLogger(__name__)

_METHOD_MAP = {"image": "analyze_image", "audio": "analyze_audio", "video": "analyze_video"}


@register_adapter("openai", "vlm")
class OpenAIVLMAdapter(VLMAdapter, HttpTransportMixin):
    """OpenAI-compatible VLM adapter; chat delegates to a wrapped OpenAIModel."""

    factory = "openai"

    def __init__(self, context: VLMContext) -> None:
        MultimodalAdapter.__init__(self, context)
        HttpTransportMixin.__init__(
            self,
            base_url=context.base_url,
            api_key=context.api_key,
            ssl_verify=context.ssl_verify,
            timeout=context.timeout_seconds if context.timeout_seconds is not None else 30.0,
        )
        self._model: Any = None  # wrapped OpenAIModel, built lazily

    def _build_model(self) -> None:
        """Construct the wrapped :class:`OpenAIModel` with VLM sampling defaults.

        ``frequency_penalty`` is set as a dead instance attribute after
        construction, mirroring the old ``OpenAIVLModel``. It must NOT be
        passed to ``OpenAIModel.__init__`` because smolagents stores unknown
        kwargs in ``self.kwargs`` and merges them into every API call.
        """
        ctx = self._context
        self._model = OpenAIModel(
            observer=ctx.observer,
            model_id=ctx.model_name,
            api_base=self._base_url,
            api_key=self._api_key,
            ssl_verify=self._ssl_verify,
            model_factory=self.factory,
            display_name=ctx.display_name,
            temperature=ctx.temperature if ctx.temperature is not None else 0.7,
            top_p=ctx.top_p if ctx.top_p is not None else 0.7,
            max_tokens=ctx.max_tokens if ctx.max_tokens is not None else 512,
        )
        self._model.frequency_penalty = ctx.frequency_penalty if ctx.frequency_penalty is not None else 0.5

    # VLM protocol (moved from openai_vlm.py)

    def encode_image(self, image_input: Union[str, BinaryIO]) -> str:
        """Encode an image file or stream into a base64 string.

        Args:
            image_input: A file path or a binary file-like object.

        Returns:
            The base64-encoded image bytes as a string.
        """
        if isinstance(image_input, str):
            with open(image_input, "rb") as image_file:
                return base64.b64encode(image_file.read()).decode('utf-8')
        return base64.b64encode(image_input.read()).decode('utf-8')

    def prepare_image_message(self, image_input: Union[str, BinaryIO],
                             system_prompt: str = "Describe this picture.") -> List[Dict[str, Any]]:
        """Build OpenAI-compatible chat messages embedding an encoded image.

        When ``image_input`` is a path, the image format is sniffed from the
        file extension (defaulting to ``jpeg``).

        Args:
            image_input: A file path or a binary file-like object.
            system_prompt: System prompt guiding the analysis.

        Returns:
            A two-message list (system + user) with the image as a data URL.
        """
        base64_image = self.encode_image(image_input)

        image_format = "jpeg"
        if isinstance(image_input, str) and os.path.exists(image_input):
            _, ext = os.path.splitext(image_input)
            if ext.lower() in ['.png', '.jpg', '.jpeg', '.gif', '.webp']:
                image_format = ext.lower()[1:]
                if image_format == 'jpg':
                    image_format = 'jpeg'

        messages = [{"role": "system", "content": [{"text": system_prompt, "type": "text"}]},
                    {"role": "user",
                     "content": [{"type": "image_url",
                                  "image_url": {"url": f"data:image/{image_format};base64,{base64_image}",
                                                "detail": "auto"}}]}]
        return messages

    def prepare_media_message(self, media_input: Union[str, BinaryIO], media_type: str,
                              content_type: str, system_prompt: str) -> List[Dict[str, Any]]:
        """Build an OpenAI-compatible multimodal message for audio or video.

        Args:
            media_input: A file path or a binary file-like object.
            media_type: ``"audio"`` or ``"video"``.
            content_type: MIME content type, e.g. ``"audio/mpeg"``.
            system_prompt: System prompt guiding the analysis.

        Returns:
            A user message list with the media as a data URL.

        Raises:
            ValueError: If ``media_type`` is not "audio" or "video".
        """
        if media_type not in ("audio", "video"):
            raise ValueError(f"Unsupported media type: {media_type}")

        base64_media = self.encode_image(media_input)
        media_url_key = f"{media_type}_url"
        media_config: Dict[str, Any] = {"url": f"data:{content_type};base64,{base64_media}"}
        if media_type == "video":
            media_config.update({"detail": "high", "max_frames": 16, "fps": 1})

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": media_url_key, media_url_key: media_config},
                    {"type": "text", "text": system_prompt}
                ]
            }
        ]
        return messages

    def analyze_image(self, image_input: Union[str, BinaryIO],
                      system_prompt: str = "Please describe this picture concisely and carefully, within 200 words.",
                      stream: bool = True, **kwargs) -> Any:
        """Analyze image content and return a smolagents ChatMessage.

        Args:
            image_input: A file path or a binary file-like object.
            system_prompt: System prompt guiding the analysis.
            stream: Whether to stream the response.
            **kwargs: Additional arguments forwarded to the wrapped model.

        Returns:
            A smolagents ``ChatMessage`` with the image analysis.
        """
        if self._model is None:
            self._build_model()
        messages = self.prepare_image_message(image_input, system_prompt)
        # Call _model.__call__ explicitly so instance-level mocks work in tests.
        return self._model(messages=messages, **kwargs)

    def analyze_audio(self, audio_input: Union[str, BinaryIO],
                      system_prompt: str = "Please analyze this audio carefully.",
                      content_type: str = "audio/mpeg", stream: bool = True, **kwargs) -> Any:
        """Analyze audio content and return a smolagents ChatMessage.

        Args:
            audio_input: A file path or a binary file-like object.
            system_prompt: System prompt guiding the analysis.
            content_type: MIME content type, e.g. ``"audio/mpeg"``.
            stream: Whether to stream the response. Absorbed here so it is
                NOT forwarded to the wrapped model — the wrapped
                :class:`OpenAIModel` always drives ``stream`` itself, and
                forwarding it would collide with its own ``stream=True``.
            **kwargs: Additional arguments forwarded to the wrapped model.

        Returns:
            A smolagents ``ChatMessage`` with the audio analysis.
        """
        if self._model is None:
            self._build_model()
        messages = self.prepare_media_message(audio_input, "audio", content_type, system_prompt)
        return self._model(messages=messages, **kwargs)

    def analyze_video(self, video_input: Union[str, BinaryIO],
                      system_prompt: str = "Please analyze this video carefully.",
                      content_type: str = "video/mp4", stream: bool = True, **kwargs) -> Any:
        """Analyze video content and return a smolagents ChatMessage.

        Args:
            video_input: A file path or a binary file-like object.
            system_prompt: System prompt guiding the analysis.
            content_type: MIME content type, e.g. ``"video/mp4"``.
            stream: Whether to stream the response. Absorbed here so it is
                NOT forwarded to the wrapped model — the wrapped
                :class:`OpenAIModel` always drives ``stream`` itself, and
                forwarding it would collide with its own ``stream=True``.
            **kwargs: Additional arguments forwarded to the wrapped model.

        Returns:
            A smolagents ``ChatMessage`` with the video analysis.
        """
        if self._model is None:
            self._build_model()
        messages = self.prepare_media_message(video_input, "video", content_type, system_prompt)
        return self._model(messages=messages, **kwargs)

    async def check_connectivity(self) -> bool:
        """Check VLM connectivity by sending a test image + text prompt.

        Probes with the local ``assets/git-flow.png`` asset, falling back to a
        hardcoded DashScope URL when the asset is missing.

        Returns:
            True if the probe succeeds, False on any exception.
        """
        if self._model is None:
            self._build_model()
        module_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        test_image_path = os.path.join(module_dir, "assets", "git-flow.png")
        if os.path.exists(test_image_path):
            base64_image = self.encode_image(test_image_path)
            _, ext = os.path.splitext(test_image_path)
            image_format = ext.lower()[1:] if ext else "png"
            if image_format == "jpg":
                image_format = "jpeg"
            content_parts: List[Dict[str, Any]] = [
                {"type": "image_url", "image_url": {"url": f"data:image/{image_format};base64,{base64_image}"}},
                {"type": "text", "text": "Hello"},
            ]
        else:
            test_image_url = "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20250925/thtclx/input1.png"
            content_parts = [
                {"type": "image_url", "image_url": {"url": test_image_url}},
                {"type": "text", "text": "Hello"},
            ]

        try:
            await asyncio.to_thread(
                self._model.client.chat.completions.create,
                model=self._model.model_id,
                messages=[{"role": "user", "content": content_parts}],
                max_tokens=5,
                stream=False,
            )
            return True
        except Exception:
            logger.exception("VLM connectivity check failed")
            return False

    # Adapter contract

    async def invoke(self, request: VLMRequest) -> Any:
        """Dispatch to the matching ``analyze_*`` method and return a ChatMessage."""
        return self.invoke_sync(request)

    def invoke_sync(self, request: VLMRequest) -> Any:
        """Dispatch the request to the matching ``analyze_*`` method.

        Args:
            request: The VLM request; ``media_type`` selects the method,
                ``prompt`` becomes ``system_prompt``, and ``kwargs`` are merged
                into the forwarded call.

        Returns:
            A smolagents ``ChatMessage`` from the dispatched ``analyze_*`` call.
        """
        method = getattr(self, _METHOD_MAP[request.media_type])
        call_kwargs: Dict[str, Any] = {"stream": request.stream}
        if request.prompt:
            call_kwargs["system_prompt"] = request.prompt
        if request.kwargs:
            call_kwargs.update(request.kwargs)
        return method(request.media_input, **call_kwargs)

    async def health_check(self) -> bool:
        """Delegate to :meth:`check_connectivity`."""
        return await self.check_connectivity()

    def _is_siliconflow_non_omni(self) -> bool:
        """Check whether this is a SiliconFlow VLM that cannot accept audio input.

        This is the only place that should know which (provider, model) combos
        can't ingest a given media type - callers ask the adapter via
        :meth:`get_model_info` rather than reaching into the wrapped model's
        ``client_kwargs`` / ``model_id``.

        Returns:
            True if the provider is SiliconFlow and the model is not Qwen3-Omni.
        """
        return (
            "siliconflow" in (self._context.base_url or "").lower()
            and "omni" not in (self._context.model_name or "").lower()
        )

    def get_model_info(self) -> ModelInfo:
        """Return ``ModelInfo`` with image/audio/video capabilities.

        Explicit capability overrides from context win; defaults assume a
        capable VLM. Provider-specific limitations are computed here so the
        capability dict, not the caller's URL-sniffing, is the source of truth.
        """
        caps = dict(self._context.capabilities)
        if "audio" not in caps and self._is_siliconflow_non_omni():
            caps["audio"] = False
        caps.setdefault("image", True)
        caps.setdefault("audio", True)
        caps.setdefault("video", True)
        return ModelInfo(
            model_id=self._context.model_name,
            display_name=self._context.display_name or "",
            provider=self.factory,
            capabilities=caps,
        )
