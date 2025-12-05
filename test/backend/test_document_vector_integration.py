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

# Mock consts module before patching backend.database.client to avoid ImportError
# backend.database.client imports from consts.const, so we need to mock it first
consts_mock = MagicMock()
consts_const_mock = MagicMock()
# Set required constants that backend.database.client might use
consts_const_mock.MINIO_ENDPOINT = "http://localhost:9000"
consts_const_mock.MINIO_ACCESS_KEY = "test_access_key"
consts_const_mock.MINIO_SECRET_KEY = "test_secret_key"
consts_const_mock.MINIO_REGION = "us-east-1"
consts_const_mock.MINIO_DEFAULT_BUCKET = "test-bucket"
consts_const_mock.POSTGRES_HOST = "localhost"
consts_const_mock.POSTGRES_USER = "test_user"
consts_const_mock.NEXENT_POSTGRES_PASSWORD = "test_password"
consts_const_mock.POSTGRES_DB = "test_db"
consts_const_mock.POSTGRES_PORT = 5432
consts_mock.const = consts_const_mock
sys.modules['consts'] = consts_mock
sys.modules['consts.const'] = consts_const_mock

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
minio_client_mock = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_client_mock).start()

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

