"""HTTP client for the AIDP native knowledge-base API."""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urljoin

import httpx

from nexent.utils.http_client_manager import http_client_manager

from .config import AIDP_API_KEY, AIDP_BASE_URL, AIDP_TENANT_ID, COUNT_PATH_KDS_ID


logger = logging.getLogger("aidp_knowledge_base_adapter")

_RETRY_DELAYS_SECONDS = (1, 2, 4)


class AidpAdapterError(RuntimeError):
    """Raised when the adapter cannot complete an AIDP request."""

    def __init__(self, message: str, status_code: int = 500, response_body: Any | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class AidpClient:
    """Small wrapper around the AIDP knowledge-base API."""

    def __init__(
        self,
        base_url: str = AIDP_BASE_URL,
        api_key: str = AIDP_API_KEY,
        tenant_id: str = AIDP_TENANT_ID,
        timeout: float = 120.0,
        verify_ssl: bool = False,
    ):
        if not base_url or not base_url.startswith(("http://", "https://")):
            raise ValueError("AIDP base URL must start with http:// or https://")
        if not api_key:
            raise ValueError("AIDP API key is required")

        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.tenant_id = tenant_id
        self._client = http_client_manager.get_sync_client(
            base_url=self.base_url,
            timeout=timeout,
            verify_ssl=verify_ssl,
        )

    def _headers(self, content_type: str | None = "application/json") -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _url(self, path: str) -> str:
        return urljoin(f"{self.base_url}/", path.lstrip("/"))

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = self._url(path)
        for attempt, retry_delay in enumerate((*_RETRY_DELAYS_SECONDS, None), start=1):
            try:
                response = self._client.request(method, url, **kwargs)
            except httpx.RequestError as exc:
                if retry_delay is None:
                    raise AidpAdapterError(f"AIDP request failed: {exc}", 503) from exc
                logger.warning(
                    "AIDP request attempt %d/4 failed for %s %s: %s; retrying in %ds",
                    attempt,
                    method,
                    path,
                    exc,
                    retry_delay,
                )
                time.sleep(retry_delay)
                continue

            if response.status_code == 200:
                return {} if not response.content else self._safe_json(response)

            if retry_delay is None:
                body = self._safe_json(response)
                message = self._extract_error_message(body) or f"AIDP HTTP error {response.status_code}"
                raise AidpAdapterError(message, response.status_code, body)

            logger.warning(
                "AIDP HTTP attempt %d/4 failed for %s %s with status %d; retrying in %ds",
                attempt,
                method,
                path,
                response.status_code,
                retry_delay,
            )
            time.sleep(retry_delay)

    @staticmethod
    def _safe_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return response.text

    @staticmethod
    def _extract_error_message(body: Any) -> str | None:
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict):
                return str(error.get("message") or error.get("code") or "")
            return str(body.get("message") or "")
        if isinstance(body, str):
            return body
        return None

    def health_check(self) -> bool:
        self.count_knowledge_bases(is_personal=0)
        return True

    def create_knowledge_base(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = f"/KnowledgeBase/Tenants/{self.tenant_id}/KnowledgeBases"
        return self._request("PUT", path, headers=self._headers(), json=payload)

    def list_knowledge_bases(self, page: int, page_size: int) -> dict[str, Any]:
        path = f"/KnowledgeBase/Tenants/{self.tenant_id}/KnowledgeBases"
        return self._request(
            "GET",
            path,
            headers=self._headers(),
            params={"page": page, "page_size": page_size},
        )

    def count_knowledge_bases(self, is_personal: int = 0, kds_id: str = COUNT_PATH_KDS_ID) -> int:
        path = f"/KnowledgeBase/Tenants/{self.tenant_id}/KnowledgeBases/{kds_id}/Count"
        data = self._request("POST", path, headers=self._headers(), json={"is_personal": is_personal})
        if not isinstance(data, dict):
            return 0
        return int(data.get("count") or 0)

    def get_knowledge_base(self, knowledge_base_id: str) -> dict[str, Any]:
        path = f"/KnowledgeBase/Tenants/{self.tenant_id}/KnowledgeBases/{knowledge_base_id}"
        return self._request("GET", path, headers=self._headers())

    def update_knowledge_base(self, knowledge_base_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        path = f"/KnowledgeBase/Tenants/{self.tenant_id}/KnowledgeBases/{knowledge_base_id}"
        return self._request("PATCH", path, headers=self._headers(), json=payload)

    def delete_knowledge_base(self, knowledge_base_id: str) -> dict[str, Any]:
        path = f"/KnowledgeBase/Tenants/{self.tenant_id}/KnowledgeBases/{knowledge_base_id}"
        return self._request("DELETE", path, headers=self._headers())

    def upload_documents(self, knowledge_base_id: str, files: list[tuple[str, bytes, str]]) -> dict[str, Any]:
        path = f"/KnowledgeBase/Tenants/{self.tenant_id}/KnowledgeBases/{knowledge_base_id}/KnowledgeFiles/Upload"
        multipart_files = [
            ("file", (filename, content, content_type or "application/octet-stream"))
            for filename, content, content_type in files
        ]
        return self._request("POST", path, headers=self._headers(content_type=None), files=multipart_files)

    def list_documents(self, knowledge_base_id: str, page: int, page_size: int) -> dict[str, Any]:
        path = f"/KnowledgeBase/Tenants/{self.tenant_id}/KnowledgeBases/{knowledge_base_id}/KnowledgeFiles"
        return self._request(
            "GET",
            path,
            headers=self._headers(),
            params={"page": page, "page_size": page_size},
        )

    def retrieve(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = f"/KnowledgeBase/Tenants/{self.tenant_id}/Retrieval/FusionSearch"
        return self._request("POST", path, headers=self._headers(), json=payload)
