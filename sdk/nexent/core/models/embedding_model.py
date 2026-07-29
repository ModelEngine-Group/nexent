import asyncio
import base64
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union

import requests

from ...monitor.monitoring import record_model_call

# Path to test assets directory
ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "assets")


class BaseEmbedding(ABC):
    """
    Abstract base class for embedding models, defining methods that all embedding models should implement.
    """

    @abstractmethod
    def __init__(
        self,
        model_name: str = None,
        base_url: str = None,
        api_key: str = None,
        embedding_dim: int = None,
        ssl_verify: bool = True,
        model_type: str = None
    ):
        """
        Initialize the embedding model.

        Args:
            model_name: Name of the embedding model
            base_url: Base URL of the embedding API
            api_key: API key for the embedding API
            embedding_dim: Dimension of the embedding vector
            ssl_verify: Whether to verify SSL certificates for network requests
        """
        pass

    @abstractmethod
    def get_embeddings(
        self,
        inputs: Union[str, List[str]],
        with_metadata: bool = False,
        timeout: Optional[float] = None,
        retries: int = 3,
        retry_timeout_step: float = 5.0,
    ) -> Union[List[List[float]], Dict[str, Any]]:
        """
        Get the embedding vectors for the input.

        Args:
            inputs: Objects to be embedded
            with_metadata: Whether to return the full response with metadata
            timeout: Base timeout in seconds for the first attempt. If None, uses retry_timeout_step.
            retries: Number of retries on timeout (not counting the first attempt)
            retry_timeout_step: Linear increment in seconds for each retry timeout

        Returns:
            If with_metadata is False, returns a list of embedding vectors; otherwise, returns a dictionary containing embeddings and metadata
        """
        pass

    @abstractmethod
    async def dimension_check(self, timeout: float = 5.0) -> List[List[float]]:
        """
        Test the connectivity to the embedding API, supporting timeout detection.

        Args:
            timeout: Timeout in seconds

        Returns:
            bool: Returns True if the connection is successful, False if it fails or times out
        """
        pass


class TextEmbedding(BaseEmbedding):
    """
    Abstract class for text embedding models, specifically handling the task of vectorizing text.
    Input format is a string or an array of strings.
    """

    @abstractmethod
    def __init__(
        self,
        model_name: str = None,
        base_url: str = None,
        api_key: str = None,
        embedding_dim: int = None,
        ssl_verify: bool = True,
        model_type: str = None
    ):
        super().__init__(model_name, base_url, api_key, embedding_dim, ssl_verify=ssl_verify)

    @abstractmethod
    def get_embeddings(
        self,
        inputs: Union[str, List[str]],
        with_metadata: bool = False,
        timeout: Optional[float] = None,
        retries: int = 3,
        retry_timeout_step: float = 5.0,
    ) -> Union[List[List[float]], Dict[str, Any]]:
        """
        Get the embedding vectors for text inputs.

        Args:
            inputs: A text string or a list of text strings
            with_metadata: Whether to return the full response with metadata
            timeout: Base timeout in seconds for the first attempt. If None, uses retry_timeout_step
            retries: Number of retries on timeout (not counting the first attempt)
            retry_timeout_step: Linear increment in seconds for each retry timeout

        Returns:
            If with_metadata is False, returns a list of embedding vectors; otherwise, returns a dictionary containing embeddings and metadata
        """
        pass


class OpenAICompatibleEmbedding(TextEmbedding):
    def __init__(self, model_name: str, base_url: str, api_key: str, embedding_dim: int, model_type: str = "text", ssl_verify: bool = True):
        """Initialize OpenAICompatibleEmbedding with configuration from environment variables or provided parameters."""
        self.api_key = api_key
        self.api_url = base_url
        self.model = model_name
        self.embedding_dim = embedding_dim
        self.ssl_verify = ssl_verify
        self.model_type=model_type

        self.headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}

        # Create a session with trust_env=False to ignore proxy environment variables
        self.session = requests.Session()
        self.session.trust_env = False

    def _prepare_input(self, inputs: Union[str, List[str]]) -> Dict[str, Any]:
        """Prepare the input data for the API request."""
        if isinstance(inputs, str):
            inputs = [inputs]
        return {"model": self.model, "input": inputs}

    def _make_request(self, data: Dict[str, Any], timeout: Optional[float] = None) -> Dict[str, Any]:
        """
        Make the API request and return the response.

        Args:
            data: Request data
            timeout: Timeout in seconds

        Returns:
            Dict[str, Any]: API response
        """
        response = self.session.post(self.api_url, headers=self.headers, json=data, timeout=timeout, verify=self.ssl_verify)
        response.raise_for_status()
        return response.json()

    def get_embeddings(
        self,
        inputs: Union[str, List[str]],
        with_metadata: bool = False,
        timeout: Optional[float] = None,
        retries: int = 3,
        retry_timeout_step: float = 5.0,
    ) -> Union[List[List[float]], Dict[str, Any]]:
        """
        Get embeddings for text inputs.

        Args:
            inputs: A single text string or a list of text strings
            with_metadata: Whether to return the full response with metadata or just a list of embedding vectors
            timeout: Base timeout in seconds for the first attempt. If None, uses retry_timeout_step.
            retries: Number of retries on timeout (not counting the first attempt)
            retry_timeout_step: Linear increment in seconds for each retry timeout

        Returns:
            List of embedding vectors, or a dictionary with metadata if with_metadata is True.
        """
        with record_model_call("embedding", self.model, display_name=self.model):
            data = self._prepare_input(inputs)

            base_timeout = timeout if timeout is not None else retry_timeout_step
            attempts = retries + 1
            last_timeout: Optional[requests.exceptions.Timeout] = None
            for attempt_index in range(attempts):
                current_timeout = base_timeout + attempt_index * retry_timeout_step
                try:
                    response = self._make_request(data, timeout=current_timeout)

                    if with_metadata:
                        return response

                    embeddings = [item["embedding"] for item in response["data"]]
                    return embeddings
                except requests.exceptions.Timeout as e:
                    logging.warning(
                        f"OpenAI API connection test timed out in {current_timeout}s ({attempt_index + 1}/{attempts})"
                    )
                    last_timeout = e
                    if attempt_index == attempts - 1:
                        logging.error("OpenAI API connection test timed out.")
                        raise
                    continue

            if last_timeout:
                raise last_timeout
            return []

    async def dimension_check(self, timeout: float = 5.0) -> List[List[float]]:
        try:
            # Create a simple test input
            test_input = "Hello, nexent!"

            # Try to get embedding vectors in a background thread, setting a timeout
            embeddings = await asyncio.to_thread(self.get_embeddings, test_input, timeout=timeout)

            # If embedding vectors are successfully obtained, the connection is normal
            return embeddings

        except requests.exceptions.Timeout:
            logging.error(f"OpenAI API connection test timed out ({timeout} seconds)")
            return []
        except requests.exceptions.ConnectionError:
            logging.error("OpenAI API connection error, unable to establish connection")
            return []
        except Exception as e:
            logging.error(f"OpenAI API connection test failed: {str(e)}")
            return []


class MultimodalEmbedding(BaseEmbedding):
    """
    Abstract class for multimodal embedding models, capable of handling vectorization tasks for text, images, videos, etc.
    Input format is a list of dictionaries containing type information List[Dict[str, str]].
    """

    @abstractmethod
    def __init__(
        self,
        model_name: str = None,
        base_url: str = None,
        api_key: str = None,
        embedding_dim: int = None,
        ssl_verify: bool = True,
        model_type: str = None
    ):
        super().__init__(model_name, base_url, api_key, embedding_dim, ssl_verify=ssl_verify)

    @abstractmethod
    def get_multimodal_embeddings(
        self,
        inputs: List[Dict[str, str]],
        with_metadata: bool = False,
        timeout: Optional[float] = None,
        retries: int = 3,
        retry_timeout_step: float = 5.0,
    ) -> Union[List[List[float]], Dict[str, Any]]:
        """
        Get the embedding vectors for multimodal inputs.

        Args:
            inputs: A list of dictionaries containing type information, e.g., [{"text": "content"}, {"image": "image URL"}]
            with_metadata: Whether to return the full response with metadata
            timeout: Base timeout in seconds for the first attempt. If None, uses retry_timeout_step
            retries: Number of retries on timeout (not counting the first attempt)
            retry_timeout_step: Linear increment in seconds for each retry timeout

        Returns:
            If with_metadata is False, returns a list of embedding vectors; otherwise, returns a dictionary containing embeddings and metadata
        """
        pass


