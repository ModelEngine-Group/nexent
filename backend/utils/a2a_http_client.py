"""
HTTP client utilities for A2A protocol communication.
"""
import asyncio
import logging
from typing import Any, AsyncIterator, Dict, Optional
import aiohttp

logger = logging.getLogger(__name__)

# Default timeout for A2A requests (5 minutes)
DEFAULT_TIMEOUT = 300.0
# Shorter timeout for lightweight requests like agent-card (10 seconds)
AGENT_CARD_TIMEOUT = 10.0
# Retry settings
DEFAULT_MAX_RETRIES = 3
RETRY_BACKOFF_FACTOR = 0.5

# Runtime error message
ERR_CLIENT_NOT_INITIALIZED = "Client not initialized. Use async context manager."
# Content type / accept header for JSON payloads
CONTENT_TYPE_JSON = "application/json"


class A2AHttpClient:
    """HTTP client for A2A protocol communication."""

    def __init__(
        self,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES
    ):
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.max_retries = max_retries
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        connector = aiohttp.TCPConnector(
            limit=100,
            limit_per_host=20,
            ttl_dns_cache=300,
            enable_cleanup_closed=True,
            force_close=True,  # Disable keep-alive to avoid server closing connection mid-response
        )
        self._session = aiohttp.ClientSession(
            timeout=self.timeout,
            connector=connector,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session:
            await self._session.close()

    async def _handle_retryable(
        self,
        exc: Exception,
        attempt: int,
        url: str,
        context: str
    ) -> None:
        """Handle a retryable exception. Raises if all retries exhausted."""
        if attempt < self.max_retries - 1:
            wait_time = RETRY_BACKOFF_FACTOR * (2 ** attempt)
            error_type = type(exc).__name__
            logger.warning(
                f"{context} for {url}: [{error_type}] {exc}, "
                f"retrying in {wait_time}s (attempt {attempt + 1}/{self.max_retries})"
            )
            await asyncio.sleep(wait_time)
        else:
            logger.error(f"All retries exhausted for {url}: {context} - {exc}")
            raise exc

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        read_response: bool = True,
        **kwargs
    ) -> aiohttp.ClientResponse:
        """Execute HTTP request with automatic retry on transient failures.

        Args:
            method: HTTP method
            url: Target URL
            read_response: If True, return (status, body_text). If False, return response object.
            **kwargs: Additional arguments for the request
        """
        last_exception = None

        for attempt in range(self.max_retries):
            try:
                async with await self._session.request(method, url, **kwargs) as response:
                    if response.status < 500 and not read_response:
                        return response
                    body = await response.read()
                    if response.status < 500:
                        return (response.status, body)
                    if attempt < self.max_retries - 1:
                        wait_time = RETRY_BACKOFF_FACTOR * (2 ** attempt)
                        logger.warning(
                            f"HTTP {response.status} for {url}, "
                            f"retrying in {wait_time}s (attempt {attempt + 1}/{self.max_retries})"
                        )
                        await asyncio.sleep(wait_time)
                        continue
                    return (response.status, body)
            except (aiohttp.ClientConnectionResetError, aiohttp.ServerDisconnectedError) as e:
                last_exception = e
                await self._handle_retryable(e, attempt, url, type(e).__name__)
            except aiohttp.ClientError as e:
                last_exception = e
                await self._handle_retryable(e, attempt, url, "Request failed")
            except asyncio.TimeoutError as e:
                last_exception = e
                await self._handle_retryable(e, attempt, url, "Request timeout")

        if last_exception:
            raise last_exception
        raise aiohttp.ClientError(f"Request failed after {self.max_retries} attempts")

    async def get_json(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Send a GET request and return JSON response."""
        if not self._session:
            raise RuntimeError(ERR_CLIENT_NOT_INITIALIZED)

        # Add default headers if not provided
        request_headers = {
            "User-Agent": "Nexent-A2A-Client/1.0",
            "Accept": CONTENT_TYPE_JSON,
            "Connection": "close",
        }
        if headers:
            request_headers.update(headers)

        logger.debug(f"A2A GET request: url={url}")

        try:
            _, body = await self._request_with_retry(
                "GET",
                url,
                headers=request_headers
            )
            # Parse JSON from body
            import json
            data = json.loads(body.decode('utf-8'))
            return data
        except asyncio.TimeoutError as e:
            logger.error(f"A2A GET timeout for {url}: {e}")
            raise
        except aiohttp.ClientResponseError as e:
            logger.error(f"A2A GET HTTP error for {url}: {e.status}")
            raise
        except Exception as e:
            import traceback
            logger.error(f"A2A GET request failed for {url}: {type(e).__name__}: {e}\n{traceback.format_exc()}")
            raise

    async def post_json(
        self,
        url: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Send a POST request and return JSON response."""
        if not self._session:
            raise RuntimeError(ERR_CLIENT_NOT_INITIALIZED)

        # Add default headers if not provided
        request_headers = {
            "Content-Type": CONTENT_TYPE_JSON,
            "Accept": CONTENT_TYPE_JSON,
            "Connection": "close",
        }
        if headers:
            request_headers.update(headers)

        logger.info(f"A2A POST request: url={url}, payload={payload}")

        try:
            _, body = await self._request_with_retry(
                "POST",
                url,
                json=payload,
                headers=request_headers
            )
            # Parse JSON from body
            import json
            data = json.loads(body.decode('utf-8'))
            return data
        except asyncio.TimeoutError as e:
            logger.error(f"A2A POST timeout for {url}: {e}")
            raise
        except aiohttp.ClientResponseError as e:
            logger.error(f"A2A POST HTTP error for {url}: {e.status}")
            raise
        except Exception as e:
            import traceback
            logger.error(f"A2A POST request failed for {url}: {type(e).__name__}: {e}\n{traceback.format_exc()}")
            raise

    async def post_stream(
        self,
        url: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """Send a streaming POST request and yield SSE events."""
        if not self._session:
            raise RuntimeError(ERR_CLIENT_NOT_INITIALIZED)

        try:
            response = await self._session.post(
                url,
                json=payload,
                headers=headers
            )
            response.raise_for_status()

            async for line in response.content:
                decoded = line.decode('utf-8').strip()
                if decoded.startswith("data: "):
                    data_str = decoded[6:].strip()
                    if data_str:
                        import json
                        try:
                            yield json.loads(data_str)
                        except json.JSONDecodeError:
                            logger.warning(f"Failed to parse SSE data: {data_str}")
        except asyncio.TimeoutError as e:
            logger.error(f"A2A streaming timeout for {url}: {e}")
            raise
        except aiohttp.ClientResponseError as e:
            logger.error(f"A2A streaming HTTP error for {url}: {e.status}")
            raise
        except Exception as e:
            import traceback
            logger.error(f"A2A streaming request failed for {url}: {type(e).__name__}: {e}\n{traceback.format_exc()}")
            raise


def build_a2a_headers(api_key: Optional[str] = None) -> Dict[str, str]:
    """Build HTTP headers for A2A requests."""
    headers = {
        "Content-Type": CONTENT_TYPE_JSON,
        "Accept": CONTENT_TYPE_JSON,
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers
