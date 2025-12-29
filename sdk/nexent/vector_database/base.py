from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Callable

from ..core.models.embedding_model import BaseEmbedding


class VectorDatabaseCore(ABC):
    """
    Abstract base class for vector database operations.

    All vector database implementations must inherit from this class and implement
    all abstract methods. This abstraction enables support for multiple vector
    database backends (e.g., Elasticsearch, Milvus) while maintaining a consistent
    interface for the service layer.
    """

    # ---- INDEX MANAGEMENT ----

    @abstractmethod
    def create_index(self, index_name: str, embedding_dim: Optional[int] = None) -> bool:
        """
        Create a new vector search index with appropriate mappings.

        Args:
            index_name: Name of the index to create
            embedding_dim: Dimension of the embedding vectors (optional, will use model's dim if not provided)

        Returns:
            bool: True if creation was successful
        """
        pass

    @abstractmethod
    def delete_index(self, index_name: str) -> bool:
        """
        Delete an entire index.

        Args:
            index_name: Name of the index to delete

        Returns:
            bool: True if deletion was successful
        """
        pass

    @abstractmethod
    def get_user_indices(self, index_pattern: str = "*") -> List[str]:
        """
        Get list of user created indices (excluding system indices).

        Args:
            index_pattern: Pattern to match index names

        Returns:
            List of index names
        """
        pass

    @abstractmethod
    def check_index_exists(self, index_name: str) -> bool:
        """
        Check if an index exists.

        Args:
            index_name: Name of the index to check

        Returns:
            bool: True if index exists, False otherwise
        """
        pass

    # ---- DOCUMENT OPERATIONS ----

    @abstractmethod
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
        """
        Index documents with embeddings.

        Args:
            index_name: Name of the index to add documents to
            embedding_model: Model used to generate embeddings for documents
            documents: List of document dictionaries
            batch_size: Number of documents to process at once
            content_field: Field to use for generating embeddings

        Returns:
            int: Number of documents successfully indexed
        """
        pass

    @abstractmethod
    def delete_documents(self, index_name: str, path_or_url: str) -> int:
        """
        Delete documents based on their path_or_url field.

        Args:
            index_name: Name of the index to delete documents from
            path_or_url: The URL or path of the documents to delete

        Returns:
            int: Number of documents deleted
        """
        pass

    @abstractmethod
    def get_index_chunks(
        self,
        index_name: str,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
        path_or_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Retrieve chunk records for the specified index with optional pagination.

        Args:
            index_name: Name of the index to query
            page: Page number to return (1-based). If None, all chunks are returned.
            page_size: Page size for pagination. Must be provided together with page.
            path_or_url: Optional filter for a specific document path or URL.

        Returns:
            Dict containing chunks, total count, and pagination metadata
        """
        pass

    @abstractmethod
    def create_chunk(self, index_name: str, chunk: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a single chunk document inside the specified index.

        Args:
            index_name: Target index name.
            chunk: Chunk payload to persist.

        Returns:
            Dict containing the created chunk metadata (including id/result).
        """
        pass

    @abstractmethod
    def update_chunk(self, index_name: str, chunk_id: str, chunk_updates: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update an existing chunk document.

        Args:
            index_name: Target index name.
            chunk_id: Identifier of the chunk (ES _id or custom id field).
            chunk_updates: Fields to update.

        Returns:
            Dict containing update status information.
        """
        pass

    @abstractmethod
    def delete_chunk(self, index_name: str, chunk_id: str) -> bool:
        """
        Delete a chunk document from the specified index.

        Args:
            index_name: Target index name.
            chunk_id: Identifier of the chunk (ES _id or custom id field).

        Returns:
            bool indicating whether a document was deleted.
        """
        pass

    @abstractmethod
    def count_documents(self, index_name: str) -> int:
        """
        Count the total number of documents in an index.

        Args:
            index_name: Name of the index to count documents in

        Returns:
            int: Total number of documents
        """
        pass

    @abstractmethod
    def search(self, index_name: str, query: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a search query on an index.

        Args:
            index_name: Name of the index to search
            query: Search query dictionary

        Returns:
            Dict containing search results
        """
        pass

    @abstractmethod
    def multi_search(self, body: List[Dict[str, Any]], index_name: str) -> Dict[str, Any]:
        """
        Execute multiple search queries in a single request.

        Args:
            body: List of search queries (alternating index and query)
            index_name: Name of the index to search

        Returns:
            Dict containing responses for all queries
        """
        pass

    # ---- SEARCH OPERATIONS ----

    @abstractmethod
    def accurate_search(self, index_names: List[str], query_text: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Search for documents using fuzzy text matching across multiple indices.

        Args:
            index_names: List of index names to search in
            query_text: The text query to search for
            top_k: Number of results to return

        Returns:
            List of search results with scores and document content
        """
        pass

    @abstractmethod
    def semantic_search(
        self, index_names: List[str], query_text: str, embedding_model: BaseEmbedding, top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Search for similar documents using vector similarity across multiple indices.

        Args:
            index_names: List of index names to search in
            query_text: The text query to search for
            embedding_model: The embedding model to use
            top_k: Number of results to return

        Returns:
            List of search results with scores and document content
        """
        pass

    @abstractmethod
    def hybrid_search(
        self,
        index_names: List[str],
        query_text: str,
        embedding_model: BaseEmbedding,
        top_k: int = 5,
        weight_accurate: float = 0.3,
    ) -> List[Dict[str, Any]]:
        """
        Hybrid search method, combining accurate matching and semantic search results across multiple indices.

        Args:
            index_names: List of index names to search in
            query_text: The text query to search for
            embedding_model: The embedding model to use
            top_k: Number of results to return
            weight_accurate: The weight of the accurate matching score (0-1),
                           the semantic search weight is 1-weight_accurate

        Returns:
            List of search results sorted by combined score
        """
        pass

    # ---- STATISTICS AND MONITORING ----

    @abstractmethod
    def get_documents_detail(self, index_name: str) -> List[Dict[str, Any]]:
        """
        Get a list of unique source files with metadata.

        Args:
            index_name: Name of the index to query

        Returns:
            List of dictionaries, each containing:
                - path_or_url: Source identifier
                - filename: Optional display name
                - file_size: Size in bytes
                - create_time: ISO timestamp string
        """
        pass

    @abstractmethod
    def get_indices_detail(
        self, index_names: List[str], embedding_dim: Optional[int] = None
    ) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """
        Get formatted statistics for multiple indices.

        Args:
            index_names: List of index names to get stats for
            embedding_dim: Optional embedding dimension (for display purposes)

        Returns:
            Dict mapping each index name to:
                - base_info: Dict with doc_count, chunk_count, store_size,
                  process_source, embedding_model, embedding_dim,
                  creation_date, update_date
                - search_performance: Dict with total_search_count, hit_count
        """
        pass
