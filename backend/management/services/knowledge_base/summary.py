# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Knowledge document summary."""

import logging
import random
from typing import Dict, List, Optional, Tuple

import numpy as np
from contracts.constants.localization import LANGUAGE
from management.db.model.repository import get_model_by_model_id
from management.services.knowledge_base.clustering import (
    analyze_cluster_coherence,
    calculate_document_embedding,
)
from management.services.model.invocation import call_llm_for_system_prompt
from nexent.core.agents.prompt.auxiliary import compose_auxiliary_prompt
from nexent.core.agents.prompt.document import compose_document_cluster_summary
from nexent.vector_database.base import VectorDatabaseCore

logger = logging.getLogger(__name__)


def get_documents_from_es(
    index_name: str, vdb_core: VectorDatabaseCore, sample_doc_count: int = 200
) -> Dict[str, Dict]:
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
                        "size": 10000,  # Get all unique documents
                    }
                }
            },
        }

        logger.info(f"Fetching unique documents from index {index_name}")
        agg_response = vdb_core.search(index_name=index_name, query=agg_query)
        all_documents = agg_response["aggregations"]["unique_documents"]["buckets"]

        if not all_documents:
            logger.warning(f"No documents found in index {index_name}")
            return {}

        # Step 2: Random sample documents
        sample_count = min(sample_doc_count, len(all_documents))
        # Ensure all_documents is a list for random.sample
        if not isinstance(all_documents, list):
            all_documents = list(all_documents)
        sampled_docs = random.sample(all_documents, sample_count)

        logger.info(
            f"Sampled {sample_count} documents from {len(all_documents)} total documents"
        )

        # Step 3: Get all chunks for each sampled document
        document_samples = {}
        for doc_bucket in sampled_docs:
            path_or_url = doc_bucket["key"]
            chunk_count = doc_bucket["doc_count"]

            # Get all chunks for this document
            chunks_query = {
                "query": {"term": {"path_or_url": path_or_url}},
                "size": chunk_count,  # Get all chunks
                "sort": [
                    {
                        "create_time": {
                            "order": "asc",
                            "missing": "_last",  # Put documents without create_time at the end
                        }
                    }
                ],
            }

            chunks_response = vdb_core.search(index_name=index_name, query=chunks_query)
            chunks = [hit["_source"] for hit in chunks_response["hits"]["hits"]]

            # Build document object
            if chunks:
                doc_id = f"doc_{len(document_samples):04d}"
                document_samples[doc_id] = {
                    "doc_id": doc_id,
                    "path_or_url": path_or_url,
                    "filename": chunks[0].get("filename", "unknown"),
                    "chunk_count": chunk_count,
                    "chunks": chunks,
                    "file_size": chunks[0].get("file_size", 0),
                }

        logger.info(
            f"Successfully retrieved {len(document_samples)} documents with chunks"
        )
        return document_samples

    except Exception as e:
        logger.error(f"Error retrieving documents from ES: {str(e)}", exc_info=True)
        raise Exception(f"Failed to retrieve documents from Elasticsearch: {str(e)}")


def process_documents_for_clustering(
    index_name: str, vdb_core, sample_doc_count: int = 200
) -> Tuple[Dict[str, Dict], Dict[str, np.ndarray]]:
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
            chunks = doc_info["chunks"]
            doc_embedding = calculate_document_embedding(chunks, use_weighted=True)

            if doc_embedding is not None:
                doc_embeddings[doc_id] = doc_embedding
            else:
                logger.warning(f"Failed to calculate embedding for document {doc_id}")

        logger.info(
            f"Successfully calculated embeddings for {len(doc_embeddings)} documents"
        )
        return document_samples, doc_embeddings

    except Exception as e:
        logger.error(
            f"Error processing documents for clustering: {str(e)}", exc_info=True
        )
        raise Exception(f"Failed to process documents: {str(e)}")


def summarize_document(
    document_content: str,
    filename: str,
    language: str = LANGUAGE["ZH"],
    max_words: int = 100,
    model_id: Optional[int] = None,
    tenant_id: Optional[str] = None,
) -> str:
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
        prompt = compose_auxiliary_prompt(
            language,
            "document_summary",
            {
                "filename": filename,
                "content": document_content,
                "max_words": max_words,
            },
        )
        system_prompt, user_prompt = prompt.system, prompt.user

        logger.info(
            f"Document summary prompt generated for {filename} (max_words: {max_words})"
        )

        # Call LLM if model_id and tenant_id are provided
        if model_id and tenant_id:
            # Get model configuration
            llm_model_config = get_model_by_model_id(
                model_id=model_id, tenant_id=tenant_id
            )
            if not llm_model_config:
                logger.warning(
                    f"No model configuration found for model_id: {model_id}, tenant_id: {tenant_id}"
                )
                return f"[Document Summary: {filename}] (max {max_words} words) - Content: {document_content[:200]}..."

            document_summary = call_llm_for_system_prompt(
                model_id=model_id,
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                callback=None,
                tenant_id=tenant_id,
            )

            return (document_summary or "").strip()
        else:
            # Fallback to placeholder if no model configuration
            logger.warning(
                "No model_id or tenant_id provided, using placeholder summary"
            )
            return f"[Document Summary: {filename}] (max {max_words} words) - Content: {document_content[:200]}..."

    except Exception as e:
        logger.error(f"Error generating document summary: {str(e)}", exc_info=True)
        return f"Failed to generate summary for {filename}: {str(e)}"


