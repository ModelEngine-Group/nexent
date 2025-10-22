"""
Test module for document_vector_utils

Tests for document-level vector operations and clustering functionality.
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


class TestDocumentEmbedding:
    """Test document embedding calculation"""
    
    def test_calculate_document_embedding_simple_average(self):
        """Test simple average embedding calculation"""
        chunks = [
            {'embedding': [1.0, 2.0, 3.0], 'content': 'Content 1'},
            {'embedding': [4.0, 5.0, 6.0], 'content': 'Content 2'},
            {'embedding': [7.0, 8.0, 9.0], 'content': 'Content 3'}
        ]
        
        result = calculate_document_embedding(chunks, use_weighted=False)
        
        assert result is not None
        assert np.allclose(result, [4.0, 5.0, 6.0])  # Average of all embeddings
    
    def test_calculate_document_embedding_weighted(self):
        """Test weighted average embedding calculation"""
        chunks = [
            {'embedding': [1.0, 2.0], 'content': 'Short'},
            {'embedding': [3.0, 4.0], 'content': 'Long content with more words'},
            {'embedding': [5.0, 6.0], 'content': 'Medium length content'}
        ]
        
        result = calculate_document_embedding(chunks, use_weighted=True)
        
        assert result is not None
        assert len(result) == 2
    
    def test_calculate_document_embedding_empty_chunks(self):
        """Test handling of empty chunks"""
        chunks = []
        result = calculate_document_embedding(chunks)
        assert result is None
    
    def test_calculate_document_embedding_no_embeddings(self):
        """Test handling of chunks without embeddings"""
        chunks = [
            {'content': 'Content 1'},
            {'content': 'Content 2'}
        ]
        result = calculate_document_embedding(chunks)
        assert result is None


class TestAutoDetermineK:
    """Test automatic K determination"""
    
    def test_auto_determine_k_small_dataset(self):
        """Test K determination for small dataset"""
        embeddings = np.random.rand(10, 128)
        k = auto_determine_k(embeddings, min_k=3, max_k=15)
        
        assert 3 <= k <= 15
    
    def test_auto_determine_k_large_dataset(self):
        """Test K determination for large dataset"""
        embeddings = np.random.rand(200, 128)
        k = auto_determine_k(embeddings, min_k=3, max_k=15)
        
        assert 3 <= k <= 15
    
    def test_auto_determine_k_very_small_dataset(self):
        """Test K determination for very small dataset"""
        embeddings = np.random.rand(5, 128)
        k = auto_determine_k(embeddings, min_k=3, max_k=15)
        
        assert k >= 2
        assert k <= 5
    
    def test_auto_determine_k_minimum(self):
        """Test K determination respects minimum"""
        embeddings = np.random.rand(100, 128)
        k = auto_determine_k(embeddings, min_k=5, max_k=15)
        
        assert k >= 5


class TestKMeansClustering:
    """Test K-means clustering"""
    
    def test_kmeans_cluster_documents(self):
        """Test basic K-means clustering"""
        doc_embeddings = {
            'doc1': np.array([1.0, 1.0]),
            'doc2': np.array([1.1, 1.1]),
            'doc3': np.array([5.0, 5.0]),
            'doc4': np.array([5.1, 5.1]),
            'doc5': np.array([9.0, 9.0]),
            'doc6': np.array([9.1, 9.1])
        }
        
        clusters = kmeans_cluster_documents(doc_embeddings, k=3)
        
        assert len(clusters) == 3
        assert sum(len(docs) for docs in clusters.values()) == 6
    
    def test_kmeans_cluster_documents_auto_k(self):
        """Test K-means clustering with auto-determined K"""
        doc_embeddings = {
            f'doc{i}': np.random.rand(128) for i in range(50)
        }
        
        clusters = kmeans_cluster_documents(doc_embeddings, k=None)
        
        assert len(clusters) > 0
        assert sum(len(docs) for docs in clusters.values()) == 50
    
    def test_kmeans_cluster_documents_empty(self):
        """Test handling of empty embeddings"""
        doc_embeddings = {}
        clusters = kmeans_cluster_documents(doc_embeddings)
        
        assert clusters == {}


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

