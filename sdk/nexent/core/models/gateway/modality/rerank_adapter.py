"""Rerank adapter — protocol implementation sunk in (no _model wrapper).

The rerank protocol (OpenAI-compatible + DashScope URL-sniff request formatting,
retry, connectivity check) lives directly in the adapter. The old
``rerank_model.py`` classes (``OpenAICompatibleRerank`` / ``JinaRerank`` /
``CohereRerank``) are deleted; this adapter IS the implementation.
"""

from __future__ import annotations

import asyncio
import logging
from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

from ..multimodal_adapter import ModelInfo, MultimodalAdapter
from ..model_context import ModelContext
from ..registry import register_adapter
from ..transport import HttpTransportMixin

logger = logging.getLogger(__name__)


@dataclass
class RerankRequest:
    """Rerank request.

    Attributes:
        query: The query to rerank documents against.
        documents: The documents to rerank.
        top_n: Optional limit on the number of returned documents.
    """

    query: str
    documents: List[str]
    top_n: Optional[int] = None


class RerankAdapter(MultimodalAdapter):
    """Rerank adapter root.

    Attributes:
        modality: ``"rerank"``.
    """

    modality = "rerank"

    @abstractmethod
    async def invoke(self, request: RerankRequest) -> List[Dict[str, Any]]:
        """Reranks ``request.documents`` for ``request.query``.

        Args:
            request: The rerank request containing the query and documents.

        Returns:
            The reranked result list.
        """


