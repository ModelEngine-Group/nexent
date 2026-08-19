"""Embedding adapter root: request type + shared text/multimodal embedding machinery."""

from __future__ import annotations

import asyncio
import logging
import os
from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

import requests

from nexent.monitor import record_model_call

from ...model_context import EmbeddingContext
from ...multimodal_adapter import MultimodalAdapter
from ...transport import HttpTransportMixin


DEFAULT_IMAGE_MIME_TYPE = "image/jpeg"

ASSETS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))), "assets"
)


def _detect_image_mime(img_bytes: bytes) -> str:
    """Detect an image's MIME type from its magic bytes (default ``image/jpeg``)."""
    if not img_bytes:
        return DEFAULT_IMAGE_MIME_TYPE
    if img_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if img_bytes[:3] == b"\xff\xd8\xff":
        return DEFAULT_IMAGE_MIME_TYPE
    if img_bytes[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if img_bytes[:4] == b"RIFF" and img_bytes[8:12] == b"WEBP":
        return "image/webp"
    if img_bytes[:2] == b"BM":
        return "image/bmp"
    return DEFAULT_IMAGE_MIME_TYPE


@dataclass
class EmbeddingRequest:
    """Embedding request payload: text or multimodal inputs.

    Attributes:
        inputs: A string, a list of strings, or a list of multimodal item dicts.
        with_metadata: If True, return the raw provider response instead of vectors.
        timeout: Per-request timeout; ``None`` uses ``retry_timeout_step``.
        retries: Number of retries on timeout (total attempts = ``retries + 1``).
        retry_timeout_step: Seconds added to the timeout per retry.
    """

    inputs: Union[str, List[str], List[Dict[str, Any]]]
    with_metadata: bool = False
    timeout: float = None
    retries: int = 3
    retry_timeout_step: float = 5.0


class EmbeddingAdapter(MultimodalAdapter, HttpTransportMixin):
    """Base embedding adapter — shared HTTP session + retry loop.

    Attributes:
        _session: Shared ``requests.Session`` (``trust_env`` disabled).
        _headers: HTTP auth headers built from the API key.
    """

    @abstractmethod
    async def invoke(self, request: EmbeddingRequest):
        """Embed the request's inputs.

        Args:
            request: The embedding request (text or multimodal inputs).

        Returns:
            A list of embedding vectors, or the raw response with metadata.
        """
        ...

    def __init__(self, context: EmbeddingContext) -> None:
        """Initialize the shared HTTP session and auth headers."""
        MultimodalAdapter.__init__(self, context)
        HttpTransportMixin.__init__(
            self,
            base_url=context.base_url,
            api_key=context.api_key,
            ssl_verify=context.ssl_verify,
            timeout=context.timeout_seconds if context.timeout_seconds is not None else 30.0,
        )
        self._session = requests.Session()
        self._session.trust_env = False
        self._headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

    @property
    def _model_name(self) -> str:
        """The model name from the construction context."""
        return self._context.model_name

    def _make_request(self, data: Dict[str, Any], timeout: Optional[float] = None) -> Dict[str, Any]:
        """POST the request body and return the parsed JSON response.

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
        for i in range(attempts):
            current = base_timeout + i * step
            try:
                return fn(current)
            except requests.exceptions.Timeout:
                logging.warning(f"{label} API timed out in {current}s ({i + 1}/{attempts})")
                if i == attempts - 1:
                    logging.error(f"{label} API timed out after all retries.")
                    raise
        return []

    async def health_check(self) -> bool:
        """Check API connectivity via a quick dimension check."""
        try:
            await self.dimension_check(timeout=5.0)
            return True
        except Exception:
            return False


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
        """Embed text inputs by delegating to the multimodal embedding path.

        Args:
            inputs: A string or list of strings to embed.
            with_metadata: If True, return the raw provider response.
            timeout: Per-request timeout; ``None`` uses ``retry_timeout_step``.
            retries: Number of retries on timeout.
            retry_timeout_step: Seconds added to the timeout per retry.

        Returns:
            A list of embedding vectors, or the raw response with metadata.
        """
        if isinstance(inputs, str):
            mm = [{"text": inputs}]
        else:
            mm = [{"text": item} for item in inputs]
        return self.get_multimodal_embeddings(mm, with_metadata, timeout, retries, retry_timeout_step)

    def get_multimodal_embeddings(self, inputs, with_metadata=False, timeout=None, retries=3, retry_timeout_step=5.0):
        """Embed multimodal items via the provider's multimodal endpoint.

        Args:
            inputs: A list of multimodal item dicts (``{"text": ...}`` / ``{"image": ...}``).
            with_metadata: If True, return the raw provider response.
            timeout: Per-request timeout; ``None`` uses ``retry_timeout_step``.
            retries: Number of retries on timeout.
            retry_timeout_step: Seconds added to the timeout per retry.

        Returns:
            A list of embedding vectors, or the raw response with metadata.
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
        """Connectivity check using sample multimodal inputs.

        Args:
            timeout: Timeout in seconds for the check.

        Returns:
            The embedding vectors from the sample request, or ``[]`` on failure.
        """
        try:
            return await asyncio.to_thread(self.get_multimodal_embeddings, self._test_inputs(), timeout=timeout)
        except requests.exceptions.Timeout:
            logging.error(f"{type(self).__name__} connection timed out ({timeout}s)")
            return []
        except requests.exceptions.ConnectionError:
            logging.error(f"{type(self).__name__} connection error")
            return []
        except Exception:
            logging.exception(f"{type(self).__name__} connection failed")
            return []

    async def invoke(self, request: EmbeddingRequest):
        """Embed ``request.inputs`` via the multimodal or text path, offloaded to a thread."""
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
