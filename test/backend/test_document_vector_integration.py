"""
Integration test for document vector operations

This test demonstrates the complete workflow from ES retrieval to clustering.
Note: This requires a running Elasticsearch instance.
"""
import os
import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# Add backend to path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../backend"))
sys.path.insert(0, backend_dir)

from backend.utils.document_vector_utils import (
    calculate_document_embedding,
    auto_determine_k,
    kmeans_cluster_documents
)


class TestDocumentVectorIntegration:
    """Integration tests for document vector operations"""
    
    def test_complete_workflow(self):
        """Test complete workflow: embedding calculation -> clustering"""
        # Simulate document chunks with embeddings
        chunks_1 = [
            {'embedding': np.random.rand(128).tolist(), 'content': 'Content for doc 1 chunk 1'},
            {'embedding': np.random.rand(128).tolist(), 'content': 'Content for doc 1 chunk 2'},
            {'embedding': np.random.rand(128).tolist(), 'content': 'Content for doc 1 chunk 3'}
        ]
        
        chunks_2 = [
            {'embedding': np.random.rand(128).tolist(), 'content': 'Content for doc 2 chunk 1'},
            {'embedding': np.random.rand(128).tolist(), 'content': 'Content for doc 2 chunk 2'}
        ]
        
        chunks_3 = [
            {'embedding': np.random.rand(128).tolist(), 'content': 'Content for doc 3 chunk 1'},
            {'embedding': np.random.rand(128).tolist(), 'content': 'Content for doc 3 chunk 2'},
            {'embedding': np.random.rand(128).tolist(), 'content': 'Content for doc 3 chunk 3'},
            {'embedding': np.random.rand(128).tolist(), 'content': 'Content for doc 3 chunk 4'}
        ]
        
        # Calculate document embeddings
        doc_embedding_1 = calculate_document_embedding(chunks_1, use_weighted=True)
        doc_embedding_2 = calculate_document_embedding(chunks_2, use_weighted=True)
        doc_embedding_3 = calculate_document_embedding(chunks_3, use_weighted=True)
        
        assert doc_embedding_1 is not None
        assert doc_embedding_2 is not None
        assert doc_embedding_3 is not None
        
        # Create document embeddings dictionary
        doc_embeddings = {
            'doc_001': doc_embedding_1,
            'doc_002': doc_embedding_2,
            'doc_003': doc_embedding_3
        }
        
        # Determine optimal K
        embeddings_array = np.array([doc_embedding_1, doc_embedding_2, doc_embedding_3])
        optimal_k = auto_determine_k(embeddings_array, min_k=2, max_k=3)
        
        assert 2 <= optimal_k <= 3
        
        # Perform clustering
        clusters = kmeans_cluster_documents(doc_embeddings, k=optimal_k)
        
        assert len(clusters) == optimal_k
        assert sum(len(docs) for docs in clusters.values()) == 3
    
    def test_large_dataset_clustering(self):
        """Test clustering with larger simulated dataset"""
        # Create simulated document embeddings
        n_docs = 50
        doc_embeddings = {
            f'doc_{i:03d}': np.random.rand(128) for i in range(n_docs)
        }
        
        # Auto-determine K
        embeddings_array = np.array(list(doc_embeddings.values()))
        optimal_k = auto_determine_k(embeddings_array, min_k=3, max_k=15)
        
        assert 3 <= optimal_k <= 15
        
        # Cluster documents
        clusters = kmeans_cluster_documents(doc_embeddings, k=optimal_k)
        
        assert len(clusters) == optimal_k
        assert sum(len(docs) for docs in clusters.values()) == n_docs
        
        # Verify cluster sizes are reasonable
        cluster_sizes = [len(docs) for docs in clusters.values()]
        assert min(cluster_sizes) >= 1
        # Allow for some imbalance in clustering results (realistic for random data)
        assert max(cluster_sizes) <= n_docs * 0.7  # No single cluster dominates too much


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

