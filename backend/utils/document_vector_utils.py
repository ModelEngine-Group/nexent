"""
Document Vector Utilities Module

This module provides utilities for document-level vector operations and clustering.
Main features:
1. Document-level vector calculation (weighted average of chunk vectors)
2. Automatic K-means clustering with optimal K determination
3. Document grouping and classification
4. Cluster summarization
"""
import logging
import random
from typing import Dict, List, Optional, Tuple

import numpy as np
from jinja2 import Template, StrictUndefined
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.metrics.pairwise import cosine_similarity

from consts.const import LANGUAGE
from database.model_management_db import get_model_by_model_id
from nexent.core.utils.observer import MessageObserver
from nexent.core.models import OpenAIModel
from nexent.vector_database.base import VectorDatabaseCore
from utils.llm_utils import call_llm_for_system_prompt
from utils.prompt_template_utils import (
    get_document_summary_prompt_template,
    get_cluster_summary_reduce_prompt_template,
    get_cluster_summary_agent_prompt_template
)

logger = logging.getLogger("document_vector_utils")


def get_documents_from_es(index_name: str, vdb_core: VectorDatabaseCore, sample_doc_count: int = 200) -> Dict[str, Dict]:
    """
    Get document samples from Elasticsearch, aggregated by path_or_url
    
    Args:
        index_name: Name of the index to query
        vdb_core: VectorDatabaseCore instance
        sample_doc_count: Number of documents to sample
        
    Returns:
        Dictionary mapping document IDs to document information with chunks
    """
    try:
        # Step 1: Aggregate unique documents by path_or_url
        agg_query = {
            "size": 0,
            "aggs": {
                "unique_documents": {
                    "terms": {
                        "field": "path_or_url",
                        "size": 10000  # Get all unique documents
                    }
                }
            }
        }
        
        logger.info(f"Fetching unique documents from index {index_name}")
        agg_response = vdb_core.search(index_name=index_name, query=agg_query)
        all_documents = agg_response['aggregations']['unique_documents']['buckets']
        
        if not all_documents:
            logger.warning(f"No documents found in index {index_name}")
            return {}
        
        # Step 2: Random sample documents
        sample_count = min(sample_doc_count, len(all_documents))
        # Ensure all_documents is a list for random.sample
        if not isinstance(all_documents, list):
            all_documents = list(all_documents)
        sampled_docs = random.sample(all_documents, sample_count)
        
        logger.info(f"Sampled {sample_count} documents from {len(all_documents)} total documents")
        
        # Step 3: Get all chunks for each sampled document
        document_samples = {}
        for doc_bucket in sampled_docs:
            path_or_url = doc_bucket['key']
            chunk_count = doc_bucket['doc_count']
            
            # Get all chunks for this document
            chunks_query = {
                "query": {
                    "term": {"path_or_url": path_or_url}
                },
                "size": chunk_count,  # Get all chunks
                "sort": [
                    {
                        "create_time": {
                            "order": "asc",
                            "missing": "_last"  # Put documents without create_time at the end
                        }
                    }
                ]
            }
            
            chunks_response = vdb_core.search(index_name=index_name, query=chunks_query)
            chunks = [hit['_source'] for hit in chunks_response['hits']['hits']]
            
            # Build document object
            if chunks:
                doc_id = f"doc_{len(document_samples):04d}"
                document_samples[doc_id] = {
                    "doc_id": doc_id,
                    "path_or_url": path_or_url,
                    "filename": chunks[0].get('filename', 'unknown'),
                    "chunk_count": chunk_count,
                    "chunks": chunks,
                    "file_size": chunks[0].get('file_size', 0)
                }
        
        logger.info(f"Successfully retrieved {len(document_samples)} documents with chunks")
        return document_samples
        
    except Exception as e:
        logger.error(f"Error retrieving documents from ES: {str(e)}", exc_info=True)
        raise Exception(f"Failed to retrieve documents from Elasticsearch: {str(e)}")


