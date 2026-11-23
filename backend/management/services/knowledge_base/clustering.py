# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Knowledge document clustering."""

import logging
from typing import Dict, List, Optional

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)


def calculate_document_embedding(
    doc_chunks: List[Dict], use_weighted: bool = True
) -> Optional[np.ndarray]:
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
            chunk_embedding = chunk.get("embedding")
            if chunk_embedding and isinstance(chunk_embedding, list):
                embeddings.append(np.array(chunk_embedding))

                if use_weighted:
                    # Weight by content length only (removed position-based weight to reduce order dependency)
                    content_length = len(chunk.get("content", ""))
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
            doc_embedding = np.average(
                embeddings_array, axis=0, weights=weights_normalized
            )
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
        actual_max_k = min(
            max_k, n_samples // 10, 15
        )  # At least 10 samples per cluster
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
                score = silhouette_score(
                    embeddings, labels, sample_size=min(1000, n_samples)
                )

                logger.debug(f"K={k}, Silhouette Score={score:.4f}")

                if score > best_score:
                    best_score = score
                    best_k = k

            except Exception as e:
                logger.warning(f"Error calculating K={k}: {str(e)}")
                continue

        logger.info(
            f"Optimal K determined: {best_k} (Silhouette Score: {best_score:.4f})"
        )
        return best_k

    except Exception as e:
        logger.error(f"Error in auto_determine_k: {str(e)}", exc_info=True)
        # Fallback to heuristic
        heuristic_k = max(min_k, min(int(np.sqrt(len(embeddings) / 2)), max_k))
        logger.warning(f"Using fallback K value: {heuristic_k}")
        return heuristic_k


def merge_duplicate_documents_in_clusters(
    clusters: Dict[int, List[str]],
    doc_embeddings: Dict[str, np.ndarray],
    similarity_threshold: float = 0.98,
) -> Dict[int, List[str]]:
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

            for j, doc_id2 in enumerate(doc_ids_list[i + 1 :], start=i + 1):
                if doc_id2 not in doc_embeddings:
                    continue

                embedding2 = doc_embeddings[doc_id2]

                # Calculate cosine similarity
                similarity = cosine_similarity(
                    embedding1.reshape(1, -1), embedding2.reshape(1, -1)
                )[0][0]

                # If similarity is very high, they are likely duplicates
                if similarity >= similarity_threshold:
                    cluster1 = doc_to_cluster.get(doc_id1)
                    cluster2 = doc_to_cluster.get(doc_id2)

                    # Only merge if they are in different clusters AND truly duplicates
                    # Check both cosine similarity AND Euclidean distance to prevent false positives
                    if (
                        cluster1 is not None
                        and cluster2 is not None
                        and cluster1 != cluster2
                    ):
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
                        relative_distance_threshold = (
                            0.01 * avg_norm if avg_norm > 0 else 0.1
                        )

                        if euclidean_distance <= relative_distance_threshold:
                            merged_pairs.append(
                                (doc_id1, doc_id2, cluster1, cluster2, similarity)
                            )
                            logger.info(
                                f"Found duplicate documents: {doc_id1} and {doc_id2} (similarity: {similarity:.4f}, distance: {euclidean_distance:.4f}) in different clusters {cluster1} and {cluster2}"
                            )

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
                        if (
                            current_cluster is not None
                            and current_cluster != target_cluster
                        ):
                            # Move document to target cluster
                            if (
                                current_cluster in clusters
                                and doc_id in clusters[current_cluster]
                            ):
                                clusters[current_cluster].remove(doc_id)
                            if target_cluster not in clusters:
                                clusters[target_cluster] = []
                            if doc_id not in clusters[target_cluster]:
                                clusters[target_cluster].append(doc_id)
                            doc_to_cluster[doc_id] = target_cluster
                            logger.debug(
                                f"Moved {doc_id} from cluster {current_cluster} to cluster {target_cluster}"
                            )

            # Remove empty clusters
            empty_clusters = [cid for cid, docs in clusters.items() if not docs]
            for cid in empty_clusters:
                del clusters[cid]
                logger.debug(f"Removed empty cluster {cid}")

            logger.info(
                f"Successfully merged duplicate documents. Final cluster count: {len(clusters)}"
            )

        return clusters

    except Exception as e:
        logger.error(f"Error merging duplicate documents: {str(e)}", exc_info=True)
        # Return original clusters if merge fails
        return clusters


def kmeans_cluster_documents(
    doc_embeddings: Dict[str, np.ndarray], k: Optional[int] = None
) -> Dict[int, List[str]]:
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
        clusters = merge_duplicate_documents_in_clusters(
            clusters, doc_embeddings, similarity_threshold=0.98
        )

        # Log final cluster sizes after merge
        for cluster_id, docs in clusters.items():
            logger.info(f"Final cluster {cluster_id}: {len(docs)} documents")

        return clusters

    except Exception as e:
        logger.error(f"Error in K-means clustering: {str(e)}", exc_info=True)
        raise Exception(f"Failed to cluster documents: {str(e)}")


def analyze_cluster_coherence(
    cluster_doc_ids: List[str], document_samples: Dict[str, Dict]
) -> Dict[str, any]:
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
            filename = doc_info.get("filename", "unknown")
            chunks = doc_info.get("chunks", [])
            if chunks:
                first_chunk = chunks[0].get("content", "")[:200]
                doc_previews.append({"filename": filename, "preview": first_chunk})

    return {
        "doc_count": len(cluster_doc_ids),
        "doc_previews": doc_previews,
        "file_types": [
            doc["filename"].split(".")[-1]
            for doc in doc_previews
            if "." in doc["filename"]
        ],
    }