@register_adapter("openai", "rerank")
class OpenAICompatibleRerankAdapter(RerankAdapter, HttpTransportMixin):
    """OpenAI-compatible rerank — supports any OpenAI-rerank-format API.

    DashScope is auto-detected by URL (``dashscope`` in base_url) and uses the
    ``input``/``parameters`` wrapper; otherwise the flat OpenAI format is used.

    Attributes:
        modality: ``"rerank"``.
        factory: ``"openai"``.
        _headers: HTTP auth headers built from the API key.
    """

    factory = "openai"

    def __init__(self, context: ModelContext) -> None:
        MultimodalAdapter.__init__(self, context)
        HttpTransportMixin.__init__(
            self,
            base_url=context.base_url,
            api_key=context.api_key,
            ssl_verify=context.ssl_verify,
            timeout=context.extra.get("timeout_seconds", 30.0),
        )
        self._headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

    # ---- protocol (moved from OpenAICompatibleRerank) ----

    @property
    def _model_name(self) -> str:
        """The model name from the construction context."""
        return self._context.model_name

    def _prepare_request(
        self, query: str, documents: List[str], top_n: Optional[int] = None
    ) -> Dict[str, Any]:
        """Build the rerank request payload.

        DashScope is auto-detected by URL (``dashscope`` in base_url) and uses
        the ``input``/``parameters`` wrapper; otherwise the flat OpenAI format
        is used.
        """
        if "dashscope" in (self._base_url or "").lower():
            return {
                "model": self._model_name,
                "input": {"query": query, "documents": documents},
                "parameters": {"top_n": top_n or len(documents)},
            }
        return {
            "model": self._model_name,
            "query": query,
            "documents": documents,
            "top_n": top_n or len(documents),
        }

    def _make_request(
        self, data: Dict[str, Any], timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """POST the payload to the rerank endpoint and return the JSON.

        Raises:
            requests.exceptions.RequestException: If the HTTP request fails.
        """
        response = requests.post(
            self._base_url,
            headers=self._headers,
            json=data,
            timeout=timeout,
            verify=self._ssl_verify,
        )
        response.raise_for_status()
        return response.json()

    def rerank(
        self, query: str, documents: List[str], top_n: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Rerank documents against a query, retrying on timeout.

        Empty document lists short-circuit to an empty result. Timeouts are
        retried with increasing timeouts (30s base, +10s per attempt, up to 4
        attempts); other request errors fail immediately.

        Args:
            query: The query to rerank documents against.
            documents: The documents to rerank.
            top_n: Optional limit on the number of returned documents.

        Returns:
            A list of ``{"index", "relevance_score", "document"}`` dicts.

        Raises:
            requests.exceptions.Timeout: If all timeout retries are exhausted.
            requests.exceptions.RequestException: If the request fails.
        """
        if not documents:
            return []
        data = self._prepare_request(query, documents, top_n)
        base_timeout = 30.0
        attempts = 4
        last_exception = None
        for attempt_index in range(attempts):
            current_timeout = base_timeout + attempt_index * 10.0
            try:
                response = self._make_request(data, timeout=current_timeout)
                results = response.get("results") or response.get("output", {}).get(
                    "results", []
                )
                reranked = []
                for r in results:
                    doc = r.get("document")
                    doc_text = doc.get("text") if isinstance(doc, dict) else doc
                    reranked.append(
                        {
                            "index": r.get("index"),
                            "relevance_score": r.get("relevance_score"),
                            "document": doc_text,
                        }
                    )
                return reranked
            except requests.exceptions.Timeout as e:
                logging.warning(
                    f"Rerank API timed out in {current_timeout}s (attempt {attempt_index + 1}/{attempts})"
                )
                last_exception = e
                if attempt_index == attempts - 1:
                    logging.error("Rerank API timed out after all retries.")
                    raise
                continue
            except requests.exceptions.RequestException as e:
                logging.error(f"Rerank API request failed: {str(e)}")
                raise
        if last_exception:
            raise last_exception
        return []

    async def rerank_async(
        self, query: str, documents: List[str], top_n: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Rerank documents against a query, offloaded to a worker thread.

        Args:
            query: The query to rerank documents against.
            documents: The documents to rerank.
            top_n: Optional limit on the number of returned documents.

        Returns:
            A list of rerank result dicts (see :meth:`rerank`).
        """
        return await asyncio.to_thread(self.rerank, query, documents, top_n)

    async def connectivity_check(self, timeout: float = 5.0) -> bool:
        """Verify the rerank endpoint is reachable with a probe rerank call.

        Args:
            timeout: Timeout in seconds for the probe.

        Returns:
            True if the probe succeeds, False on timeout/connection/other error.
        """
        try:
            await asyncio.to_thread(
                self.rerank, "test query", ["test document"], top_n=1
            )
            return True
        except requests.exceptions.Timeout:
            logging.error(f"Rerank API connection test timed out ({timeout} seconds)")
            return False
        except requests.exceptions.ConnectionError:
            logging.error("Rerank API connection error, unable to establish connection")
            return False
        except Exception as e:
            logging.error(f"Rerank API connectivity check failed: {str(e)}")
            return False

    # ---- adapter interface ----

    async def invoke(self, request: RerankRequest) -> List[Dict[str, Any]]:
        """Rerank ``request.documents`` offloaded to a worker thread."""
        return await asyncio.to_thread(
            self.rerank, request.query, request.documents, request.top_n
        )

    async def health_check(self) -> bool:
        """Delegate to :meth:`connectivity_check`."""
        return await self.connectivity_check()

    def get_model_info(self) -> ModelInfo:
        """Return ``ModelInfo`` with the ``rerank`` capability."""
        return ModelInfo(
            model_id=self._context.model_name,
            display_name=self._context.display_name or "",
            provider=self.factory,
            capabilities={"rerank": True},
        )


def _apply_defaults(context: ModelContext, base_url: str, model_name: str) -> None:
    """Apply default base_url/model to ``context`` in place when they are unset."""
    if not context.base_url:
        context.base_url = base_url
    if not context.model_name:
        context.model_name = model_name


@register_adapter("jina", "rerank")
class JinaRerankAdapter(OpenAICompatibleRerankAdapter):
    """Jina AI rerank — default base_url/model applied when the cfg omits them.

    Attributes:
        factory: ``"jina"``.
    """

    factory = "jina"

    def __init__(self, context: ModelContext) -> None:
        _apply_defaults(context, "https://api.jina.ai/v1/rerank", "jina-rerank-v2-base")
        super().__init__(context)


@register_adapter("cohere", "rerank")
class CohereRerankAdapter(OpenAICompatibleRerankAdapter):
    """Cohere rerank — default base_url/model applied when the cfg omits them.

    Attributes:
        factory: ``"cohere"``.
    """

    factory = "cohere"

    def __init__(self, context: ModelContext) -> None:
        _apply_defaults(context, "https://api.cohere.ai/v1/rerank", "rerank-multilingual-v3.0")
        super().__init__(context)