def calculate_document_embedding(doc_chunks: List[Dict], use_weighted: bool = True) -> Optional[np.ndarray]:
    """
    Calculate document-level embedding from chunk embeddings
    
    Args:
        doc_chunks: List of chunk dictionaries containing 'embedding' and 'content' fields
        use_weighted: Whether to use weighted average based on content length
        
    Returns:
        Document-level embedding vector or None if no valid embeddings found
    """
    try:
        embeddings = []
        weights = []
        
        for chunk in doc_chunks:
            chunk_embedding = chunk.get('embedding')
            if chunk_embedding and isinstance(chunk_embedding, list):
                embeddings.append(np.array(chunk_embedding))
                
                if use_weighted:
                    # Weight by content length only (removed position-based weight to reduce order dependency)
                    content_length = len(chunk.get('content', ''))
                    weight = content_length
                    weights.append(weight)
        
        if not embeddings:
            logger.warning("No valid embeddings found in chunks")
            return None
        
        # Convert to numpy array
        embeddings_array = np.array(embeddings)
        
        if use_weighted and weights:
            # Weighted average
            total_weight = sum(weights)
            weights_normalized = np.array(weights) / total_weight
            doc_embedding = np.average(embeddings_array, axis=0, weights=weights_normalized)
        else:
            # Simple average
            doc_embedding = np.mean(embeddings_array, axis=0)
        
        return doc_embedding
        
    except Exception as e:
        logger.error(f"Error calculating document embedding: {str(e)}", exc_info=True)
        return None