class OpenAICompatibleMultimodalEmbedding(MultimodalEmbedding):
    """OpenAI-compatible multimodal embedding implementation.

    This is the concrete implementation used for providers that follow the
    OpenAI embedding API contract (request body with an ``input`` list and a
    ``data[].embedding`` response). Provider-specific subclasses (Jina, Silicon,
    DashScope) inherit the shared HTTP/retry/timeout logic from this class and
    only override the hooks that differ between providers: ``__init__``
    defaults, ``_prepare_multimodal_input`` (request body shape) and
    ``_extract_embeddings`` (response parsing).
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.siliconflow.cn/v1/embeddings",
        model_name: str = "Qwen/Qwen3-VL-Embedding-8B",
        embedding_dim: int = 4096,
        ssl_verify: bool = True,
        model_type: str = "multimodal"
    ):
        """Initialize OpenAI-compatible multimodal embedding with configuration."""
        self.api_key = api_key
        self.api_url = base_url
        self.model = model_name
        self.embedding_dim = embedding_dim
        self.ssl_verify = ssl_verify
        self.model_type = model_type

        # Create a session with trust_env=False to ignore proxy environment variables
        self.session = requests.Session()
        self.session.trust_env = False

        self.headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}

    def _prepare_multimodal_input(self, inputs: List[Dict[str, str]]) -> Dict[str, Any]:
        """Prepare the input data for the API request."""
        return {"model": self.model, "input": inputs}

    def _extract_embeddings(self, response: Dict[str, Any]) -> List[List[float]]:
        """Extract embedding vectors from the API response."""
        return [item["embedding"] for item in response["data"]]

    def _make_request(self, data: Dict[str, Any], timeout: Optional[float] = None) -> Dict[str, Any]:
        """
        Make the API request and return the response.

        Args:
            data: Request data
            timeout: Timeout in seconds

        Returns:
            Dict[str, Any]: API response
        """
        response = self.session.post(self.api_url, headers=self.headers, json=data, timeout=timeout, verify=self.ssl_verify)
        response.raise_for_status()
        return response.json()

    def get_embeddings(
        self,
        inputs: Union[str, List[str]],
        with_metadata: bool = False,
        timeout: Optional[float] = None,
        retries: int = 3,
        retry_timeout_step: float = 5.0,
    ) -> Union[List[List[float]], Dict[str, Any]]:
        """
        Get embeddings for text inputs.
        Args:
            inputs: A single text string or a list of text strings.
            with_metadata: Whether to return the full response with metadata.
            timeout: Base timeout in seconds for the first attempt. If None, uses retry_timeout_step.
            retries: Number of retries on timeout (not counting the first attempt).
            retry_timeout_step: Linear increment in seconds for each retry timeout.
        Returns:
            A list of embedding vectors, or a dictionary with metadata if with_metadata is True.
        """
        if isinstance(inputs, str):
            multimodal_inputs = [{"text": inputs}]
        else:
            multimodal_inputs = [{"text": item} for item in inputs]

        base_timeout = timeout if timeout is not None else retry_timeout_step
        attempts = retries + 1
        last_timeout: Optional[requests.exceptions.Timeout] = None
        for attempt_index in range(attempts):
            current_timeout = base_timeout + attempt_index * retry_timeout_step
            try:
                return self.get_multimodal_embeddings(
                    multimodal_inputs, with_metadata=with_metadata, timeout=current_timeout
                )
            except requests.exceptions.Timeout as e:
                logging.warning(
                    f"{type(self).__name__} API connection test timed out in {current_timeout}s ({attempt_index + 1}/{attempts})"
                )
                last_timeout = e
                if attempt_index == attempts - 1:
                    logging.error(f"{type(self).__name__} API connection test timed out.")
                    raise
                continue

        if last_timeout:
            raise last_timeout
        return []

    def get_multimodal_embeddings(
        self,
        inputs: List[Dict[str, str]],
        with_metadata: bool = False,
        timeout: Optional[float] = None,
        retries: int = 3,
        retry_timeout_step: float = 5.0,
    ) -> Union[List[List[float]], Dict[str, Any]]:
        """
        Get embeddings for a list of inputs (text or image URLs).

        Args:
            inputs: List of dictionaries containing either 'text' or 'image' keys
            with_metadata: Whether to return the full response with metadata or just a list of embedding vectors
            timeout: Base timeout in seconds for the first attempt. If None, uses retry_timeout_step
            retries: Number of retries on timeout (not counting the first attempt)
            retry_timeout_step: Linear increment in seconds for each retry timeout

        Returns:
            List of embedding vectors

        Example:
            >>> model = OpenAICompatibleMultimodalEmbedding(api_key="...")
            >>> inputs = [
            ...     {"text": "A beautiful sunset over the beach"},
            ...     {"image": "https://example.com/image.jpg"}
            ... ]
            >>> embeddings = model.get_multimodal_embeddings(inputs)
        """
        with record_model_call("multi_embedding", self.model, display_name=self.model):
            data = self._prepare_multimodal_input(inputs)

            base_timeout = timeout if timeout is not None else retry_timeout_step
            attempts = retries + 1
            last_timeout: Optional[requests.exceptions.Timeout] = None
            for attempt_index in range(attempts):
                current_timeout = base_timeout + attempt_index * retry_timeout_step
                try:
                    response = self._make_request(data, timeout=current_timeout)

                    if with_metadata:
                        return response

                    return self._extract_embeddings(response)
                except requests.exceptions.Timeout as e:
                    logging.warning(
                        f"{type(self).__name__} API connection test timed out in {current_timeout}s ({attempt_index + 1}/{attempts})"
                    )
                    last_timeout = e
                    if attempt_index == attempts - 1:
                        logging.error(f"{type(self).__name__} API connection test timed out.")
                        raise
                    continue

            if last_timeout:
                raise last_timeout
            return []

    async def dimension_check(self, timeout: float = 5.0) -> List[List[float]]:
        try:
            # Create multimodal test input with both text and image
            test_image_path = os.path.join(ASSETS_DIR, "test.png")
            with open(test_image_path, "rb") as f:
                image_data = f.read()
            image_base64 = base64.b64encode(image_data).decode("utf-8")

            test_inputs = [
                {"text": "Hello, nexent!"},
                {"image": f"data:image/png;base64,{image_base64}"}
            ]

            # Try to get embedding vectors, setting a timeout
            embeddings = await asyncio.to_thread(self.get_multimodal_embeddings, test_inputs, timeout=timeout)

            # If embedding vectors are successfully obtained, the connection is normal
            return embeddings

        except requests.exceptions.Timeout:
            logging.error(f"Embedding API connection test timed out ({timeout} seconds)")
            return []
        except requests.exceptions.ConnectionError:
            logging.error("Embedding API connection error, unable to establish connection")
            return []
        except Exception as e:
            logging.error(f"Embedding API connection test failed: {str(e)}")
            return []


class JinaMultimodalEmbedding(OpenAICompatibleMultimodalEmbedding):
    """Jina multimodal embedding (jina-clip-v2).

    Differs from the OpenAI-compatible base only in the ``truncate`` flag type
    (Jina expects a boolean ``True`` instead of the string ``"right"``).
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.jina.ai/v1/embeddings",
        model_name: str = "jina-clip-v2",
        embedding_dim: int = 1024,
        ssl_verify: bool = True,
        model_type: str = "multimodal"
    ):
        """Initialize JinaMultimodalEmbedding with configuration."""
        super().__init__(api_key, base_url, model_name, embedding_dim, ssl_verify, model_type)

    def _prepare_multimodal_input(self, inputs: List[Dict[str, str]]) -> Dict[str, Any]:
        """Prepare the input data for the Jina API request."""
        return {"model": self.model, "input": inputs, "truncate": True}


