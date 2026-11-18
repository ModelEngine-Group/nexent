# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Knowledge document summary."""

import logging
from typing import Dict, List, Optional

from contracts.agentos_knowledge import KnowledgeSampleResult
from contracts.constants.constants import LANGUAGE
from contracts.errors.exceptions import RuntimeUpstreamError
from management.clients.model import invoke_chat_prompt_in_worker
from management.services.knowledge_base.clustering import (
    analyze_cluster_coherence,
    calculate_document_embedding,
)
from nexent.core.agents.prompt.auxiliary import compose_auxiliary_prompt
from nexent.core.agents.prompt.document import compose_document_cluster_summary

logger = logging.getLogger(__name__)


def document_embeddings(document_samples):
    """Use the established content-length weighted document representation."""
    embeddings = {}
    for doc_id, doc_info in document_samples.items():
        embedding = calculate_document_embedding(doc_info['chunks'], use_weighted=True)
        if embedding is not None:
            embeddings[doc_id] = embedding
        else:
            logger.warning('Failed to calculate embedding for document %s', doc_id)
    return embeddings


def sample_documents_for_clustering(sample: KnowledgeSampleResult):
    """Adapt published neutral samples to the existing Management MapReduce inputs."""
    documents = {}
    for document in sample.documents:
        if not document.chunks:
            continue
        doc_id = f'doc_{len(documents):04d}'
        documents[doc_id] = {'doc_id': doc_id, 'path_or_url': document.file_ref.file_id,
            'filename': document.filename or 'unknown', 'chunk_count': len(document.chunks), 'file_size': 0,
            'chunks': [chunk.model_dump() for chunk in document.chunks]}
    return documents, document_embeddings(documents)


def summarize_document(
    document_content: str,
    filename: str,
    language: str = LANGUAGE["ZH"],
    max_words: int = 100,
    model_id: Optional[int] = None,
    tenant_id: Optional[str] = None,
    *,
    user_id: Optional[str] = None,
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
        user_id: Authenticated caller or scheduled job actor

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

        fallback = f"[Document Summary: {filename}] (max {max_words} words) - Content: {document_content[:200]}..."
        if not (model_id and tenant_id and user_id):
            return fallback
        try:
            content = invoke_chat_prompt_in_worker(
                model_id=model_id,
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                user_id=user_id,
                tenant_id=tenant_id,
            )
            return (content or "").strip()
        except RuntimeUpstreamError as exc:
            if exc.status_code == 404:
                return fallback
            raise

    except Exception as e:
        logger.error(f"Error generating document summary: {str(e)}", exc_info=True)
        return f"Failed to generate summary for {filename}: {str(e)}"


def summarize_cluster(
    document_summaries: List[str],
    language: str = LANGUAGE["ZH"],
    max_words: int = 150,
    model_id: Optional[int] = None,
    tenant_id: Optional[str] = None,
    *,
    user_id: Optional[str] = None,
) -> str:
    """
    Summarize a cluster of documents using LLM (Reduce stage)

    Args:
        document_summaries: List of individual document summaries
        language: Language code ('zh' or 'en')
        max_words: Maximum words in the summary
        model_id: Model ID for LLM call
        tenant_id: Tenant ID for model configuration
        user_id: Authenticated caller or scheduled job actor

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

        fallback = f"[Cluster Summary] (max {max_words} words) - Based on {len(document_summaries)} documents"
        if not (model_id and tenant_id and user_id):
            return fallback
        try:
            content = invoke_chat_prompt_in_worker(
                model_id=model_id,
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                user_id=user_id,
                tenant_id=tenant_id,
            )
            return (content or "").strip()
        except RuntimeUpstreamError as exc:
            if exc.status_code == 404:
                return fallback
            raise

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
    *,
    user_id: Optional[str] = None,
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
                doc_content, filename, language, doc_max_words, model_id, tenant_id, user_id=user_id
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
                document_summaries, language, cluster_max_words, model_id, tenant_id, user_id=user_id
            )
            cluster_summaries[cluster_id] = cluster_summary
        else:
            logger.warning(f"No valid documents found in cluster {cluster_id}")
            cluster_summaries[cluster_id] = "No content available for this cluster"

    return cluster_summaries
