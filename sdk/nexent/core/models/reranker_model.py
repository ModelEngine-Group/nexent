import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import requests


class BaseReranker(ABC):
    """
    Abstract base class for reranker models, defining methods that all reranker models should implement.
    """

    @abstractmethod
    def __init__(
        self,
        model_name: str = None,
        base_url: str = None,
        api_key: str = None,
        ssl_verify: bool = True,
    ):
        """
        Initialize the reranker model.

        Args:
            model_name: Name of the reranker model
            base_url: Base URL of the reranker API
            api_key: API key for the reranker API
            ssl_verify: Whether to verify SSL certificates for network requests
        """
        pass

    @abstractmethod
    def rerank(
        self,
        query: str,
        documents: List[str],
        top_n: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Rerank documents based on their relevance to the query.

        Args:
            query: The search query
            documents: List of document texts to rerank
            top_n: Number of top results to return (default: all documents)

        Returns:
            List of reranked results, each containing document index and relevance score
        """
        pass

    @abstractmethod
    async def connectivity_check(self, timeout: float = 5.0) -> bool:
        """
        Test the connectivity to the reranker API.

        Args:
            timeout: Timeout in seconds

        Returns:
            bool: Returns True if the connection is successful, False if it fails or times out
        """
        pass


class OpenAICompatibleReranker(BaseReranker):
    """
    OpenAI-compatible reranker implementation.
    Supports any API that follows the OpenAI reranking format.
    """

    def __init__(
        self,
        model_name: str,
        base_url: str,
        api_key: str,
        ssl_verify: bool = True,
    ):
        """
        Initialize OpenAICompatibleReranker with configuration.

        Args:
            model_name: Name of the reranker model
            base_url: Base URL of the reranker API
            api_key: API key for the reranker API
            ssl_verify: Whether to verify SSL certificates for network requests
        """
        self.model = model_name
        self.api_url = base_url
        self.api_key = api_key
        self.ssl_verify = ssl_verify
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

    def _prepare_request(self, query: str, documents: List[str], top_n: Optional[int] = None) -> Dict[str, Any]:
        """
        Prepare the request data for the API.

        Args:
            query: The search query
            documents: List of document texts to rerank
            top_n: Number of top results to return

        Returns:
            Dict containing the request payload
        """
        # DashScope rerank API uses "input" and "parameters" wrapper for ALL models (qwen3-rerank, gte-rerank-v2, etc.)
        if "dashscope" in self.api_url.lower():
            return {
                "model": self.model,
                "input": {
                    "query": query,
                    "documents": documents,
                },
                "parameters": {
                    "top_n": top_n or len(documents),
                },
            }
        # OpenAI-compatible format
        return {
            "model": self.model,
            "query": query,
            "documents": documents,
            "top_n": top_n or len(documents),
        }

    def _make_request(self, data: Dict[str, Any], timeout: Optional[float] = None) -> Dict[str, Any]:
        """
        Make the API request and return the response.

        Args:
            data: Request data
            timeout: Timeout in seconds

        Returns:
            Dict containing the API response
        """
        response = requests.post(
            self.api_url,
            headers=self.headers,
            json=data,
            timeout=timeout,
            verify=self.ssl_verify
        )
        response.raise_for_status()
        return response.json()

    def rerank(
        self,
        query: str,
        documents: List[str],
        top_n: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Rerank documents based on their relevance to the query.

        Args:
            query: The search query
            documents: List of document texts to rerank
            top_n: Number of top results to return

        Returns:
            List of reranked results with index and relevance_score
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
                # DashScope returns results in {"output": {"results": [...]}}
                # OpenAI-compatible returns {"results": [...]}
                results = response.get("results") or response.get("output", {}).get("results", [])

                reranked_results = []
                for r in results:
                    # DashScope returns document as {"text": "..."}, others return string directly
                    doc = r.get("document")
                    if isinstance(doc, dict):
                        doc_text = doc.get("text")
                    else:
                        doc_text = doc
                    reranked_results.append({
                        "index": r.get("index"),
                        "relevance_score": r.get("relevance_score"),
                        "document": doc_text,
                    })
                return reranked_results

            except requests.exceptions.Timeout as e:
                logging.warning(
                    f"Reranker API timed out in {current_timeout}s (attempt {attempt_index + 1}/{attempts})"
                )
                last_exception = e
                if attempt_index == attempts - 1:
                    logging.error("Reranker API timed out after all retries.")
                    raise
                continue

            except requests.exceptions.RequestException as e:
                logging.error(f"Reranker API request failed: {str(e)}")
                raise

        if last_exception:
            raise last_exception
        return []

    async def rerank_async(
        self,
        query: str,
        documents: List[str],
        top_n: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Async version of rerank.

        Args:
            query: The search query
            documents: List of document texts to rerank
            top_n: Number of top results to return

        Returns:
            List of reranked results
        """
        return await asyncio.to_thread(self.rerank, query, documents, top_n)

    async def connectivity_check(self, timeout: float = 5.0) -> bool:
        """
        Test the connectivity to the reranker API.

        Args:
            timeout: Timeout in seconds

        Returns:
            bool: True if connection is successful, False otherwise
        """
        try:
            test_query = "test query"
            test_documents = ["test document"]

            await asyncio.to_thread(
                self.rerank, test_query, test_documents, top_n=1
            )
            return True

        except requests.exceptions.Timeout:
            logging.error(f"Reranker API connection test timed out ({timeout} seconds)")
            return False
        except requests.exceptions.ConnectionError:
            logging.error("Reranker API connection error, unable to establish connection")
            return False
        except Exception as e:
            logging.error(f"Reranker API connectivity check failed: {str(e)}")
            return False


class JinaReranker(OpenAICompatibleReranker):
    """
    Jina AI reranker implementation.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.jina.ai/v1/rerank",
        model_name: str = "jina-reranker-v2-base",
        ssl_verify: bool = True,
    ):
        """
        Initialize JinaReranker with configuration.

        Args:
            api_key: API key for Jina AI
            base_url: Base URL of the Jina reranker API
            model_name: Name of the Jina reranker model
            ssl_verify: Whether to verify SSL certificates for network requests
        """
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            ssl_verify=ssl_verify,
        )


class CohereReranker(OpenAICompatibleReranker):
    """
    Cohere reranker implementation.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.cohere.ai/v1/rerank",
        model_name: str = "rerank-multilingual-v3.0",
        ssl_verify: bool = True,
    ):
        """
        Initialize CohereReranker with configuration.

        Args:
            api_key: API key for Cohere
            base_url: Base URL of the Cohere reranker API
            model_name: Name of the Cohere reranker model
            ssl_verify: Whether to verify SSL certificates for network requests
        """
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            ssl_verify=ssl_verify,
        )