class SiliconMultimodalEmbedding(OpenAICompatibleMultimodalEmbedding):
    """SiliconFlow multimodal embedding.

    Uses the same OpenAI-compatible request/response format and the same
    defaults as the base class; kept as a named subclass so callers can dispatch
    by provider factory name. SiliconFlow's Qwen3-VL expects ``truncate="right"``.
    """

    def _prepare_multimodal_input(self, inputs: List[Dict[str, str]]) -> Dict[str, Any]:
        """Prepare the input data for the SiliconFlow API request."""
        return {"model": self.model, "input": inputs, "truncate": "right"}


class DashScopeMultimodalEmbedding(OpenAICompatibleMultimodalEmbedding):
    """DashScope multimodal embedding (tongyi-embedding-vision).

    Overrides the request body shape (``input.contents``), the response parsing
    path (``output.embeddings``), and ``get_embeddings`` direct delegation to
    match the DashScope API contract.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model_name: str,
        embedding_dim: int = 1024,
        ssl_verify: bool = True,
        model_type: str = "multimodal"
    ):
        """Initialize DashScopeMultimodalEmbedding with configuration."""
        super().__init__(api_key, base_url, model_name, embedding_dim, ssl_verify, model_type)

    def _prepare_multimodal_input(self, inputs: List[Dict[str, str]]) -> Dict[str, Any]:
        """Prepare DashScope-compatible multimodal input format."""
        return {
            "model": self.model,
            "input": {"contents": inputs}
        }

    def _extract_embeddings(self, response: Dict[str, Any]) -> List[List[float]]:
        """Extract embedding vectors from the DashScope API response."""
        return [item["embedding"] for item in response["output"]["embeddings"]]

    def get_embeddings(
        self,
        inputs: Union[str, List[str]],
        with_metadata: bool = False,
        timeout: Optional[float] = None,
        retries: int = 3,
        retry_timeout_step: float = 5.0,
    ) -> Union[List[List[float]], Dict[str, Any]]:
        """Get embeddings for text inputs, delegating directly to the multimodal path."""
        if isinstance(inputs, str):
            multimodal_inputs = [{"text": inputs}]
        else:
            multimodal_inputs = [{"text": item} for item in inputs]
        return self.get_multimodal_embeddings(multimodal_inputs, with_metadata, timeout, retries, retry_timeout_step)


class VolcengineMultimodalEmbedding(OpenAICompatibleMultimodalEmbedding):
    """Volcengine multimodal embedding (doubao-embedding-vision).

    Volcengine ARK expects a typed ``input`` list where each entry declares its
    modality via a ``type`` field: ``text`` items carry a ``text`` string, and
    ``image_url`` items wrap the URL under an ``image_url.url`` object. This
    differs from the OpenAI-compatible base shape, so only the request body
    preparation is overridden; the OpenAI-style ``data[].embedding`` response is
    reused unchanged.
    """

    def _prepare_multimodal_input(self, inputs: List[Dict[str, str]]) -> Dict[str, Any]:
        """Prepare Volcengine ARK multimodal input format.

        Each internal ``{"text": ...}`` or ``{"image": ...}`` entry is converted
        into the typed structure expected by the doubao-embedding-vision API:
        ``{"type": "text", "text": ...}`` and
        ``{"type": "image_url", "image_url": {"url": ...}}``. Entries already in
        the provider's typed shape are passed through unchanged.
        """
        typed_inputs: List[Dict[str, Any]] = []
        for item in inputs:
            if "text" in item:
                typed_inputs.append({"type": "text", "text": item["text"]})
            elif "image" in item:
                typed_inputs.append({"type": "image_url", "image_url": {"url": item["image"]}})
            else:
                typed_inputs.append(item)
        return {"model": self.model, "input": typed_inputs}

    def _extract_embeddings(self, response: Dict[str, Any]) -> List[List[float]]:
        """Extract embedding vectors from the Volcengine ARK API response.

        Volcengine wraps the result under a single ``data.embedding`` object
        rather than the OpenAI-style ``data[].embedding`` list, so the vector
        is wrapped into a one-element list. A list-shaped ``data`` is also
        tolerated for forward compatibility with batch responses.
        """
        data = response["data"]
        if isinstance(data, dict):
            return [data["embedding"]]
        return [item["embedding"] for item in data]
