import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union

import requests


class BaseImageGeneration(ABC):
    """
    Abstract base class for image generation models.
    """

    @abstractmethod
    def __init__(
        self,
        model_name: str = None,
        base_url: str = None,
        api_key: str = None,
        ssl_verify: bool = True,
    ):
        pass

    @abstractmethod
    async def connectivity_check(self, timeout: float = 5.0) -> bool:
        """
        Test the connectivity to the image generation API.

        Args:
            timeout: Timeout in seconds

        Returns:
            bool: True if connection is successful, False otherwise
        """
        pass


class OpenAICompatibleImageGeneration(BaseImageGeneration):
    """
    OpenAI-compatible image generation implementation.
    Supports any API that follows the OpenAI image generation format.
    """

    def __init__(
        self,
        model_name: str,
        base_url: str,
        api_key: str,
        ssl_verify: bool = True,
    ):
        """
        Initialize OpenAICompatibleImageGeneration with configuration.

        Args:
            model_name: Name of the image generation model
            base_url: Base URL of the image generation API
            api_key: API key for the image generation API
            ssl_verify: Whether to verify SSL certificates for network requests
        """
        self.model = model_name
        # Handle URLs that may already include /images/generations or /v1 path
        base_url = base_url.rstrip("/")
        if "/images/generations" in base_url:
            self.api_url = base_url
        elif base_url.endswith("/v1"):
            self.api_url = base_url + "/images/generations"
        else:
            self.api_url = base_url + "/images/generations"
        self.api_key = api_key
        self.ssl_verify = ssl_verify
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

    async def connectivity_check(self, timeout: float = 5.0) -> bool:
        """
        Test the connectivity to the image generation API.

        Args:
            timeout: Timeout in seconds

        Returns:
            bool: True if connection is successful, False otherwise
        """
        try:
            # Use a minimal prompt and size for connectivity test
            data = {
                "model": self.model,
                "prompt": "test",
                "n": 1,
                "size": "256x256"
            }

            await asyncio.to_thread(
                self._make_request,
                data,
                timeout
            )
            return True

        except requests.exceptions.Timeout:
            logging.error(f"Image generation API connection test timed out ({timeout} seconds)")
            return False
        except requests.exceptions.ConnectionError:
            logging.error("Image generation API connection error, unable to establish connection")
            return False
        except Exception as e:
            logging.error(f"Image generation API connectivity check failed: {str(e)}")
            return False

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
