import asyncio
import base64
import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlsplit, urlunsplit

import requests

from ...monitor.monitoring import record_model_call

# Path to test assets directory
ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "assets")

logger = logging.getLogger(__name__)

_EMBEDDING_ERROR_FIELDS = {
    "code",
    "detail",
    "error",
    "error_code",
    "message",
    "msg",
    "param",
    "request_id",
    "status",
    "status_code",
    "type",
}
_EMBEDDING_SENSITIVE_FIELDS = {
    "access_token",
    "api_key",
    "authorization",
    "content",
    "data",
    "embedding",
    "embeddings",
    "input",
    "inputs",
    "prompt",
    "prompts",
    "token",
}


def _safe_embedding_endpoint(url: str) -> str:
    """Return an endpoint without query parameters or credentials."""
    try:
        parsed = urlsplit(url)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    except Exception:
        return "<invalid-url>"


def _embedding_input_diagnostics(inputs: Any) -> Dict[str, Any]:
    """Describe embedding inputs without logging their content."""
    items = inputs if isinstance(inputs, list) else [inputs]
    lengths: List[int] = []
    item_types = set()
    empty_count = 0

    for item in items:
        item_types.add(type(item).__name__)
        if isinstance(item, str):
            length = len(item)
            empty_count += int(not item.strip())
        else:
            try:
                length = len(json.dumps(item, ensure_ascii=False, default=str))
            except Exception:
                length = len(str(item))
        lengths.append(length)

    return {
        "input_count": len(items),
        "input_types": sorted(item_types),
        "empty_count": empty_count,
        "total_chars": sum(lengths),
        "min_chars": min(lengths, default=0),
        "max_chars": max(lengths, default=0),
        "char_lengths": lengths[:20],
        "char_lengths_truncated": len(lengths) > 20,
    }


def _sanitize_embedding_error_value(value: Any, secrets: List[str], depth: int = 0) -> Any:
    """Keep provider error metadata while redacting request payloads and credentials."""
    if depth > 4:
        return "<max-depth>"
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            normalized_key = str(key).lower()
            if normalized_key in _EMBEDDING_SENSITIVE_FIELDS:
                sanitized[str(key)] = "<redacted>"
            elif normalized_key in _EMBEDDING_ERROR_FIELDS:
                sanitized[str(key)] = _sanitize_embedding_error_value(item, secrets, depth + 1)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_embedding_error_value(item, secrets, depth + 1) for item in value[:10]]
    if isinstance(value, str):
        sanitized = value
        for secret in secrets:
            if secret:
                sanitized = sanitized.replace(secret, "<redacted>")
        return sanitized[:1000]
    return value


def _embedding_error_response_summary(response: Any, inputs: Any, api_key: Optional[str]) -> Dict[str, Any]:
    """Extract a safe provider error summary without exposing source text or credentials."""
    input_items = inputs if isinstance(inputs, list) else [inputs]
    secrets = [api_key or ""] + [item for item in input_items if isinstance(item, str)]
    summary: Dict[str, Any] = {
        "status_code": getattr(response, "status_code", None),
    }

    headers = getattr(response, "headers", {}) or {}
    for header_name in ("x-request-id", "request-id", "x-trace-id", "trace-id"):
        request_id = headers.get(header_name)
        if request_id:
            summary["provider_request_id"] = str(request_id)[:200]
            break

    try:
        payload = response.json()
    except Exception:
        response_text = getattr(response, "text", "") or ""
        summary["response_format"] = "non-json"
        summary["response_body_chars"] = len(response_text)
        return summary

    sanitized_payload = _sanitize_embedding_error_value(payload, secrets)
    if sanitized_payload:
        summary["provider_error"] = sanitized_payload
    elif isinstance(payload, dict):
        summary["response_keys"] = sorted(str(key) for key in payload.keys())[:20]
    return summary


def _detect_image_mime(img_bytes: bytes) -> str:
    """Detect image MIME type from raw bytes. Falls back to image/jpeg when unknown."""
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


class JinaEmbedding(MultimodalEmbedding):
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.jina.ai/v1/embeddings",
        model_name: str = "jina-clip-v2",
        embedding_dim: int = 1024,
        ssl_verify: bool = True,
        model_type: str = "multimodal"
    ):
        """Initialize JinaEmbedding with configuration."""
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

    def _prepare_multimodal_input(self, inputs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Prepare the input data for the API request.

        Args:
            inputs: List of dictionaries with 'text' or 'image' keys.
                - Text: {"text": "string"}
                - Image: {"image": "url_string" | "data:..." | bytes}
        """
        prepared = []
        for item in inputs:
            if "text" in item:
                prepared.append(item)
            elif "image" in item:
                img = item["image"]
                # If img is bytes, encode to data URL with correct MIME type
                if isinstance(img, bytes):
                    mime = _detect_image_mime(img)
                    img = f"data:{mime};base64,{base64.b64encode(img).decode('utf-8')}"
                prepared.append({"image": img})
            else:
                prepared.append(item)
        return {"model": self.model, "input": prepared, "truncate": True}

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
                    f"JinaEmbedding API connection test timed out in {current_timeout}s ({attempt_index + 1}/{attempts})"
                )
                last_timeout = e
                if attempt_index == attempts - 1:
                    logging.error("JinaEmbedding API connection test timed out.")
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
            >>> jina = JinaEmbedding()
            >>> inputs = [
            ...     {"text": "A beautiful sunset over the beach"},
            ...     {"image": "https://example.com/image.jpg"}
            ... ]
            >>> embeddings = jina.get_multimodal_embeddings(inputs)
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

                    embeddings = [item["embedding"] for item in response["data"]]
                    return embeddings
                except requests.exceptions.Timeout as e:
                    logging.warning(
                        f"JinaEmbedding API connection test timed out in {current_timeout}s ({attempt_index + 1}/{attempts})"
                    )
                    last_timeout = e
                    if attempt_index == attempts - 1:
                        logging.error("JinaEmbedding API connection test timed out.")
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


class DashScopeMultimodalEmbedding(MultimodalEmbedding):
    """DashScope multimodal embedding model (tongyi-embedding-vision)."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model_name: str,
        embedding_dim: int = 1024,
        ssl_verify: bool = True,
    ):
        """Initialize DashScopeMultimodalEmbedding with configuration."""
        self.api_key = api_key
        self.api_url = base_url
        self.model = model_name
        self.embedding_dim = embedding_dim
        self.ssl_verify = ssl_verify
        self.model_type = "multimodal"

        self.session = requests.Session()
        self.session.trust_env = False
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

    def _prepare_multimodal_input(self, inputs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Prepare DashScope-compatible multimodal input format.

        DashScope accepts image URLs or Base64 data URIs. Raw image bytes are
        encoded as PNG data URIs before being sent to the API.
        """
        normalized = []
        for item in inputs:
            if "image" in item:
                img = item["image"]
                if isinstance(img, bytes):
                    img = f"data:image/png;base64,{base64.b64encode(img).decode('utf-8')}"
                normalized.append({"image": img})
            else:
                normalized.append(item)
        return {
            "model": self.model,
            "input": {"contents": normalized}
        }

    def _make_request(self, data: Dict[str, Any], timeout: Optional[float] = None) -> Dict[str, Any]:
        response = self.session.post(
            self.api_url,
            headers=self.headers,
            json=data,
            timeout=timeout,
            verify=self.ssl_verify
        )
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
        if isinstance(inputs, str):
            multimodal_inputs = [{"text": inputs}]
        else:
            multimodal_inputs = [{"text": item} for item in inputs]
        return self.get_multimodal_embeddings(multimodal_inputs, with_metadata, timeout, retries, retry_timeout_step)

    def get_multimodal_embeddings(
        self,
        inputs: List[Dict[str, str]],
        with_metadata: bool = False,
        timeout: Optional[float] = None,
        retries: int = 3,
        retry_timeout_step: float = 5.0,
    ) -> Union[List[List[float]], Dict[str, Any]]:
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

                    embeddings = [item["embedding"] for item in response["output"]["embeddings"]]
                    return embeddings
                except requests.exceptions.Timeout as e:
                    logging.warning(
                        f"DashScopeMultimodalEmbedding API timed out in {current_timeout}s ({attempt_index + 1}/{attempts})"
                    )
                    last_timeout = e
                    if attempt_index == attempts - 1:
                        logging.error("DashScopeMultimodalEmbedding API timed out.")
                        raise
                    continue

            if last_timeout:
                raise last_timeout
            return []

    async def dimension_check(self, timeout: float = 5.0) -> List[List[float]]:
        try:
            # DashScope multimodal embedding requires BOTH text and image in contents
            test_image_path = os.path.join(ASSETS_DIR, "test.png")
            with open(test_image_path, "rb") as f:
                image_data = f.read()
            image_base64 = base64.b64encode(image_data).decode("utf-8")

            test_inputs = [
                {"text": "Hello, nexent!"},
                {"image": f"data:image/png;base64,{image_base64}"}
            ]
            embeddings = await asyncio.to_thread(self.get_multimodal_embeddings, test_inputs, timeout=timeout)
            return embeddings
        except requests.exceptions.Timeout:
            logging.error(f"DashScopeMultimodalEmbedding connection timed out ({timeout} seconds)")
            return []
        except requests.exceptions.ConnectionError:
            logging.error("DashScopeMultimodalEmbedding connection error")
            return []
        except Exception as e:
            logging.error(f"DashScopeMultimodalEmbedding connection failed: {str(e)}")
            return []


class SiliconflowMultimodalEmbedding(MultimodalEmbedding):
    """Siliconflow multimodal embedding model (Qwen/Qwen3-VL-Embedding-8B etc.)."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model_name: str,
        embedding_dim: int = 1024,
        ssl_verify: bool = True,
    ):
        """Initialize SiliconflowMultimodalEmbedding with configuration."""
        self.api_key = api_key
        self.api_url = base_url
        self.model = model_name
        self.embedding_dim = embedding_dim
        self.ssl_verify = ssl_verify
        self.model_type = "multimodal"

        self.session = requests.Session()
        self.session.trust_env = False
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

    def _prepare_multimodal_input(self, inputs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Prepare Siliconflow-compatible multimodal input format.

        Siliconflow API expects:
        - Text: {"text": "..."} or plain string
        - Image: {"image": "data:image/xxx;base64,..."} or {"image": "url"}
        """
        prepared = []
        for item in inputs:
            if "text" in item:
                prepared.append(item["text"])
            elif "image" in item:
                img = item["image"]
                # If img is bytes, encode to data URL with correct MIME type
                if isinstance(img, bytes):
                    mime = _detect_image_mime(img)
                    img = f"data:{mime};base64,{base64.b64encode(img).decode('utf-8')}"
                prepared.append({"image": img})
            else:
                prepared.append(item)
        return {"model": self.model, "input": prepared}

    def _make_request(self, data: Dict[str, Any], timeout: Optional[float] = None) -> Dict[str, Any]:
        response = self.session.post(
            self.api_url,
            headers=self.headers,
            json=data,
            timeout=timeout,
            verify=self.ssl_verify
        )
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
        if isinstance(inputs, str):
            multimodal_inputs = [{"text": inputs}]
        else:
            multimodal_inputs = [{"text": item} for item in inputs]
        return self.get_multimodal_embeddings(multimodal_inputs, with_metadata, timeout, retries, retry_timeout_step)

    def get_multimodal_embeddings(
        self,
        inputs: List[Dict[str, Any]],
        with_metadata: bool = False,
        timeout: Optional[float] = None,
        retries: int = 3,
        retry_timeout_step: float = 5.0,
    ) -> Union[List[List[float]], Dict[str, Any]]:
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

                    embeddings = [item["embedding"] for item in response["data"]]
                    return embeddings
                except requests.exceptions.Timeout as e:
                    logging.warning(
                        f"SiliconflowMultimodalEmbedding API timed out in {current_timeout}s ({attempt_index + 1}/{attempts})"
                    )
                    last_timeout = e
                    if attempt_index == attempts - 1:
                        logging.error("SiliconflowMultimodalEmbedding API timed out.")
                        raise
                    continue

            if last_timeout:
                raise last_timeout
            return []

    async def dimension_check(self, timeout: float = 5.0) -> List[List[float]]:
        try:
            test_image_path = os.path.join(ASSETS_DIR, "test.png")
            with open(test_image_path, "rb") as f:
                image_data = f.read()
            test_inputs = [
                {"text": "Hello, nexent!"},
                {"image": image_data}
            ]
            embeddings = await asyncio.to_thread(self.get_multimodal_embeddings, test_inputs, timeout=timeout)
            return embeddings
        except requests.exceptions.Timeout:
            logging.error(f"SiliconflowMultimodalEmbedding connection timed out ({timeout} seconds)")
            return []
        except requests.exceptions.ConnectionError:
            logging.error("SiliconflowMultimodalEmbedding connection error")
            return []
        except Exception as e:
            logging.error(f"SiliconflowMultimodalEmbedding connection failed: {str(e)}")
            return []


class OpenAICompatibleEmbedding(TextEmbedding):
    def __init__(self, model_name: str, base_url: str, api_key: str, embedding_dim: int, model_type: str = "embedding", ssl_verify: bool = True):
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
        response = self.session.post(
            self.api_url,
            headers=self.headers,
            json=data,
            timeout=timeout,
            verify=self.ssl_verify,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError:
            logger.error(
                "[EMBEDDING HTTP ERROR] endpoint=%s model=%s timeout=%s input=%s response=%s",
                _safe_embedding_endpoint(self.api_url),
                self.model,
                timeout,
                _embedding_input_diagnostics(data.get("input", [])),
                _embedding_error_response_summary(
                    response,
                    data.get("input", []),
                    self.api_key,
                ),
            )
            raise
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
