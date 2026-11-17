# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""OpenAI-compatible text embedding adapter."""

from __future__ import annotations

import asyncio
import logging
from typing import List

import httpx
import requests

from nexent.core.concurrency import run_blocking

from nexent.monitor import record_model_call

from ...multimodal_adapter import ModelInfo
from ...registry import register_adapter
from .embedding_adapter import EmbeddingAdapter, EmbeddingRequest


class InvalidEmbeddingResponse(ValueError):
    """The embedding service returned an invalid vector payload."""


def _embedding_vectors(response, expected_count):
    rows = response.get("data") if isinstance(response, dict) else None
    if not isinstance(rows, list) or len(rows) != expected_count:
        raise InvalidEmbeddingResponse("Invalid embedding data or result count")
    vectors = []
    for row in rows:
        vector = row.get("embedding") if isinstance(row, dict) else None
        if not isinstance(vector, list) or not vector:
            raise InvalidEmbeddingResponse("Missing embedding vector")
        vectors.append(vector)
    return vectors


@register_adapter("openai", "embedding")
class OpenAICompatibleEmbeddingAdapter(EmbeddingAdapter):
    """OpenAI-compatible text embedding adapter.

    Attributes:
        factory: ``"openai"``.
    """

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
                return _embedding_vectors(response, len(data["input"]))

            return self._retry(attempts, base_timeout, retry_timeout_step, _do, "OpenAI")

    async def get_embeddings_with_deadline(self, inputs, *, timeout: float):
        """Perform one request with a deadline for the complete HTTP response."""
        data = self._prepare_input(inputs)
        body = {**(self._context.extra_body or {}), **data}
        with record_model_call("embedding", self._model_name, display_name=self._model_name):
            async with asyncio.timeout(timeout):
                async with httpx.AsyncClient(verify=self._ssl_verify, trust_env=False, timeout=timeout) as client:
                    response = await client.post(self._base_url, headers=self._headers, json=body)
                    response.raise_for_status()
                    try:
                        payload = response.json()
                    except ValueError as exc:
                        raise InvalidEmbeddingResponse("Invalid embedding JSON") from exc
                    return _embedding_vectors(payload, len(data["input"]))

    async def dimension_check(self, timeout: float = 5.0) -> List[List[float]]:
        """Runs a connectivity check with a sample text input.

        Args:
            timeout: Timeout in seconds for the check.

        Returns:
            The embedding vectors from the sample request, or an empty list if
            the check fails.
        """
        try:
            return await run_blocking(
                "gateway-embedding-connectivity",
                self.get_embeddings,
                "Hello, nexent!",
                timeout=timeout,
            )
        except requests.exceptions.Timeout:
            logging.error(f"OpenAI embedding connection timed out ({timeout}s)")
            return []
        except requests.exceptions.ConnectionError:
            logging.error("OpenAI embedding connection error")
            return []
        except Exception:
            logging.exception("OpenAI embedding connection failed")
            return []

    async def invoke(self, request: EmbeddingRequest):
        """Embed ``request.inputs`` (text), offloaded to a worker thread."""
        return await run_blocking(
            "gateway-embedding-invoke",
            self.get_embeddings, request.inputs,
            with_metadata=request.with_metadata, timeout=request.timeout,
        )

    def get_model_info(self) -> ModelInfo:
        """Return ``ModelInfo`` with text capability (no multimodal)."""
        return ModelInfo(self._context.model_name, self._context.display_name or "", self.factory, {"text": True, "multimodal": False})
