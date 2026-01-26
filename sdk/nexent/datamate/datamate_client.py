"""
DataMate API client for datamate knowledge base operations.

This SDK provides a unified interface for interacting with DataMate knowledge base APIs,
including listing knowledge bases, retrieving files, and retrieving content.
"""
import logging
from typing import Dict, List, Optional, Any
import httpx

logger = logging.getLogger("datamate_client")


class DataMateClient:
    """
    Client for interacting with DataMate knowledge base APIs.

    This client encapsulates all DataMate API calls and provides a clean interface
    for datamate knowledge base operations.
    """

    def __init__(self, base_url: str, timeout: float = 30.0, verify_ssl: bool = True):
        """
        Initialize DataMate client.

        Args:
            base_url: Base URL of DataMate server (e.g., "http://jasonwang.site:30000")
            timeout: Request timeout in seconds (default: 30.0)
            verify_ssl: Whether to verify SSL certificates (default: True)
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        logger.info(f"Initialized DataMateClient with base_url: {self.base_url}, verify_ssl: {self.verify_ssl}")

    def _build_url(self, path: str) -> str:
        """Build full URL from path."""
        if path.startswith("/"):
            return f"{self.base_url}{path}"
        return f"{self.base_url}/{path}"

    def _build_headers(self, authorization: Optional[str] = None) -> Dict[str, str]:
        """
        Build request headers with optional authorization.

        Args:
            authorization: Optional authorization header value

        Returns:
            Dictionary of headers
        """
        headers = {}
        if authorization:
            headers["Authorization"] = authorization
        return headers

    def _handle_error_response(self, response: httpx.Response, error_message: str) -> None:
        """
        Handle error response and raise appropriate exception.

        Args:
            response: HTTP response object
            error_message: Base error message to include in exception (e.g., "Failed to get knowledge base list")

        Raises:
            Exception: With detailed error message
        """
        error_detail = (
            response.json().get("detail", "unknown error")
            if response.headers.get("content-type", "").startswith("application/json")
            else response.text
        )
        raise Exception(f"{error_message} (status {response.status_code}): {error_detail}")

    def _make_request(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        json: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        error_message: str = "Request failed"
    ) -> httpx.Response:
        """
        Make HTTP request with error handling.

        Args:
            method: HTTP method ("GET" or "POST")
            url: Request URL
            headers: Request headers
            json: Optional JSON payload for POST requests
            timeout: Optional timeout override
            error_message: Error message to use if request fails

        Returns:
            HTTP response object

        Raises:
            Exception: If the request fails (with detailed error message)
        """
        request_timeout = timeout if timeout is not None else self.timeout

        with httpx.Client(timeout=request_timeout, verify=self.verify_ssl) as client:
            if method.upper() == "GET":
                response = client.get(url, headers=headers)
            elif method.upper() == "POST":
                response = client.post(url, json=json, headers=headers)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            if response.status_code != 200:
                self._handle_error_response(response, error_message)

            return response

    def list_knowledge_bases(
        self,
        page: int = 0,
        size: int = 20,
        authorization: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get list of knowledge bases from DataMate.

        Args:
            page: Page index (default: 0)
            size: Page size (default: 20)
            authorization: Optional authorization header

        Returns:
            List of knowledge base dictionaries with their IDs and metadata.

        Raises:
            RuntimeError: If the API request fails
        """
        try:
            url = self._build_url("/api/knowledge-base/list")
            payload = {"page": page, "size": size}
            headers = self._build_headers(authorization)

            logger.info(f"Fetching DataMate knowledge bases from: {url}, page={page}, size={size}")

            response = self._make_request("POST", url, headers, json=payload, error_message="Failed to get knowledge base list")
            data = response.json()

            # Extract knowledge base list from response
            knowledge_bases = []
            if data.get("data"):
                knowledge_bases = data.get("data").get("content", [])

            logger.info(f"Successfully fetched {len(knowledge_bases)} knowledge bases from DataMate")
            return knowledge_bases

        except httpx.HTTPError as e:
            logger.error(f"HTTP error while fetching DataMate knowledge bases: {str(e)}")
            raise RuntimeError(f"Failed to fetch DataMate knowledge bases: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error while fetching DataMate knowledge bases: {str(e)}")
            raise RuntimeError(f"Failed to fetch DataMate knowledge bases: {str(e)}")

    def get_knowledge_base_files(
        self,
        knowledge_base_id: str,
        authorization: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get file list for a specific DataMate knowledge base.

        Args:
            knowledge_base_id: The ID of the knowledge base
            authorization: Optional authorization header

        Returns:
            List of file dictionaries with name, status, size, upload_date, etc.

        Raises:
            RuntimeError: If the API request fails
        """
        try:
            url = self._build_url(
                f"/api/knowledge-base/{knowledge_base_id}/files")
            logger.info(
                f"Fetching files for DataMate knowledge base {knowledge_base_id} from: {url}")

            headers = self._build_headers(authorization)
            response = self._make_request(
                "GET", url, headers, error_message="Failed to get knowledge base files")
            data = response.json()

            # Extract file list from response
            files = []
            if data.get("data"):
                files = data.get("data").get("content", [])

            logger.info(
                f"Successfully fetched {len(files)} files for datamate knowledge base {knowledge_base_id}")
            return files

        except httpx.HTTPError as e:
            logger.error(
                f"HTTP error while fetching files for datamate knowledge base {knowledge_base_id}: {str(e)}")
            raise RuntimeError(
                f"Failed to fetch files for datamate knowledge base {knowledge_base_id}: {str(e)}")
        except Exception as e:
            logger.error(
                f"Unexpected error while fetching files for datamate knowledge base {knowledge_base_id}: {str(e)}")
            raise RuntimeError(
                f"Failed to fetch files for datamate knowledge base {knowledge_base_id}: {str(e)}")

    def get_knowledge_base_info(
        self,
        knowledge_base_id: str,
        authorization: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get details for a specific DataMate knowledge base.

        Args:
            knowledge_base_id: The ID of the knowledge base
            authorization: Optional authorization header

        Returns:
            Dictionary containing knowledge base details.

        Raises:
            RuntimeError: If the API request fails
        """
        try:
            url = self._build_url(f"/api/knowledge-base/{knowledge_base_id}")
            logger.info(
                f"Fetching details for DataMate knowledge base {knowledge_base_id} from: {url}")

            headers = self._build_headers(authorization)
            response = self._make_request(
                "GET", url, headers, error_message="Failed to get knowledge base details")
            data = response.json()

            # Extract knowledge base details from response
            knowledge_base = data.get("data", {})

            logger.info(
                f"Successfully fetched details for datamate knowledge base {knowledge_base_id}")
            return knowledge_base

        except httpx.HTTPError as e:
            logger.error(
                f"HTTP error while fetching details for datamate knowledge base {knowledge_base_id}: {str(e)}")
            raise RuntimeError(
                f"Failed to fetch details for datamate knowledge base {knowledge_base_id}: {str(e)}")
        except Exception as e:
            logger.error(
                f"Unexpected error while fetching details for datamate knowledge base {knowledge_base_id}: {str(e)}")
            raise RuntimeError(
                f"Failed to fetch details for datamate knowledge base {knowledge_base_id}: {str(e)}")

    def retrieve_knowledge_base(
        self,
        query: str,
        knowledge_base_ids: List[str],
        top_k: int = 10,
        threshold: float = 0.2,
        authorization: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieve content in DataMate knowledge bases.

        Args:
            query: Retrieve query text
            knowledge_base_ids: List of knowledge base IDs to retrieve
            top_k: Maximum number of results to return (default: 10)
            threshold: Similarity threshold (default: 0.2)
            authorization: Optional authorization header

        Returns:
            List of retrieve result dictionaries

        Raises:
            RuntimeError: If the API request fails
        """
        try:
            url = self._build_url("/api/knowledge-base/retrieve")
            payload = {
                "query": query,
                "topK": top_k,
                "threshold": threshold,
                "knowledgeBaseIds": knowledge_base_ids,
            }

            headers = self._build_headers(authorization)

            logger.info(
                f"Retrieving DataMate knowledge bases: query='{query}', "
                f"knowledge_base_ids={knowledge_base_ids}, top_k={top_k}, threshold={threshold}"
            )

            # Longer timeout for retrieve operation
            response = self._make_request(
                "POST", url, headers, json=payload, timeout=self.timeout * 2,
                error_message="Failed to retrieve knowledge base content"
            )

            search_results = []
            data = response.json()
            # Extract search results from response
            for result in data.get("data", {}):
                search_results.append(result)

            logger.info(
                f"Successfully retrieved {len(search_results)} retrieve result(s)")
            return search_results

        except httpx.HTTPError as e:
            logger.error(
                f"HTTP error while retrieving DataMate knowledge bases: {str(e)}")
            raise RuntimeError(
                f"Failed to retrieve DataMate knowledge bases: {str(e)}")
        except Exception as e:
            logger.error(
                f"Unexpected error while retrieving DataMate knowledge bases: {str(e)}")
            raise RuntimeError(
                f"Failed to retrieve DataMate knowledge bases: {str(e)}")

    def build_file_download_url(self, dataset_id: str, file_id: str) -> str:
        """
        Build download URL for a DataMate file.

        Args:
            dataset_id: Dataset ID
            file_id: File ID

        Returns:
            Full download URL for the file
        """
        if not (dataset_id and file_id):
            return ""
        return f"{self.base_url}/api/data-management/datasets/{dataset_id}/files/{file_id}/download"

    def sync_all_knowledge_bases(
        self,
        authorization: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Sync all DataMate knowledge bases and their files.

        Args:
            authorization: Optional authorization header

        Returns:
            Dictionary containing knowledge bases with their file lists.
            Format: {
                "success": bool,
                "knowledge_bases": [
                    {
                        "knowledge_base": {...},
                        "files": [...],
                        "error": str (optional)
                    }
                ],
                "total_count": int
            }
        """
        try:
            # Fetch all knowledge bases
            knowledge_bases = self.list_knowledge_bases(
                authorization=authorization)

            # Fetch files for each knowledge base
            result = []
            for kb in knowledge_bases:
                kb_id = kb.get("id")

                try:
                    files = self.get_knowledge_base_files(
                        str(kb_id), authorization=authorization)
                    result.append({
                        "knowledge_base": kb,
                        "files": files,
                    })
                except Exception as e:
                    logger.error(
                        f"Failed to fetch files for datamate knowledge base {kb_id}: {str(e)}")
                    # Continue with other knowledge bases even if one fails
                    result.append({
                        "knowledge_base": kb,
                        "files": [],
                        "error": str(e),
                    })

            return {
                "success": True,
                "knowledge_bases": result,
                "total_count": len(result),
            }

        except Exception as e:
            logger.error(f"Error syncing DataMate knowledge bases: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "knowledge_bases": [],
                "total_count": 0,
            }
