import time
import logging
import threading
from typing import List, Dict, Any, Optional
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from ..core.models.embedding_model import BaseEmbedding
from .utils import format_size, format_timestamp, build_weighted_query
from elasticsearch import Elasticsearch, exceptions

from ..core.nlp.tokenizer import calculate_term_weights

logger = logging.getLogger("elasticsearch_core")

@dataclass
class BulkOperation:
    """Bulk operation status tracking"""
    index_name: str
    operation_id: str
    start_time: datetime
    expected_duration: timedelta

class ElasticSearchCore:
    """
    Core class for Elasticsearch operations including:
    - Index management
    - Document insertion with embeddings
    - Document deletion
    - Accurate text search
    - Semantic vector search
    - Hybrid search
    - Index statistics
    """
    
    def __init__(
        self, 
        host: Optional[str],
        api_key: Optional[str],
        verify_certs: bool = False,
        ssl_show_warn: bool = False,
    ):
        """
        Initialize ElasticSearchCore with Elasticsearch client and JinaEmbedding model.
        
        Args:
            host: Elasticsearch host URL (defaults to env variable)
            api_key: Elasticsearch API key (defaults to env variable)
            verify_certs: Whether to verify SSL certificates
            ssl_show_warn: Whether to show SSL warnings
        """
        # Get credentials from environment if not provided
        self.host = host
        self.api_key = api_key
        
        # Initialize Elasticsearch client with HTTPS support
        self.client = Elasticsearch(
            self.host,
            api_key=self.api_key,
            verify_certs=verify_certs,
            ssl_show_warn=ssl_show_warn,
            request_timeout=20,
            max_retries=3,  # Reduce retries for faster failure detection
            retry_on_timeout=True,
            retry_on_status=[502, 503, 504],  # Retry on these status codes,
        )
        
        # Initialize embedding model
        self._bulk_operations: Dict[str, List[BulkOperation]] = {}
        self._settings_lock = threading.Lock()
        self._operation_counter = 0

        # Embedding API limits
        self.max_texts_per_batch = 2048
        self.max_tokens_per_text = 8192
        self.max_total_tokens = 100000
    
    # ---- INDEX MANAGEMENT ----
    
    def create_vector_index(self, index_name: str, embedding_dim: Optional[int] = None) -> bool:
        """
        Create a new vector search index with appropriate mappings in a celery-friendly way.
        
        Args:
            index_name: Name of the index to create
            embedding_dim: Dimension of the embedding vectors (optional, will use model's dim if not provided)
            
        Returns:
            bool: True if creation was successful
        """
        try:
            # Use provided embedding_dim or get from model
            actual_embedding_dim = embedding_dim or 1024
            
            # Use balanced fixed settings to avoid dynamic adjustment
            settings = {
                "number_of_shards": 1,
                "number_of_replicas": 0,
                "refresh_interval": "5s",  # not too fast, not too slow
                "index": {
                    "max_result_window": 50000,
                    "translog": {
                        "durability": "async",
                        "sync_interval": "5s"
                    },
                    "write": {
                        "wait_for_active_shards": "1"
                    },
                    # Memory optimization for bulk operations
                    "merge": {
                        "policy": {
                            "max_merge_at_once": 5,
                            "segments_per_tier": 5
                        }
                    }
                }
            }

            # Check if index already exists
            if self.client.indices.exists(index=index_name):
                logger.info(f"Index {index_name} already exists, skipping creation")
                self._ensure_index_ready(index_name)
                return True
                
            # Define the mapping with vector field
            mappings = {
                "properties": {
                    "id": {"type": "keyword"},
                    "title": {"type": "text"},
                    "filename": {"type": "keyword"},
                    "path_or_url": {"type": "keyword"},
                    "language": {"type": "keyword"},
                    "author": {"type": "keyword"},
                    "date": {"type": "date"},
                    "content": {"type": "text"},
                    "process_source": {"type": "keyword"},
                    "embedding_model_name": {"type": "keyword"},
                    "file_size": {"type": "long"},
                    "create_time": {"type": "date"},
                    "embedding": {
                        "type": "dense_vector",
                        "dims": actual_embedding_dim,
                        "index": "true",
                        "similarity": "cosine",
                    },
                }
            }
            
            # Create the index with the defined mappings
            self.client.indices.create(
                index=index_name,
                mappings=mappings,
                settings=settings,
                wait_for_active_shards="1"
            )

            # Force refresh to ensure visibility
            self._force_refresh_with_retry(index_name)
            self._ensure_index_ready(index_name)

            logger.info(f"Successfully created index: {index_name}")
            return True
            
        except exceptions.RequestError as e:
            # Handle the case where index already exists (error 400)
            if "resource_already_exists_exception" in str(e):
                logger.info(f"Index {index_name} already exists, skipping creation")
                self._ensure_index_ready(index_name)
                return True
            logger.error(f"Error creating index: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Error creating index: {str(e)}")
            return False

    def _force_refresh_with_retry(self, index_name: str, max_retries: int = 3) -> bool:
        """
        Force refresh with retry - synchronous version
        """
        for attempt in range(max_retries):
            try:
                self.client.indices.refresh(index=index_name)
                return True
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                logger.error(f"Failed to refresh index {index_name}: {e}")
                return False
        return False

    def _ensure_index_ready(self, index_name: str, timeout: int = 10) -> bool:
        """
        Ensure index is ready, avoid 503 error - synchronous version
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                # Check cluster health
                health = self.client.cluster.health(
                    index=index_name,
                    wait_for_status="yellow",
                    timeout="1s"
                )

                if health["status"] in ["green", "yellow"]:
                    # Double check: try simple query
                    self.client.search(
                        index=index_name,
                        body={"query": {"match_all": {}}, "size": 0}
                    )
                    return True

            except Exception as e:
                time.sleep(0.1)

        logger.warning(f"Index {index_name} may not be fully ready after {timeout}s")
        return False

    @contextmanager
    def bulk_operation_context(self, index_name: str, estimated_duration: int = 60):
        """
        Celery-friendly context manager - using threading.Lock
        """
        operation_id = f"bulk_{self._operation_counter}_{threading.current_thread().name}"
        self._operation_counter += 1

        operation = BulkOperation(
            index_name=index_name,
            operation_id=operation_id,
            start_time=datetime.now(),
            expected_duration=timedelta(seconds=estimated_duration)
        )

        with self._settings_lock:
            # Record current operation
            if index_name not in self._bulk_operations:
                self._bulk_operations[index_name] = []
            self._bulk_operations[index_name].append(operation)

            # If this is the first bulk operation, adjust settings
            if len(self._bulk_operations[index_name]) == 1:
                self._apply_bulk_settings(index_name)

        try:
            yield operation_id
        finally:
            with self._settings_lock:
                # Remove operation record
                self._bulk_operations[index_name] = [
                    op for op in self._bulk_operations[index_name]
                    if op.operation_id != operation_id
                ]

                # If there are no other bulk operations, restore settings
                if not self._bulk_operations[index_name]:
                    self._restore_normal_settings(index_name)
                    del self._bulk_operations[index_name]

    def _apply_bulk_settings(self, index_name: str):
        """Apply bulk operation optimization settings"""
        try:
            self.client.indices.put_settings(
                index=index_name,
                body={
                    "refresh_interval": "30s",
                    "translog.durability": "async",
                    "translog.sync_interval": "10s"
                }
            )
            logger.info(f"Applied bulk settings to {index_name}")
        except Exception as e:
            logger.warning(f"Failed to apply bulk settings: {e}")

    def _restore_normal_settings(self, index_name: str):
        """Restore normal settings"""
        try:
            self.client.indices.put_settings(
                index=index_name,
                body={
                    "refresh_interval": "5s",
                    "translog.durability": "request"
                }
            )
            # Refresh after restoration
            self._force_refresh_with_retry(index_name)
            logger.info(f"Restored normal settings for {index_name}")
        except Exception as e:
            logger.warning(f"Failed to restore settings: {e}")

    def delete_index(self, index_name: str) -> bool:
        """
        Delete an entire index
        
        Args:
            index_name: Name of the index to delete
            
        Returns:
            bool: True if deletion was successful
        """
        try:
            self.client.indices.delete(index=index_name)
            logger.info(f"Successfully deleted the index: {index_name}")
            return True
        except exceptions.NotFoundError:
            logger.info(f"Index {index_name} not found")
            return False
        except Exception as e:
            logger.error(f"Error deleting index: {str(e)}")
            return False
    
    def get_user_indices(self, index_pattern: str = "*") -> List[str]:
        """
        Get list of user created indices (excluding system indices)
        
        Args:
            index_pattern: Pattern to match index names
            
        Returns:
            List of index names
        """
        try:
            indices = self.client.indices.get_alias(index=index_pattern)
            # Filter out system indices (starting with '.')
            return [index_name for index_name in indices.keys() if not index_name.startswith('.')]
        except Exception as e:
            logger.error(f"Error getting user indices: {str(e)}")
            return []
    
    # ---- DOCUMENT OPERATIONS ----
    
    def index_documents(
        self, 
        index_name: str,
        embedding_model: BaseEmbedding,
        documents: List[Dict[str, Any]], 
        batch_size: int = 2048,
        content_field: str = "content"
    ) -> int:
        """
        Smart batch insertion - automatically selecting strategy based on data size
        
        Args:
            index_name: Name of the index to add documents to
            embedding_model: Model used to generate embeddings for documents
            documents: List of document dictionaries
            batch_size: Number of documents to process at once
            content_field: Field to use for generating embeddings
            
        Returns:
            int: Number of documents successfully indexed
        """
        logger.info(f"Indexing {len(documents)} chunks to {index_name}")

        # Handle empty documents list
        if not documents:
            return 0

        # Smart strategy selection
        total_docs = len(documents)
        if total_docs < 100:
            # Small data: direct insertion, using wait_for refresh
            return self._small_batch_insert(index_name, documents, content_field, embedding_model)
        else:
            # Large data: using context manager
            estimated_duration = max(60, total_docs // 100)
            with self.bulk_operation_context(index_name, estimated_duration):
                return self._large_batch_insert(index_name, documents, batch_size, content_field, embedding_model)

    def _small_batch_insert(self, index_name: str, documents: List[Dict[str, Any]], content_field: str, embedding_model:BaseEmbedding) -> int:
        """Small batch insertion: real-time"""
        try:
            # Preprocess documents
            processed_docs = self._preprocess_documents(documents, content_field)
            
            # Get embeddings
            inputs = [doc[content_field] for doc in processed_docs]
            embeddings = embedding_model.get_embeddings(inputs)

            # Prepare bulk operations
            operations = []
            for doc, embedding in zip(processed_docs, embeddings):
                operations.append({"index": {"_index": index_name}})
                doc["embedding"] = embedding
                if "embedding_model_name" not in doc:
                    doc["embedding_model_name"] = embedding_model.embedding_model_name
                operations.append(doc)

            # Execute bulk insertion, wait for refresh to complete
            response = self.client.bulk(
                index=index_name,
                operations=operations,
                refresh='wait_for'
            )

            # Handle errors
            self._handle_bulk_errors(response)

            logger.info(f"Small batch insert completed: {len(documents)} chunks indexed.")
            return len(documents)
            
        except Exception as e:
            logger.error(f"Small batch insert failed: {e}")
            return 0

    def _large_batch_insert(self, index_name: str, documents: List[Dict[str, Any]], batch_size: int, content_field: str, embedding_model: BaseEmbedding) -> int:
        """
        Large batch insertion with sub-batching for embedding API.
        Splits large document batches into smaller chunks to respect embedding API limits before bulk inserting into Elasticsearch.
        """
        try:
            processed_docs = self._preprocess_documents(documents, content_field)
            total_indexed = 0
            total_docs = len(processed_docs)
            es_total_batches = (total_docs + batch_size - 1) // batch_size

            for i in range(0, total_docs, batch_size):
                es_batch = processed_docs[i:i + batch_size]
                es_batch_num = i // batch_size + 1

                # Store documents and their embeddings for this Elasticsearch batch
                doc_embedding_pairs = []

                # Sub-batch for embedding API
                embedding_batch_size = self.max_texts_per_batch
                for j in range(0, len(es_batch), embedding_batch_size):
                    embedding_sub_batch = es_batch[j:j + embedding_batch_size]
                    
                    try:
                        inputs = [doc[content_field] for doc in embedding_sub_batch]
                        embeddings = embedding_model.get_embeddings(inputs)
                        
                        for doc, embedding in zip(embedding_sub_batch, embeddings):
                            doc_embedding_pairs.append((doc, embedding))

                    except Exception as e:
                        logger.error(f"Embedding API error: {e}, ES batch num: {es_batch_num}, sub-batch start: {j}, size: {len(embedding_sub_batch)}")
                        continue
                
                # Perform a single bulk insert for the entire Elasticsearch batch
                if not doc_embedding_pairs:
                    logger.warning(f"No documents with embeddings to index for ES batch {es_batch_num}")
                    continue

                operations = []
                for doc, embedding in doc_embedding_pairs:
                    operations.append({"index": {"_index": index_name}})
                    doc["embedding"] = embedding
                    if "embedding_model_name" not in doc:
                        doc["embedding_model_name"] = getattr(embedding_model, 'embedding_model_name', 'unknown')
                    operations.append(doc)

                try:
                    response = self.client.bulk(
                        index=index_name,
                        operations=operations,
                        refresh=False
                    )
                    self._handle_bulk_errors(response)
                    total_indexed += len(doc_embedding_pairs)
                    logger.info(f"Processed ES batch {es_batch_num}/{es_total_batches}, indexed {len(doc_embedding_pairs)} documents.")

                except Exception as e:
                    logger.error(f"Bulk insert error: {e}, ES batch num: {es_batch_num}")
                    continue
                
                if es_batch_num % 10 == 0:
                    time.sleep(0.1)

            self._force_refresh_with_retry(index_name)
            logger.info(f"Large batch insert completed: {total_indexed} chunks indexed.")
            return total_indexed
        except Exception as e:
            logger.error(f"Large batch insert failed: {e}")
            return 0

    def _preprocess_documents(self, documents: List[Dict[str, Any]], content_field: str) -> List[Dict[str, Any]]:
        """Ensure all documents have the required fields and set default values"""
        current_time = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        current_date = time.strftime('%Y-%m-%d', time.gmtime())

        processed_docs = []
        for doc in documents:
            # Create a copy of the document to avoid modifying the original data
            doc_copy = doc.copy()

            # Set create_time if not present
            if not doc_copy.get("create_time"):
                doc_copy["create_time"] = current_time

            if not doc_copy.get("date"):
                doc_copy["date"] = current_date

            # Ensure file_size is present (default to 0 if not provided)
            if not doc_copy.get("file_size"):
                logger.warning(f"File size not found in {doc_copy}")
                doc_copy["file_size"] = 0

            # Ensure process_source is present
            if not doc_copy.get("process_source"):
                doc_copy["process_source"] = "Unstructured"

            # Ensure all documents have an ID
            if not doc_copy.get("id"):
                doc_copy["id"] = f"{int(time.time())}_{hash(doc_copy[content_field])}"[:20]

            processed_docs.append(doc_copy)

        return processed_docs

    def _handle_bulk_errors(self, response: Dict[str, Any]) -> None:
        """Handle bulk operation errors"""
        if response.get('errors'):
            for item in response['items']:
                if 'error' in item.get('index', {}):
                    error_info = item['index']['error']
                    error_type = error_info.get('type')
                    error_reason = error_info.get('reason')
                    error_cause = error_info.get('caused_by', {})

                    if error_type == 'version_conflict_engine_exception':
                        # ignore version conflict
                        continue
                    else:
                        logger.error(f"FATAL ERROR {error_type}: {error_reason}")
                        if error_cause:
                            logger.error(f"Caused By: {error_cause.get('type')}: {error_cause.get('reason')}")
    
    def delete_documents_by_path_or_url(self, index_name: str, path_or_url: str) -> int:
        """
        Delete documents based on their path_or_url field
        
        Args:
            index_name: Name of the index to delete documents from
            path_or_url: The URL or path of the documents to delete
            
        Returns:
            int: Number of documents deleted
        """
        try:
            result = self.client.delete_by_query(
                index=index_name,
                body={
                    "query": {
                        "term": {
                            "path_or_url": path_or_url
                        }
                    }
                }
            )
            logger.info(f"Successfully deleted {result['deleted']} documents with path_or_url: {path_or_url} from index: {index_name}")
            return result['deleted']
        except Exception as e:
            logger.error(f"Error deleting documents: {str(e)}")
            return 0
    
    # ---- SEARCH OPERATIONS ----
    
    def accurate_search(self, index_names: List[str], query_text: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Search for documents using fuzzy text matching across multiple indices.

        Args:
            index_names: Name of the index to search in
            query_text: The text query to search for
            top_k: Number of results to return
            
        Returns:
            List of search results with scores and document content
        """
        # Join index names for multi-index search
        index_pattern = ",".join(index_names)

        weights = calculate_term_weights(query_text)

        # Prepare the search query using match query for fuzzy matching
        search_query = build_weighted_query(query_text, weights) | {
            "size": top_k,
            "_source": {
                "excludes": ["embedding"]
            }
        }

        # Execute the search across multiple indices
        return self.exec_query(index_pattern, search_query)

    def exec_query(self, index_pattern, search_query):
        response = self.client.search(
            index=index_pattern,
            body=search_query
        )
        # Process and return results
        results = []
        for hit in response["hits"]["hits"]:
            results.append({
                "score": hit["_score"],
                "document": hit["_source"],
                "index": hit["_index"]  # Include source index in results
            })
        return results

    def semantic_search(self, index_names: List[str], query_text: str, embedding_model: BaseEmbedding, top_k: int = 5) -> List[Dict[str, Any]]:
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
        # Join index names for multi-index search
        index_pattern = ",".join(index_names)

        # Get query embedding
        query_embedding = embedding_model.get_embeddings(query_text)[0]
        
        # Prepare the search query
        search_query = {
            "knn": {
                "field": "embedding",
                "query_vector": query_embedding,
                "k": top_k,
                "num_candidates": top_k * 2,
            },
            "size": top_k,
            "_source": {
                "excludes": ["embedding"]
            }
        }
        
        # Execute the search across multiple indices
        return self.exec_query(index_pattern, search_query)

    def hybrid_search(
        self,
        index_names: List[str],
        query_text: str,
        embedding_model: BaseEmbedding,
        top_k: int = 5,
        weight_accurate: float = 0.3
    ) -> List[Dict[str, Any]]:
        """
        Hybrid search method, combining accurate matching and semantic search results across multiple indices.
        
        Args:
            index_names: List of index names to search in
            query_text: The text query to search for
            embedding_model: The embedding model to use
            top_k: Number of results to return
            weight_accurate: The weight of the accurate matching score (0-1), the semantic search weight is 1-weight_accurate

        Returns:
            List of search results sorted by combined score
        """
        # Get results from both searches
        accurate_results = self.accurate_search(index_names, query_text, top_k=top_k)
        semantic_results = self.semantic_search(index_names, query_text, embedding_model=embedding_model, top_k=top_k)

        # Create a mapping from document ID to results
        combined_results = {}

        # Process accurate matching results
        for result in accurate_results:
            try:
                doc_id = result['document']['id']
                combined_results[doc_id] = {
                    'document': result['document'],
                    'accurate_score': result.get('score', 0),
                    'semantic_score': 0,
                    'index': result['index']  # Keep track of source index
                }
            except KeyError as e:
                logger.warning(f"Warning: Missing required field in accurate result: {e}")
                continue

        # Process semantic search results
        for result in semantic_results:
            try:
                doc_id = result['document']['id']
                if doc_id in combined_results:
                    combined_results[doc_id]['semantic_score'] = result.get('score', 0)
                else:
                    combined_results[doc_id] = {
                        'document': result['document'],
                        'accurate_score': 0,
                        'semantic_score': result.get('score', 0),
                        'index': result['index']  # Keep track of source index
                    }
            except KeyError as e:
                logger.warning(f"Warning: Missing required field in semantic result: {e}")
                continue

        # Calculate maximum scores
        max_accurate = max([r.get('score', 0) for r in accurate_results]) if accurate_results else 1
        max_semantic = max([r.get('score', 0) for r in semantic_results]) if semantic_results else 1

        # Calculate combined scores and sort
        results = []
        for doc_id, result in combined_results.items():
            try:
                # Get scores safely
                accurate_score = result.get('accurate_score', 0)
                semantic_score = result.get('semantic_score', 0)

                # Normalize scores
                normalized_accurate = accurate_score / max_accurate if max_accurate > 0 else 0
                normalized_semantic = semantic_score / max_semantic if max_semantic > 0 else 0

                # Calculate weighted combined score
                combined_score = (weight_accurate * normalized_accurate +
                                (1 - weight_accurate) * normalized_semantic)

                results.append({
                    'score': combined_score,
                    'document': result['document'],
                    'index': result['index'],  # Include source index in results
                    'scores': {
                        'accurate': normalized_accurate,
                        'semantic': normalized_semantic
                    }
                })
            except KeyError as e:
                logger.warning(f"Warning: Error processing result for doc_id {doc_id}: {e}")
                continue

        # Sort by combined score and return top k results
        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:top_k]

    # ---- STATISTICS AND MONITORING ----
    def get_file_list_with_details(self, index_name: str) -> List[Dict[str, Any]]:
        """
        Get a list of unique path_or_url values with their file_size and create_time
        
        Args:
            index_name: Name of the index to query
            
        Returns:
            List of dictionaries with path_or_url, file_size, and create_time
        """
        agg_query = {
            "size": 0,
            "aggs": {
                "unique_sources": {
                    "terms": {
                        "field": "path_or_url",
                        "size": 1000  # Limit to 1000 files for performance
                    },
                    "aggs": {
                        "file_sample": {
                            "top_hits": {
                                "size": 1,
                                "_source": ["path_or_url", "file_size", "create_time", "filename"]
                            }
                        }
                    }
                }
            }
        }
        
        try:
            result = self.client.search(
                index=index_name,
                body=agg_query
            )
            
            file_list = []
            for bucket in result['aggregations']['unique_sources']['buckets']:
                source = bucket['file_sample']['hits']['hits'][0]['_source']
                file_info = {
                    "path_or_url": source["path_or_url"],
                    "filename": source.get("filename", ""),
                    "file_size": source.get("file_size", 0),
                    "create_time": source.get("create_time", None)
                }
                file_list.append(file_info)
            
            return file_list
        except Exception as e:
            logger.error(f"Error getting file list: {str(e)}")
            return []
            
    def get_index_mapping(self, index_names: List[str]) -> Dict[str, List[str]]:
        """Get field mappings for multiple indices"""
        mappings = {}
        for index_name in index_names:
            try:
                mapping = self.client.indices.get_mapping(index=index_name)
                if mapping[index_name].get('mappings') and mapping[index_name]['mappings'].get('properties'):
                    mappings[index_name] = list(mapping[index_name]['mappings']['properties'].keys())
                else:
                    mappings[index_name] = []
            except Exception as e:
                logger.error(f"Error getting mapping for index {index_name}: {str(e)}")
                mappings[index_name] = []
        return mappings
            
    def get_index_stats(self, index_names: List[str], embedding_dim: Optional[int] = None) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """Get formatted statistics for multiple indices"""
        all_stats = {}
        for index_name in index_names:
            try:
                stats = self.client.indices.stats(index=index_name)
                settings = self.client.indices.get_settings(index=index_name)

                # Merge query
                agg_query = {
                    "size": 0,
                    "aggs": {
                        "unique_path_or_url_count": {
                            "cardinality": {
                                "field": "path_or_url"
                            }
                        },
                        "process_sources": {
                            "terms": {
                                "field": "process_source",
                                "size": 10
                            }
                        },
                        "embedding_models": {
                            "terms": {
                                "field": "embedding_model_name",
                                "size": 10
                            }
                        }
                    }
                }

                # Execute query
                agg_result = self.client.search(
                    index=index_name,
                    body=agg_query
                )

                unique_sources_count = agg_result['aggregations']['unique_path_or_url_count']['value']
                process_source = agg_result['aggregations']['process_sources']['buckets'][0]['key'] if agg_result['aggregations']['process_sources']['buckets'] else ""
                embedding_model = agg_result['aggregations']['embedding_models']['buckets'][0]['key'] if agg_result['aggregations']['embedding_models']['buckets'] else ""

                index_stats = stats["indices"][index_name]["primaries"]

                # Get creation and update timestamps from settings
                creation_date = int(settings[index_name]['settings']['index']['creation_date'])
                # Update time defaults to creation time if not modified
                update_time = creation_date

                all_stats[index_name] = {
                    "base_info": {
                        "doc_count": unique_sources_count,
                        "chunk_count": index_stats["docs"]["count"],
                        "store_size": format_size(index_stats["store"]["size_in_bytes"]),
                        "process_source": process_source,
                        "embedding_model": embedding_model,
                        "embedding_dim": embedding_dim or 1024,
                        "creation_date": creation_date,
                        "update_date": update_time
                    },
                    "search_performance": {
                        "total_search_count": index_stats["search"]["query_total"],
                        "hit_count": index_stats["request_cache"]["hit_count"],
                    }
                }
            except Exception as e:
                logger.error(f"Error getting stats for index {index_name}: {str(e)}")
                all_stats[index_name] = {"error": str(e)}

        return all_stats
        