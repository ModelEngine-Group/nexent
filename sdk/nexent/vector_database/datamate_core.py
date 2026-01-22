"""
DataMate adapter implementing the VectorDatabaseCore interface.

Not all operations are supported by the DataMate HTTP API. Unsupported methods
raise NotImplementedError to make limitations explicit.
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable, Tuple

from .base import VectorDatabaseCore
from ..datamate.datamate_client import DataMateClient
from ..core.models.embedding_model import BaseEmbedding

logger = logging.getLogger("datamate_core")


def _parse_timestamp(timestamp: Any, default: int = 0) -> int:
    """
    Parse timestamp from various formats to milliseconds since epoch.

    Args:
        timestamp: Timestamp value (int, str, or None)
        default: Default value if parsing fails

    Returns:
        Timestamp in milliseconds since epoch
    """
    if timestamp is None:
        return default

    if isinstance(timestamp, int):
        # If already an int, assume it's in milliseconds (or seconds if < 1e10)
        if timestamp < 1e10:
            return timestamp * 1000
        return timestamp

    if isinstance(timestamp, str):
        try:
            # Try ISO format
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            return int(dt.timestamp() * 1000)
        except Exception:
            try:
                # Try as integer string
                ts_int = int(timestamp)
                if ts_int < 1e10:
                    return ts_int * 1000
                return ts_int
            except Exception:
                return default

    return default


class DataMateCore(VectorDatabaseCore):
    """VectorDatabaseCore implementation backed by the DataMate REST API."""

    def __init__(self, base_url: str, timeout: float = 30.0, verify_ssl: bool = True):
        self.client = DataMateClient(
            base_url=base_url, timeout=timeout, verify_ssl=verify_ssl)

    # ---- INDEX MANAGEMENT ----
    def create_index(self, index_name: str, embedding_dim: Optional[int] = None) -> bool:
        """DataMate API does not support index creation via SDK."""
        _ = embedding_dim
        raise NotImplementedError("DataMate SDK does not support creating indices.")

    def delete_index(self, index_name: str) -> bool:
        """DataMate API does not support deleting indices via SDK."""
        raise NotImplementedError("DataMate SDK does not support deleting indices.")

    def get_user_indices(self, index_pattern: str = "*") -> List[str]:
        """Return DataMate knowledge base IDs as index identifiers."""
        _ = index_pattern
        knowledge_bases = self.client.list_knowledge_bases()
        return [str(kb.get("id")) for kb in knowledge_bases if kb.get("id") is not None and kb.get("type") == "DOCUMENT"]

    def check_index_exists(self, index_name: str) -> bool:
        """Check existence by knowledge base id."""
        return index_name in self.get_user_indices()

    # ---- DOCUMENT OPERATIONS ----
    def vectorize_documents(
            self,
            index_name: str,
            embedding_model: BaseEmbedding,
            documents: List[Dict[str, Any]],
            batch_size: int = 64,
            content_field: str = "content",
            embedding_batch_size: int = 10,
            progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> int:
        _ = (
            index_name,
            embedding_model,
            documents,
            batch_size,
            content_field,
            embedding_batch_size,
            progress_callback,
        )
        raise NotImplementedError("DataMate SDK does not support direct document ingestion.")

    def delete_documents(self, index_name: str, path_or_url: str) -> int:
        _ = (index_name, path_or_url)
        raise NotImplementedError("DataMate SDK does not support deleting documents.")

    def get_index_chunks(
            self,
            index_name: str,
            page: Optional[int] = None,
            page_size: Optional[int] = None,
            path_or_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        _ = (page, page_size, path_or_url)
        files = self.client.get_knowledge_base_files(index_name)
        return {
            "chunks": files,
            "total": len(files),
            "page": page,
            "page_size": page_size,
        }

    def create_chunk(self, index_name: str, chunk: Dict[str, Any]) -> Dict[str, Any]:
        _ = (index_name, chunk)
        raise NotImplementedError("DataMate SDK does not support creating individual chunks.")

    def update_chunk(self, index_name: str, chunk_id: str, chunk_updates: Dict[str, Any]) -> Dict[str, Any]:
        _ = (index_name, chunk_id, chunk_updates)
        raise NotImplementedError("DataMate SDK does not support updating chunks.")

    def delete_chunk(self, index_name: str, chunk_id: str) -> bool:
        _ = (index_name, chunk_id)
        raise NotImplementedError("DataMate SDK does not support deleting chunks.")

    def count_documents(self, index_name: str) -> int:
        files = self.client.get_knowledge_base_files(index_name)
        return len(files)

    # ---- SEARCH OPERATIONS ----
    def search(self, index_name: str, query: Dict[str, Any]) -> Dict[str, Any]:
        _ = (index_name, query)
        raise NotImplementedError("DataMate SDK does not support raw search API.")

    def multi_search(self, body: List[Dict[str, Any]], index_name: str) -> Dict[str, Any]:
        _ = (body, index_name)
        raise NotImplementedError("DataMate SDK does not support multi search API.")

    def accurate_search(self, index_names: List[str], query_text: str, top_k: int = 5) -> List[Dict[str, Any]]:
        _ = (index_names, query_text, top_k)
        raise NotImplementedError("DataMate SDK does not support accurate search API.")

    def semantic_search(
            self, index_names: List[str], query_text: str, embedding_model: BaseEmbedding, top_k: int = 5
    ) -> List[Dict[str, Any]]:
        _ = (index_names, query_text, embedding_model, top_k)
        raise NotImplementedError("DataMate SDK does not support semantic search API.")

    # ---- SEARCH OPERATIONS ----
    def hybrid_search(
            self,
            index_names: List[str],
            query_text: str,
            embedding_model: Optional[BaseEmbedding] = None,
            top_k: int = 10,
            weight_accurate: float = 0.2,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve content in DataMate knowledge bases.

        Args:
            index_names: List of knowledge base IDs to retrieve
            query_text: Retrieve query text
            embedding_model: Optional embedding model
            top_k: Maximum number of results to return (default: 10)
            weight_accurate: Similarity threshold (default: 0.2)

        Returns:
            List of retrieve result dictionaries

        Raises:
            RuntimeError: If the API request fails
        """
        _ = embedding_model  # Explicitly ignored
        retrieve_knowledge = self.client.retrieve_knowledge_base(query_text, index_names, top_k, weight_accurate)
        return retrieve_knowledge

    # ---- STATISTICS AND MONITORING ----
    def get_documents_detail(self, index_name: str) -> List[Dict[str, Any]]:
        files_list = self.client.get_knowledge_base_files(index_name)
        results = []
        for info in files_list:
            file_info = {
                "path_or_url": info.get("path_or_url", ""),
                "file": info.get("fileName", ""),
                "file_size": info.get("fileSize", ""),
                "create_time": _parse_timestamp(info.get("createdAt", "")),
                "chunk_count": info.get("chunkCount", ""),
                "status": "COMPLETED",
                "latest_task_id": "",
                "error_reason": info.get("errMsg", ""),
                "has_error_info": False,
                "processed_chunk_num": None,
                "total_chunk_num": None,
                "chunks": []
            }
            results.append(file_info)
        return results

    def get_indices_detail(self, index_names: List[str], embedding_dim: Optional[int] = None) -> Tuple[Dict[
        str, Dict[str, Any]], List[str]]:
        details: Dict[str, Dict[str, Any]] = {}
        knowledge_base_names = []
        for kb_id in index_names:
            try:
                # Get knowledge base info and files
                kb_info = self.client.get_knowledge_base_info(kb_id)

                # Extract data from knowledge base info
                doc_count = kb_info.get("fileCount")  # Number of unique documents (files)
                knowledge_base_name = kb_info.get("name")
                knowledge_base_names.append(knowledge_base_name)
                chunk_count = kb_info.get("chunkCount")
                store_size = kb_info.get("storeSize", "")
                process_source = kb_info.get("processSource", "Unstructured")
                embedding_model = kb_info.get("embedding").get("modelName")

                # Parse timestamps
                creation_date = _parse_timestamp(kb_info.get("createdAt"))
                update_date = _parse_timestamp(kb_info.get("updatedAt"))

                # Build base_info dict
                base_info = {
                    "doc_count": doc_count,
                    "chunk_count": chunk_count,
                    "store_size": str(store_size),
                    "process_source": str(process_source),
                    "embedding_model": str(embedding_model),
                    "embedding_dim": embedding_dim or 1024,
                    "creation_date": creation_date,
                    "update_date": update_date,
                }

                # Build performance dict (DataMate API may not provide search stats)
                performance = {"total_search_count": 0, "hit_count": 0}

                details[kb_id] = {"base_info": base_info, "search_performance": performance}
            except Exception as exc:
                logger.error(f"Error getting stats for knowledge base {kb_id}: {str(exc)}")
                details[kb_id] = {"error": str(exc)}
        return details, knowledge_base_names