def auto_determine_k(embeddings: np.ndarray, min_k: int = 3, max_k: int = 15) -> int:
    """
    Automatically determine optimal K value for K-means clustering
    
    Args:
        embeddings: Array of document embeddings
        min_k: Minimum number of clusters
        max_k: Maximum number of clusters
        
    Returns:
        Optimal K value
    """
    try:
        n_samples = len(embeddings)
        
        # Handle edge cases
        if n_samples < min_k:
            return max(2, n_samples)
        
        if n_samples < 20:
            # For small datasets, use simple heuristic
            heuristic_k = max(min_k, min(int(np.sqrt(n_samples / 2)), max_k))
            return heuristic_k
        
        # Determine K range based on dataset size
        actual_max_k = min(max_k, n_samples // 10, 15)  # At least 10 samples per cluster
        actual_min_k = min(min_k, actual_max_k)
        
        # Try different K values and calculate silhouette score
        best_k = actual_min_k
        best_score = -1
        
        k_range = range(actual_min_k, actual_max_k + 1)
        logger.info(f"Trying K values from {actual_min_k} to {actual_max_k}")
        
        for k in k_range:
            try:
                kmeans = KMeans(n_clusters=k, random_state=42, n_init=10, max_iter=300)
                labels = kmeans.fit_predict(embeddings)
                
                # Calculate silhouette score
                score = silhouette_score(embeddings, labels, sample_size=min(1000, n_samples))
                
                logger.debug(f"K={k}, Silhouette Score={score:.4f}")
                
                if score > best_score:
                    best_score = score
                    best_k = k
                    
            except Exception as e:
                logger.warning(f"Error calculating K={k}: {str(e)}")
                continue
        
        logger.info(f"Optimal K determined: {best_k} (Silhouette Score: {best_score:.4f})")
        return best_k
        
    except Exception as e:
        logger.error(f"Error in auto_determine_k: {str(e)}", exc_info=True)
        # Fallback to heuristic
        heuristic_k = max(min_k, min(int(np.sqrt(len(embeddings) / 2)), max_k))
        logger.warning(f"Using fallback K value: {heuristic_k}")
        return heuristic_k


def merge_duplicate_documents_in_clusters(clusters: Dict[int, List[str]], doc_embeddings: Dict[str, np.ndarray], similarity_threshold: float = 0.98) -> Dict[int, List[str]]:
    """
    Post-process clusters to merge duplicate documents (same content but different path_or_url)
    that were incorrectly split into different clusters.
    
    Args:
        clusters: Dictionary mapping cluster IDs to lists of document IDs
        doc_embeddings: Dictionary mapping document IDs to their embeddings
        similarity_threshold: Cosine similarity threshold to consider documents as duplicates (default: 0.98)
        
    Returns:
        Updated clusters dictionary with duplicate documents merged
    """
    try:
        if not clusters or not doc_embeddings:
            return clusters
        
        # Skip merging if there's only one cluster (nothing to merge)
        if len(clusters) <= 1:
            return clusters
        
        # Build a mapping from doc_id to its current cluster
        doc_to_cluster = {}
        for cluster_id, doc_ids in clusters.items():
            for doc_id in doc_ids:
                doc_to_cluster[doc_id] = cluster_id
        
        # Find duplicate pairs with high similarity
        doc_ids_list = list(doc_embeddings.keys())
        merged_pairs = []
        
        for i, doc_id1 in enumerate(doc_ids_list):
            if doc_id1 not in doc_embeddings:
                continue
            
            embedding1 = doc_embeddings[doc_id1]
            
            for j, doc_id2 in enumerate(doc_ids_list[i+1:], start=i+1):
                if doc_id2 not in doc_embeddings:
                    continue
                
                embedding2 = doc_embeddings[doc_id2]
                
                # Calculate cosine similarity
                similarity = cosine_similarity(
                    embedding1.reshape(1, -1),
                    embedding2.reshape(1, -1)
                )[0][0]
                
                # If similarity is very high, they are likely duplicates
                if similarity >= similarity_threshold:
                    cluster1 = doc_to_cluster.get(doc_id1)
                    cluster2 = doc_to_cluster.get(doc_id2)
                    
                    # Only merge if they are in different clusters AND truly duplicates
                    # Check both cosine similarity AND Euclidean distance to prevent false positives
                    if cluster1 is not None and cluster2 is not None and cluster1 != cluster2:
                        # Calculate Euclidean distance to ensure they're truly duplicates
                        # Documents that are just in the same direction but far apart should not be merged
                        euclidean_distance = np.linalg.norm(embedding1 - embedding2)
                        
                        # Normalize embeddings to get their magnitudes
                        norm1 = np.linalg.norm(embedding1)
                        norm2 = np.linalg.norm(embedding2)
                        avg_norm = (norm1 + norm2) / 2.0
                        
                        # Relative distance threshold: if distance is less than 1% of average magnitude,
                        # they are likely true duplicates (same content, different path_or_url)
                        # This prevents merging documents that are just in similar directions
                        relative_distance_threshold = 0.01 * avg_norm if avg_norm > 0 else 0.1
                        
                        if euclidean_distance <= relative_distance_threshold:
                            merged_pairs.append((doc_id1, doc_id2, cluster1, cluster2, similarity))
                            logger.info(f"Found duplicate documents: {doc_id1} and {doc_id2} (similarity: {similarity:.4f}, distance: {euclidean_distance:.4f}) in different clusters {cluster1} and {cluster2}")
        
        # Merge duplicate documents into the same cluster
        if merged_pairs:
            logger.info(f"Merging {len(merged_pairs)} pairs of duplicate documents")
            
            # Build a graph of duplicate relationships using union-find
            parent = {}
            
            def find(x):
                if x not in parent:
                    parent[x] = x
                if parent[x] != x:
                    parent[x] = find(parent[x])
                return parent[x]
            
            def union(x, y):
                px, py = find(x), find(y)
                if px != py:
                    parent[px] = py
            
            # Build union-find structure
            for doc_id1, doc_id2, _, _, _ in merged_pairs:
                union(doc_id1, doc_id2)
            
            # Group documents by their root parent
            # Only include documents that are part of duplicate pairs
            duplicate_doc_ids = set()
            for doc_id1, doc_id2, _, _, _ in merged_pairs:
                duplicate_doc_ids.add(doc_id1)
                duplicate_doc_ids.add(doc_id2)
            
            groups = {}
            for doc_id in duplicate_doc_ids:
                root = find(doc_id)
                if root not in groups:
                    groups[root] = []
                groups[root].append(doc_id)
            
            # Merge each group into the same cluster
            for root, doc_group in groups.items():
                if len(doc_group) < 2:
                    continue
                
                # Find all clusters containing documents in this group
                clusters_in_group = set()
                for doc_id in doc_group:
                    if doc_id in doc_to_cluster:
                        clusters_in_group.add(doc_to_cluster[doc_id])
                
                if len(clusters_in_group) > 1:
                    # Merge all documents to the smallest cluster ID
                    target_cluster = min(clusters_in_group)
                    
                    for doc_id in doc_group:
                        current_cluster = doc_to_cluster.get(doc_id)
                        if current_cluster is not None and current_cluster != target_cluster:
                            # Move document to target cluster
                            if current_cluster in clusters and doc_id in clusters[current_cluster]:
                                clusters[current_cluster].remove(doc_id)
                            if target_cluster not in clusters:
                                clusters[target_cluster] = []
                            if doc_id not in clusters[target_cluster]:
                                clusters[target_cluster].append(doc_id)
                            doc_to_cluster[doc_id] = target_cluster
                            logger.debug(f"Moved {doc_id} from cluster {current_cluster} to cluster {target_cluster}")
            
            # Remove empty clusters
            empty_clusters = [cid for cid, docs in clusters.items() if not docs]
            for cid in empty_clusters:
                del clusters[cid]
                logger.debug(f"Removed empty cluster {cid}")
            
            logger.info(f"Successfully merged duplicate documents. Final cluster count: {len(clusters)}")
        
        return clusters
        
    except Exception as e:
        logger.error(f"Error merging duplicate documents: {str(e)}", exc_info=True)
        # Return original clusters if merge fails
        return clusters


def kmeans_cluster_documents(doc_embeddings: Dict[str, np.ndarray], k: Optional[int] = None) -> Dict[int, List[str]]:
    """
    Cluster documents using K-means
    
    Args:
        doc_embeddings: Dictionary mapping document IDs to their embeddings
        k: Number of clusters (if None, auto-determined)
        
    Returns:
        Dictionary mapping cluster IDs to lists of document IDs
    """
    try:
        if not doc_embeddings:
            logger.warning("No document embeddings provided")
            return {}
        
        # Prepare embeddings array
        doc_ids = list(doc_embeddings.keys())
        embeddings_array = np.array([doc_embeddings[doc_id] for doc_id in doc_ids])
        
        # Handle single document case
        if len(doc_ids) == 1:
            logger.info("Only one document found, skipping clustering")
            return {0: doc_ids}
        
        # Determine K value
        if k is None:
            k = auto_determine_k(embeddings_array)
        
        # Ensure k is not greater than number of documents
        k = min(k, len(doc_ids))
        
        logger.info(f"Clustering {len(doc_ids)} documents into {k} clusters")
        
        # Perform K-means clustering
        kmeans = KMeans(n_clusters=k, random_state=42, n_init=10, max_iter=300)
        labels = kmeans.fit_predict(embeddings_array)
        
        # Group documents by cluster
        clusters = {}
        for i, label in enumerate(labels):
            if label not in clusters:
                clusters[label] = []
            clusters[label].append(doc_ids[i])
        
        # Log cluster sizes
        for cluster_id, docs in clusters.items():
            logger.info(f"Cluster {cluster_id}: {len(docs)} documents")
        
        # Post-process: merge duplicate documents that were split into different clusters
        clusters = merge_duplicate_documents_in_clusters(clusters, doc_embeddings, similarity_threshold=0.98)
        
        # Log final cluster sizes after merge
        for cluster_id, docs in clusters.items():
            logger.info(f"Final cluster {cluster_id}: {len(docs)} documents")
        
        return clusters
        
    except Exception as e:
        logger.error(f"Error in K-means clustering: {str(e)}", exc_info=True)
        raise Exception(f"Failed to cluster documents: {str(e)}")


def process_documents_for_clustering(index_name: str, vdb_core, sample_doc_count: int = 200) -> Tuple[Dict[str, Dict], Dict[str, np.ndarray]]:
    """
    Complete workflow: Get documents from ES and calculate their embeddings
    
    Args:
        index_name: Name of the index to query
        vdb_core: ElasticSearchCore instance
        sample_doc_count: Number of documents to sample
        
    Returns:
        Tuple of (document_samples dict, doc_embeddings dict)
    """
    try:
        # Step 1: Get documents from ES
        document_samples = get_documents_from_es(index_name, vdb_core, sample_doc_count)
        
        if not document_samples:
            logger.warning("No documents retrieved from ES")
            return {}, {}
        
        # Step 2: Calculate document-level embeddings
        doc_embeddings = {}
        for doc_id, doc_info in document_samples.items():
            chunks = doc_info['chunks']
            doc_embedding = calculate_document_embedding(chunks, use_weighted=True)
            
            if doc_embedding is not None:
                doc_embeddings[doc_id] = doc_embedding
            else:
                logger.warning(f"Failed to calculate embedding for document {doc_id}")
        
        logger.info(f"Successfully calculated embeddings for {len(doc_embeddings)} documents")
        return document_samples, doc_embeddings
        
    except Exception as e:
        logger.error(f"Error processing documents for clustering: {str(e)}", exc_info=True)
        raise Exception(f"Failed to process documents: {str(e)}")


def extract_cluster_content(document_samples: Dict[str, Dict], cluster_doc_ids: List[str], max_chunks_per_doc: int = 3) -> str:
    """
    Extract representative content from a cluster for summarization
    
    Args:
        document_samples: Dictionary mapping doc_id to document info
        cluster_doc_ids: List of document IDs in the cluster
        max_chunks_per_doc: Maximum number of chunks to include per document
        
    Returns:
        Formatted string containing cluster content
    """
    cluster_content_parts = []
    
    for doc_id in cluster_doc_ids:
        if doc_id not in document_samples:
            continue
            
        doc_info = document_samples[doc_id]
        chunks = doc_info.get('chunks', [])
        filename = doc_info.get('filename', 'unknown')
        
        # Extract representative chunks
        representative_chunks = []
        if len(chunks) <= max_chunks_per_doc:
            representative_chunks = chunks
        else:
            # Take first, middle, and last chunks
            representative_chunks = (
                chunks[:1] + 
                chunks[len(chunks)//2:len(chunks)//2+1] + 
                chunks[-1:]
            )
        
        # Format document content
        doc_content = f"\n--- Document: {filename} ---\n"
        for chunk in representative_chunks:
            content = chunk.get('content', '')
            # Limit chunk content length
            if len(content) > 500:
                content = content[:500] + "..."
            doc_content += f"{content}\n"
        
        cluster_content_parts.append(doc_content)
    
    return "\n".join(cluster_content_parts)


def summarize_document(document_content: str, filename: str, language: str = LANGUAGE["ZH"], max_words: int = 100, model_id: Optional[int] = None, tenant_id: Optional[str] = None) -> str:
    """
    Summarize a single document using LLM (Map stage)
    
    Args:
        document_content: Formatted content from document chunks
        filename: Document filename
        language: Language code ('zh' or 'en')
        max_words: Maximum words in the summary
        model_id: Model ID for LLM call
        tenant_id: Tenant ID for model configuration
        
    Returns:
        Document summary text
    """
    try:
        # Get prompt template from prompt_template_utils
        prompts = get_document_summary_prompt_template(language)
        
        system_prompt = prompts.get('system_prompt', '')
        user_prompt_template = prompts.get('user_prompt', '')
        
        user_prompt = Template(user_prompt_template, undefined=StrictUndefined).render(
            filename=filename,
            content=document_content,
            max_words=max_words
        )
        
        logger.info(f"Document summary prompt generated for {filename} (max_words: {max_words})")
        
        # Call LLM if model_id and tenant_id are provided
        if model_id and tenant_id:

            # Get model configuration
            llm_model_config = get_model_by_model_id(model_id=model_id, tenant_id=tenant_id)
            if not llm_model_config:
                logger.warning(f"No model configuration found for model_id: {model_id}, tenant_id: {tenant_id}")
                return f"[Document Summary: {filename}] (max {max_words} words) - Content: {document_content[:200]}..."

            document_summary = call_llm_for_system_prompt(
                model_id=model_id,
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                callback=None,
                tenant_id=tenant_id
            )

            return (document_summary or "").strip()
        else:
            # Fallback to placeholder if no model configuration
            logger.warning("No model_id or tenant_id provided, using placeholder summary")
            return f"[Document Summary: {filename}] (max {max_words} words) - Content: {document_content[:200]}..."
        
    except Exception as e:
        logger.error(f"Error generating document summary: {str(e)}", exc_info=True)
        return f"Failed to generate summary for {filename}: {str(e)}"


def summarize_cluster(document_summaries: List[str], language: str = LANGUAGE["ZH"], max_words: int = 150, model_id: Optional[int] = None, tenant_id: Optional[str] = None) -> str:
    """
    Summarize a cluster of documents using LLM (Reduce stage)
    
    Args:
        document_summaries: List of individual document summaries
        language: Language code ('zh' or 'en')
        max_words: Maximum words in the summary
        model_id: Model ID for LLM call
        tenant_id: Tenant ID for model configuration
        
    Returns:
        Cluster summary text
    """
    try:
        # Get prompt template from prompt_template_utils
        prompts = get_cluster_summary_reduce_prompt_template(language)
        
        system_prompt = prompts.get('system_prompt', '')
        user_prompt_template = prompts.get('user_prompt', '')
        
        # Format document summaries
        summaries_text = "\n\n".join([f"Document {i+1}: {summary}" for i, summary in enumerate(document_summaries)])
        
        user_prompt = Template(user_prompt_template, undefined=StrictUndefined).render(
            document_summaries=summaries_text,
            max_words=max_words
        )
        
        logger.info(f"Cluster summary prompt generated (language: {language}, max_words: {max_words})")
        
        # Call LLM if model_id and tenant_id are provided
        if model_id and tenant_id:
            
            # Get model configuration
            llm_model_config = get_model_by_model_id(model_id=model_id, tenant_id=tenant_id)
            if not llm_model_config:
                logger.warning(f"No model configuration found for model_id: {model_id}, tenant_id: {tenant_id}")
                return f"[Cluster Summary] (max {max_words} words) - Based on {len(document_summaries)} documents"
            
            # Create LLM instance
            cluster_summary = call_llm_for_system_prompt(
                model_id=model_id,
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                callback=None,
                tenant_id=tenant_id
            )

            return (cluster_summary or "").strip()
        else:
            # Fallback to placeholder if no model configuration
            logger.warning("No model_id or tenant_id provided, using placeholder summary")
            return f"[Cluster Summary] (max {max_words} words) - Based on {len(document_summaries)} documents"
        
    except Exception as e:
        logger.error(f"Error generating cluster summary: {str(e)}", exc_info=True)
        return f"Failed to generate summary: {str(e)}"


def extract_representative_chunks_smart(chunks: List[Dict], max_chunks: int = 3) -> List[Dict]:
    """
    Intelligently extract representative chunks from a document
    
    Strategy:
    1. Always include first chunk (usually contains title/abstract)
    2. Extract chunks with highest keyword density (important content)
    3. Include last chunk if significant (may contain conclusions)
    
    Args:
        chunks: List of chunk dictionaries with 'content' field
        max_chunks: Maximum number of chunks to return
        
    Returns:
        List of representative chunks
    """
    if len(chunks) <= max_chunks:
        return chunks
    
    selected_chunks = []
    
    # 1. Always include first chunk
    selected_chunks.append(chunks[0])
    
    # 2. Find chunks with high keyword density
    try:
        from nexent.core.nlp.tokenizer import calculate_term_weights
    except ImportError:
        # Fallback: use simple scoring
        logger.warning("Could not import calculate_term_weights, using simple scoring")
        # Simple fallback: just pick middle chunks
        if len(chunks) > 1:
            selected_chunks.append(chunks[len(chunks)//2])
        if len(selected_chunks) < max_chunks and len(chunks) > 2:
            selected_chunks.append(chunks[-1])
        return selected_chunks[:max_chunks]
    
    chunk_scores = []
    for i, chunk in enumerate(chunks[1:-1]):  # Skip first and last
        content = chunk.get('content', '')
        if len(content) > 500:
            # Calculate keyword density (use first 500 chars for speed)
            keywords = calculate_term_weights(content[:500])
            score = len(keywords) * 0.5 + len(content) * 0.001  # Balance keyword count and length
            chunk_scores.append((i + 1, score, chunk))
    
    # Sort by score and pick top chunks
    chunk_scores.sort(key=lambda x: x[1], reverse=True)
    remaining_slots = max_chunks - 1  # Already have first chunk
    
    for idx, score, chunk in chunk_scores[:remaining_slots]:
        selected_chunks.append(chunk)
    
    # 3. If we have space, include last chunk
    if len(selected_chunks) < max_chunks and len(chunks) > 1:
        selected_chunks.append(chunks[-1])
    
    return selected_chunks[:max_chunks]


def merge_cluster_summaries(cluster_summaries: Dict[int, str]) -> str:
    """
    Merge all cluster summaries into a final knowledge base summary
    
    Args:
        cluster_summaries: Dictionary mapping cluster_id to cluster summary
        
    Returns:
        Final merged knowledge base summary
    """
    if not cluster_summaries:
        return ""
    
    # Sort by cluster ID for consistent output
    sorted_clusters = sorted(cluster_summaries.items())
    
    # Format cluster summaries with HTML paragraph tags for explicit rendering
    summary_parts = []
    for _, summary in sorted_clusters:
        if summary.strip():
            # Wrap each summary in <p> tags for explicit paragraph rendering
            summary_parts.append(f"<p>{summary.strip()}</p>")
    
    # Join with simple double newlines, as <p> tags already handle block-level separation
    final_summary = "\n\n".join(summary_parts)
    
    logger.info(f"Merged {len(cluster_summaries)} cluster summaries into final knowledge base summary")
    return final_summary


def analyze_cluster_coherence(cluster_doc_ids: List[str], document_samples: Dict[str, Dict]) -> Dict[str, any]:
    """
    Analyze coherence and structure of documents within a cluster
    
    Returns:
        Dict with analysis results including common themes, document types, etc.
    """
    if not cluster_doc_ids:
        return {}
    
    # Extract document titles and content previews
    doc_previews = []
    for doc_id in cluster_doc_ids:
        if doc_id in document_samples:
            doc_info = document_samples[doc_id]
            filename = doc_info.get('filename', 'unknown')
            chunks = doc_info.get('chunks', [])
            if chunks:
                first_chunk = chunks[0].get('content', '')[:200]
                doc_previews.append({'filename': filename, 'preview': first_chunk})
    
    return {
        'doc_count': len(cluster_doc_ids),
        'doc_previews': doc_previews,
        'file_types': [doc['filename'].split('.')[-1] for doc in doc_previews if '.' in doc['filename']]
    }


def summarize_clusters_map_reduce(document_samples: Dict[str, Dict], clusters: Dict[int, List[str]], 
                                  language: str = LANGUAGE["ZH"], doc_max_words: int = 100, cluster_max_words: int = 150,
                                  use_smart_chunk_selection: bool = True, enhance_with_metadata: bool = True,
                                  model_id: Optional[int] = None, tenant_id: Optional[str] = None) -> Dict[int, str]:
    """
    Summarize all clusters using Map-Reduce approach
    
    Map stage: Summarize each document individually (within each cluster)
    Reduce stage: Combine document summaries within the same cluster into a cluster summary
    Note: Clusters remain separate - we combine document summaries WITHIN each cluster
    
    Args:
        document_samples: Dictionary mapping doc_id to document info
        clusters: Dictionary mapping cluster_id to list of doc_ids
        language: Language code ('zh' or 'en')
        doc_max_words: Maximum words per document summary
        cluster_max_words: Maximum words per cluster summary
        use_smart_chunk_selection: Use intelligent chunk selection based on keyword density
        enhance_with_metadata: Enhance summaries with document metadata
        model_id: Model ID for LLM calls
        tenant_id: Tenant ID for model configuration
        
    Returns:
        Dictionary mapping cluster_id to summary text
    """
    cluster_summaries = {}
    
    for cluster_id, doc_ids in clusters.items():
        logger.info(f"Summarizing cluster {cluster_id} with {len(doc_ids)} documents using Map-Reduce")
        
        # Map stage: Summarize each document
        document_summaries = []
        for doc_id in doc_ids:
            if doc_id not in document_samples:
                continue
            
            doc_info = document_samples[doc_id]
            chunks = doc_info.get('chunks', [])
            filename = doc_info.get('filename', 'unknown')
            
            # Extract representative content for this document
            if use_smart_chunk_selection:
                representative_chunks = extract_representative_chunks_smart(chunks, max_chunks=3)
            else:
                # Simple approach: first, middle, last
                if len(chunks) <= 3:
                    representative_chunks = chunks
                else:
                    representative_chunks = (
                        chunks[:1] + 
                        chunks[len(chunks)//2:len(chunks)//2+1] + 
                        chunks[-1:]
                    )
            
            # Format document content (merge top-K chunks)
            doc_content = ""
            for i, chunk in enumerate(representative_chunks):
                content = chunk.get('content', '')
                # Limit each chunk length for individual document
                if len(content) > 1000:
                    content = content[:1000] + "..."
                # Add chunk separator
                doc_content += f"[Chunk {i+1}]\n{content}\n\n"
            
            # Generate document summary from merged chunks
            logger.info(f"Summarizing document {filename} with {len(representative_chunks)} representative chunks")
            doc_summary = summarize_document(doc_content, filename, language, doc_max_words, model_id, tenant_id)
            document_summaries.append(doc_summary)
        
        # Reduce stage: Combine document summaries within this cluster into cluster summary
        if document_summaries:
            # Optionally enhance with cluster analysis
            if enhance_with_metadata:
                cluster_analysis = analyze_cluster_coherence(doc_ids, document_samples)
                logger.info(f"Cluster {cluster_id} analysis: {cluster_analysis.get('doc_count', 0)} documents")
            
            cluster_summary = summarize_cluster(document_summaries, language, cluster_max_words, model_id, tenant_id)
            cluster_summaries[cluster_id] = cluster_summary
        else:
            logger.warning(f"No valid documents found in cluster {cluster_id}")
            cluster_summaries[cluster_id] = "No content available for this cluster"
    
    return cluster_summaries


def summarize_clusters(document_samples: Dict[str, Dict], clusters: Dict[int, List[str]], 
                       language: str = LANGUAGE["ZH"], max_words: int = 150) -> Dict[int, str]:
    """
    Summarize all clusters (legacy method - kept for backward compatibility)
    
    Note: This method uses the old approach. Use summarize_clusters_map_reduce for better results.
    
    Args:
        document_samples: Dictionary mapping doc_id to document info
        clusters: Dictionary mapping cluster_id to list of doc_ids
        language: Language code ('zh' or 'en')
        max_words: Maximum words per cluster summary
        
    Returns:
        Dictionary mapping cluster_id to summary text
    """
    cluster_summaries = {}
    
    for cluster_id, doc_ids in clusters.items():
        logger.info(f"Summarizing cluster {cluster_id} with {len(doc_ids)} documents")
        
        # Extract cluster content
        cluster_content = extract_cluster_content(document_samples, doc_ids, max_chunks_per_doc=3)
        
        # Generate summary using old method
        summary = summarize_cluster_legacy(cluster_content, language, max_words)
        cluster_summaries[cluster_id] = summary
    
    return cluster_summaries


def summarize_cluster_legacy(cluster_content: str, language: str = LANGUAGE["ZH"], max_words: int = 150) -> str:
    """
    Legacy cluster summarization method (single-stage)
    
    Args:
        cluster_content: Formatted content from the cluster
        language: Language code ('zh' or 'en')
        max_words: Maximum words in the summary
        
    Returns:
        Cluster summary text
    """
    try:
        # Get prompt template from prompt_template_utils
        prompts = get_cluster_summary_agent_prompt_template(language)
        
        system_prompt = prompts.get('system_prompt', '')
        user_prompt_template = prompts.get('user_prompt', '')
        
        user_prompt = Template(user_prompt_template, undefined=StrictUndefined).render(
            cluster_content=cluster_content,
            max_words=max_words
        )
        
        logger.info(f"Cluster summary prompt generated (language: {language}, max_words: {max_words})")
        
        # Note: This is a legacy function, using placeholder summary
        # The main summarization uses summarize_cluster() with LLM integration
        return f"[Cluster Summary] (max {max_words} words) - Content preview: {cluster_content[:200]}..."
        
    except Exception as e:
        logger.error(f"Error generating cluster summary: {str(e)}", exc_info=True)
        return f"Failed to generate summary: {str(e)}"