def summarize_cluster(
    document_summaries: List[str],
    language: str = LANGUAGE["ZH"],
    max_words: int = 150,
    model_id: Optional[int] = None,
    tenant_id: Optional[str] = None,
) -> str:
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
        prompt = compose_document_cluster_summary(
            language, document_summaries, max_words
        )
        system_prompt, user_prompt = prompt.system, prompt.user

        logger.info(
            f"Cluster summary prompt generated (language: {language}, max_words: {max_words})"
        )

        # Call LLM if model_id and tenant_id are provided
        if model_id and tenant_id:
            # Get model configuration
            llm_model_config = get_model_by_model_id(
                model_id=model_id, tenant_id=tenant_id
            )
            if not llm_model_config:
                logger.warning(
                    f"No model configuration found for model_id: {model_id}, tenant_id: {tenant_id}"
                )
                return f"[Cluster Summary] (max {max_words} words) - Based on {len(document_summaries)} documents"

            # Create LLM instance
            cluster_summary = call_llm_for_system_prompt(
                model_id=model_id,
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                callback=None,
                tenant_id=tenant_id,
            )

            return (cluster_summary or "").strip()
        else:
            # Fallback to placeholder if no model configuration
            logger.warning(
                "No model_id or tenant_id provided, using placeholder summary"
            )
            return f"[Cluster Summary] (max {max_words} words) - Based on {len(document_summaries)} documents"

    except Exception as e:
        logger.error(f"Error generating cluster summary: {str(e)}", exc_info=True)
        return f"Failed to generate summary: {str(e)}"


def extract_representative_chunks_smart(
    chunks: List[Dict], max_chunks: int = 3
) -> List[Dict]:
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
            selected_chunks.append(chunks[len(chunks) // 2])
        if len(selected_chunks) < max_chunks and len(chunks) > 2:
            selected_chunks.append(chunks[-1])
        return selected_chunks[:max_chunks]

    chunk_scores = []
    for i, chunk in enumerate(chunks[1:-1]):  # Skip first and last
        content = chunk.get("content", "")
        if len(content) > 500:
            # Calculate keyword density (use first 500 chars for speed)
            keywords = calculate_term_weights(content[:500])
            score = (
                len(keywords) * 0.5 + len(content) * 0.001
            )  # Balance keyword count and length
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

    logger.info(
        f"Merged {len(cluster_summaries)} cluster summaries into final knowledge base summary"
    )
    return final_summary


def summarize_clusters_map_reduce(
    document_samples: Dict[str, Dict],
    clusters: Dict[int, List[str]],
    language: str = LANGUAGE["ZH"],
    doc_max_words: int = 100,
    cluster_max_words: int = 150,
    use_smart_chunk_selection: bool = True,
    enhance_with_metadata: bool = True,
    model_id: Optional[int] = None,
    tenant_id: Optional[str] = None,
) -> Dict[int, str]:
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
        logger.info(
            f"Summarizing cluster {cluster_id} with {len(doc_ids)} documents using Map-Reduce"
        )

        # Map stage: Summarize each document
        document_summaries = []
        for doc_id in doc_ids:
            if doc_id not in document_samples:
                continue

            doc_info = document_samples[doc_id]
            chunks = doc_info.get("chunks", [])
            filename = doc_info.get("filename", "unknown")

            # Extract representative content for this document
            if use_smart_chunk_selection:
                representative_chunks = extract_representative_chunks_smart(
                    chunks, max_chunks=3
                )
            else:
                # Simple approach: first, middle, last
                if len(chunks) <= 3:
                    representative_chunks = chunks
                else:
                    representative_chunks = (
                        chunks[:1]
                        + chunks[len(chunks) // 2 : len(chunks) // 2 + 1]
                        + chunks[-1:]
                    )

            # Format document content (merge top-K chunks)
            doc_content = ""
            for i, chunk in enumerate(representative_chunks):
                content = chunk.get("content", "")
                # Limit each chunk length for individual document
                if len(content) > 1000:
                    content = content[:1000] + "..."
                # Add chunk separator
                doc_content += f"[Chunk {i + 1}]\n{content}\n\n"

            # Generate document summary from merged chunks
            logger.info(
                f"Summarizing document {filename} with {len(representative_chunks)} representative chunks"
            )
            doc_summary = summarize_document(
                doc_content, filename, language, doc_max_words, model_id, tenant_id
            )
            document_summaries.append(doc_summary)

        # Reduce stage: Combine document summaries within this cluster into cluster summary
        if document_summaries:
            # Optionally enhance with cluster analysis
            if enhance_with_metadata:
                cluster_analysis = analyze_cluster_coherence(doc_ids, document_samples)
                logger.info(
                    f"Cluster {cluster_id} analysis: {cluster_analysis.get('doc_count', 0)} documents"
                )

            cluster_summary = summarize_cluster(
                document_summaries, language, cluster_max_words, model_id, tenant_id
            )
            cluster_summaries[cluster_id] = cluster_summary
        else:
            logger.warning(f"No valid documents found in cluster {cluster_id}")
            cluster_summaries[cluster_id] = "No content available for this cluster"

    return cluster_summaries
