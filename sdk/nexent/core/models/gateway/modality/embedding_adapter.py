"""Embedding adapter — protocol implementation sunk in (no _model wrapper).

The HTTP REST embedding protocol (session POST + retry loop + response parsing
+ dimension_check connectivity test) lives directly in the adapters. The old
``embedding_model.py`` classes (``BaseEmbedding`` / ``TextEmbedding`` /
``MultimodalEmbedding`` / ``JinaEmbedding`` / ``DashScopeMultimodalEmbedding`` /
``SiliconflowMultimodalEmbedding`` / ``OpenAICompatibleEmbedding``) are deleted;
the adapters ARE the implementation.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

import requests

from .....monitor.monitoring import record_model_call
from ..base import ModelInfo, MultimodalAdapter
from ..context import ModelContext
from ..registry import register_adapter
from ..transport import HttpTransportMixin

logger = logging.getLogger(__name__)

ASSETS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))), "assets"
)


def _detect_image_mime(img_bytes: bytes) -> str:
    """Detects an image's MIME type from its magic bytes.

    Args:
        img_bytes: The raw image bytes to inspect.

    Returns:
        The detected MIME type, or ``image/jpeg`` when empty or unknown.
    """
    if not img_bytes:
        return "image/jpeg"
    if img_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if img_bytes[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if img_bytes[:4] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if img_bytes[:4] == b"RIFF" and img_bytes[8:12] == b"WEBP":
        return "image/webp"
    if img_bytes[:2] == b"BM":
        return "image/bmp"
    return "image/jpeg"


@dataclass
class EmbeddingRequest:
    """Embedding request payload: text or multimodal inputs."""

    inputs: Union[str, List[str], List[Dict[str, Any]]]
    with_metadata: bool = False
    timeout: float = None
    retries: int = 3
    retry_timeout_step: float = 5.0


class EmbeddingAdapter(MultimodalAdapter, HttpTransportMixin):
    """Base embedding adapter — shared HTTP session + retry loop."""

    @abstractmethod
    async def invoke(self, request: EmbeddingRequest):
        """Embeds the inputs in the given request."""
        ...

    def __init__(self, context: ModelContext) -> None:
        MultimodalAdapter.__init__(self, context)
        HttpTransportMixin.__init__(
            self,
            base_url=context.base_url,
            api_key=context.api_key,
            ssl_verify=context.ssl_verify,
            timeout=context.extra.get("timeout_seconds", 30.0),
        )
        self._session = requests.Session()
        self._session.trust_env = False
        self._headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

    @property
    def _model_name(self) -> str:
        """The configured model name."""
        return self._context.model_name

    def _make_request(self, data: Dict[str, Any], timeout: Optional[float] = None) -> Dict[str, Any]:
        """POSTs the request body and returns the parsed JSON response.

        Args:
            data: The JSON-serializable request body.
            timeout: Optional per-request timeout in seconds.

        Returns:
            The response body parsed as JSON.

        Raises:
            requests.HTTPError: If the upstream returns a non-2xx status.
        """
        response = self._session.post(
            self._base_url, headers=self._headers, json=data, timeout=timeout, verify=self._ssl_verify
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _retry(attempts: int, base_timeout: float, step: float, fn, label: str):
        """Runs ``fn()`` with linear-backoff retries on timeout.

        Args:
            attempts: Total number of attempts.
            base_timeout: Timeout in seconds for the first attempt.
            step: Seconds added to the timeout per retry.
            fn: Callable taking a timeout in seconds and returning its result.
            label: Provider name used in log messages.

        Returns:
            The result of a successful ``fn()`` call, or ``[]`` if no attempt
            was made.

        Raises:
            requests.exceptions.Timeout: If ``fn()`` still times out after all
                retries.
        """
        last_timeout = None
        for i in range(attempts):
            current = base_timeout + i * step
            try:
                return fn(current)
            except requests.exceptions.Timeout as e:
                logging.warning(f"{label} API timed out in {current}s ({i + 1}/{attempts})")
                last_timeout = e
                if i == attempts - 1:
                    logging.error(f"{label} API timed out after all retries.")
                    raise
        if last_timeout:
            raise last_timeout
        return []

    async def health_check(self) -> bool:
        """Checks API connectivity with a quick dimension check.

        Returns:
            True if the check succeeds, False otherwise.
        """
        try:
            await self.dimension_check(timeout=5.0)
            return True
        except Exception:
            return False


# ---- multimodal embedding adapters (Jina / DashScope / Siliconflow) ----

class _MultimodalEmbeddingAdapter(EmbeddingAdapter):
    """Shared multimodal logic: get_embeddings delegates to get_multimodal_embeddings."""

    @abstractmethod
    def _prepare_multimodal_input(self, inputs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Builds the provider request body from multimodal inputs."""
        ...

    @abstractmethod
    def _extract_embeddings(self, response: Dict[str, Any]) -> List[List[float]]:
        """Extracts embedding vectors from a provider response."""
        ...

    @abstractmethod
    def _test_inputs(self) -> List[Dict[str, Any]]:
        """Returns sample inputs used for connectivity checks."""
        ...

    def get_embeddings(self, inputs, with_metadata=False, timeout=None, retries=3, retry_timeout_step=5.0):
        """Embeds text inputs, delegating to the multimodal embedding path.

        Args:
            inputs: A string or an iterable of strings to embed.
            with_metadata: If True, returns the raw provider response instead
                of embedding vectors.
            timeout: Optional per-request timeout; defaults to
                ``retry_timeout_step``.
            retries: Number of retries on timeout.
            retry_timeout_step: Seconds added to the timeout per retry.

        Returns:
            A list of embedding vectors, or the raw response when
            ``with_metadata`` is True.
        """
        if isinstance(inputs, str):
            mm = [{"text": inputs}]
        else:
            mm = [{"text": item} for item in inputs]
        return self.get_multimodal_embeddings(mm, with_metadata, timeout, retries, retry_timeout_step)

    def get_multimodal_embeddings(self, inputs, with_metadata=False, timeout=None, retries=3, retry_timeout_step=5.0):
        """Embeds multimodal items via the provider's multimodal endpoint.

        Args:
            inputs: List of multimodal items (dicts with ``text`` and/or
                ``image`` keys).
            with_metadata: If True, returns the raw provider response instead
                of embedding vectors.
            timeout: Optional per-request timeout; defaults to
                ``retry_timeout_step``.
            retries: Number of retries on timeout.
            retry_timeout_step: Seconds added to the timeout per retry.

        Returns:
            A list of embedding vectors, or the raw response when
            ``with_metadata`` is True.
        """
        with record_model_call("multi_embedding", self._model_name, display_name=self._model_name):
            data = self._prepare_multimodal_input(inputs)
            base_timeout = timeout if timeout is not None else retry_timeout_step
            attempts = retries + 1

            def _do(current):
                response = self._make_request(data, timeout=current)
                if with_metadata:
                    return response
                return self._extract_embeddings(response)

            return self._retry(attempts, base_timeout, retry_timeout_step, _do, type(self).__name__)

    async def dimension_check(self, timeout: float = 5.0) -> List[List[float]]:
        """Runs a connectivity check using sample multimodal inputs.

        Args:
            timeout: Timeout in seconds for the check.

        Returns:
            The embedding vectors from the sample request, or an empty list if
            the check fails.
        """
        try:
            return await asyncio.to_thread(self.get_multimodal_embeddings, self._test_inputs(), timeout=timeout)
        except requests.exceptions.Timeout:
            logging.error(f"{type(self).__name__} connection timed out ({timeout}s)")
            return []
        except requests.exceptions.ConnectionError:
            logging.error(f"{type(self).__name__} connection error")
            return []
        except Exception as e:
            logging.error(f"{type(self).__name__} connection failed: {str(e)}")
            return []

    async def invoke(self, request: EmbeddingRequest):
        """Embeds the request via the multimodal or text embedding path."""
        if _is_multimodal(request.inputs):
            return await asyncio.to_thread(
                self.get_multimodal_embeddings, request.inputs,
                with_metadata=request.with_metadata, timeout=request.timeout,
            )
        return await asyncio.to_thread(
            self.get_embeddings, request.inputs,
            with_metadata=request.with_metadata, timeout=request.timeout,
        )


