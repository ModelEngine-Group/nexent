# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""OpenAI-compatible text embedding adapter."""

from __future__ import annotations

import asyncio
import logging
from typing import List

import httpx
import requests

from nexent.core.model_service.profiles.probe_diagnostics import record_connectivity_failure
from nexent.core.concurrency import run_blocking

from nexent.monitor import record_model_call
from nexent.monitor.model_fact import AttemptObservation, suppress_model_attempts
from nexent.monitor.monitoring import read_openai_token_counts

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
            observation = AttemptObservation.for_client(
                self._context.tenant_id, self._context.catalog_model_id, self._context.modality,
            )
            if observation is not None:
                observation.dispatch()
            try:
                async with asyncio.timeout(timeout):
                    async with httpx.AsyncClient(verify=self._ssl_verify, trust_env=False, timeout=timeout) as client:
                        response = await client.post(self._base_url, headers=self._headers, json=body)
                        response.raise_for_status()
                        try:
                            payload = response.json()
                        except ValueError as exc:
                            raise InvalidEmbeddingResponse("Invalid embedding JSON") from exc
                        vectors = _embedding_vectors(payload, len(data["input"]))
            except BaseException as error:
                if observation is not None:
                    observation.finish(error)
                raise
            if observation is not None:
                observation.record_provider_counts(read_openai_token_counts(payload.get("usage")))
                observation.complete(None)
                observation.finish()
            return vectors

    async def dimension_check(self, timeout: float = 5.0) -> List[List[float]]:
        """Runs a connectivity check with a sample text input.

        Args:
            timeout: Timeout in seconds for the check.

        Returns:
            The embedding vectors from the sample request, or an empty list if
            the check fails.
        """
        try:
            with suppress_model_attempts():
                return await run_blocking(
                    "gateway-embedding-connectivity",
                    self.get_embeddings,
                    "Hello, nexent!",
                    timeout=timeout,
                )
        except requests.exceptions.Timeout as error:
            if not record_connectivity_failure(error):
                logging.error(f"OpenAI embedding connection timed out ({timeout}s)")
            return []
        except requests.exceptions.ConnectionError as error:
            if not record_connectivity_failure(error):
                logging.error("OpenAI embedding connection error")
            return []
        except Exception as error:
            if not record_connectivity_failure(error):
                logging.exception("OpenAI embedding connection failed")
            return []

    async def invoke(self, request: EmbeddingRequest):
        """Embed ``request.inputs`` (text), offloaded to a worker thread."""
        worker_options = {"lane": request.worker_lane} if request.worker_lane is not None else {}
        return await run_blocking(
            "gateway-embedding-invoke",
            self.get_embeddings, request.inputs,
            with_metadata=request.with_metadata, timeout=request.timeout,
            retries=request.retries, retry_timeout_step=request.retry_timeout_step, **worker_options,
        )

    def get_model_info(self) -> ModelInfo:
        """Return ``ModelInfo`` with text capability (no multimodal)."""
        return ModelInfo(self._context.model_name, self._context.display_name or "", self.factory, {"text": True, "multimodal": False})