def _is_multimodal(inputs: Any) -> bool:
    """Returns True if ``inputs`` is a non-empty list of dicts."""
    return isinstance(inputs, list) and bool(inputs) and isinstance(inputs[0], dict)


@register_adapter("jina", "multi_embedding")
class JinaEmbeddingAdapter(_MultimodalEmbeddingAdapter):
    """Jina multimodal embedding adapter."""

    factory = "jina"

    def _prepare_multimodal_input(self, inputs):
        prepared = []
        for item in inputs:
            if "text" in item:
                prepared.append(item)
            elif "image" in item:
                img = item["image"]
                if isinstance(img, bytes):
                    mime = _detect_image_mime(img)
                    img = f"data:{mime};base64,{base64.b64encode(img).decode('utf-8')}"
                prepared.append({"image": img})
            else:
                prepared.append(item)
        return {"model": self._model_name, "input": prepared, "truncate": True}

    def _extract_embeddings(self, response):
        return [item["embedding"] for item in response["data"]]

    def _test_inputs(self):
        test_image_path = os.path.join(ASSETS_DIR, "test.png")
        with open(test_image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")
        return [
            {"text": "Hello, nexent!"},
            {"image": f"data:image/png;base64,{image_data}"},
        ]

    def get_model_info(self) -> ModelInfo:
        """Returns the model's metadata."""
        return ModelInfo(self._context.model_name, self._context.display_name or "", self.factory, {"text": True, "multimodal": True})


@register_adapter("dashscope", "multi_embedding")
class DashScopeEmbeddingAdapter(_MultimodalEmbeddingAdapter):
    """DashScope multimodal embedding adapter."""

    factory = "dashscope"

    def _prepare_multimodal_input(self, inputs):
        normalized = []
        for item in inputs:
            if "image" in item:
                img = item["image"]
                if isinstance(img, bytes):
                    img = f"data:image/png;base64,{base64.b64encode(img).decode('utf-8')}"
                normalized.append({"image": img})
            else:
                normalized.append(item)
        return {"model": self._model_name, "input": {"contents": normalized}}

    def _extract_embeddings(self, response):
        return [item["embedding"] for item in response["output"]["embeddings"]]

    def _test_inputs(self):
        test_image_path = os.path.join(ASSETS_DIR, "test.png")
        with open(test_image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")
        return [
            {"text": "Hello, nexent!"},
            {"image": f"data:image/png;base64,{image_data}"},
        ]

    def get_model_info(self) -> ModelInfo:
        """Returns the model's metadata."""
        return ModelInfo(self._context.model_name, self._context.display_name or "", self.factory, {"text": True, "multimodal": True})


@register_adapter("siliconflow", "multi_embedding")
class SiliconflowEmbeddingAdapter(_MultimodalEmbeddingAdapter):
    """SiliconFlow multimodal embedding adapter."""

    factory = "siliconflow"

    def _prepare_multimodal_input(self, inputs):
        prepared = []
        for item in inputs:
            if "text" in item:
                prepared.append(item["text"])
            elif "image" in item:
                img = item["image"]
                if isinstance(img, bytes):
                    mime = _detect_image_mime(img)
                    img = f"data:{mime};base64,{base64.b64encode(img).decode('utf-8')}"
                prepared.append({"image": img})
            else:
                prepared.append(item)
        return {"model": self._model_name, "input": prepared}

    def _extract_embeddings(self, response):
        return [item["embedding"] for item in response["data"]]

    def _test_inputs(self):
        test_image_path = os.path.join(ASSETS_DIR, "test.png")
        with open(test_image_path, "rb") as f:
            image_data = f.read()
        return [
            {"text": "Hello, nexent!"},
            {"image": image_data},
        ]

    def get_model_info(self) -> ModelInfo:
        """Returns the model's metadata."""
        return ModelInfo(self._context.model_name, self._context.display_name or "", self.factory, {"text": True, "multimodal": True})


# ---- text embedding adapter (OpenAI-compatible) ----

@register_adapter("openai", "embedding")
class OpenAICompatibleEmbeddingAdapter(EmbeddingAdapter):
    """OpenAI-compatible text embedding adapter."""

    factory = "openai"

    def _prepare_input(self, inputs):
        """Normalizes inputs to a list and builds the request body."""
        if isinstance(inputs, str):
            inputs = [inputs]
        return {"model": self._model_name, "input": inputs}

    def get_embeddings(self, inputs, with_metadata=False, timeout=None, retries=3, retry_timeout_step=5.0):
        """Embeds text inputs via the OpenAI-compatible endpoint.

        Args:
            inputs: A string or an iterable of strings to embed.
            with_metadata: If True, returns the raw provider response instead
                of embedding vectors.
            timeout: Optional per-request timeout; defaults to
                ``retry_timeout_step``.
            retries: Number of retries on timeout.
            retry_timeout_step: Seconds added to the timeout per retry.

        Returns:
            A list of embedding vectors, or the raw response when
            ``with_metadata`` is True.
        """
        with record_model_call("embedding", self._model_name, display_name=self._model_name):
            data = self._prepare_input(inputs)
            base_timeout = timeout if timeout is not None else retry_timeout_step
            attempts = retries + 1

            def _do(current):
                response = self._make_request(data, timeout=current)
                if with_metadata:
                    return response
                return [item["embedding"] for item in response["data"]]

            return self._retry(attempts, base_timeout, retry_timeout_step, _do, "OpenAI")

    async def dimension_check(self, timeout: float = 5.0) -> List[List[float]]:
        """Runs a connectivity check with a sample text input.

        Args:
            timeout: Timeout in seconds for the check.

        Returns:
            The embedding vectors from the sample request, or an empty list if
            the check fails.
        """
        try:
            return await asyncio.to_thread(self.get_embeddings, "Hello, nexent!", timeout=timeout)
        except requests.exceptions.Timeout:
            logging.error(f"OpenAI embedding connection timed out ({timeout}s)")
            return []
        except requests.exceptions.ConnectionError:
            logging.error("OpenAI embedding connection error")
            return []
        except Exception as e:
            logging.error(f"OpenAI embedding connection failed: {str(e)}")
            return []

    async def invoke(self, request: EmbeddingRequest):
        """Embeds the request's text inputs."""
        return await asyncio.to_thread(
            self.get_embeddings, request.inputs,
            with_metadata=request.with_metadata, timeout=request.timeout,
        )

    def get_model_info(self) -> ModelInfo:
        """Returns the model's metadata."""
        return ModelInfo(self._context.model_name, self._context.display_name or "", self.factory, {"text": True, "multimodal": False})
