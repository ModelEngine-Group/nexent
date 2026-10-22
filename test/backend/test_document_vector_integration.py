# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""
Integration test for document vector operations.

This module validates the embedding and clustering workflow using deterministic
fixtures so the clustering assertions stay stable across environments.
"""
from test.common.contract_stubs import install_shared_contract_stub
from test.common.contract_stubs import install_business_constant_stubs, install_business_contract_stubs
import os
import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# Mock consts module before patching management.db.client to avoid ImportError
# management.db.client imports from consts.const, so we need to mock it first
consts_mock = MagicMock()
consts_const_mock = MagicMock()
# Set required constants that management.db.client might use
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
consts_const_mock.LANGUAGE = {"ZH": "zh", "EN": "en"}
consts_const_mock.MESSAGE_ROLE = {"USER": "user", "ASSISTANT": "assistant", "SYSTEM": "system"}
consts_const_mock.THINK_START_PATTERN = "<think>"
consts_const_mock.THINK_END_PATTERN = "</think>"
consts_mock.const = consts_const_mock
# Mock contracts.errors.codes and contracts.errors.exceptions
consts_error_code_mock = MagicMock()
consts_error_code_mock.ErrorCode = MagicMock()
consts_exceptions_mock = MagicMock()
consts_exceptions_mock.AppException = Exception
sys.modules['consts'] = consts_mock
sys.modules['consts.const'] = consts_const_mock
install_business_constant_stubs(consts_const_mock)
install_shared_contract_stub(consts_error_code_mock, 'error_code')
install_shared_contract_stub(consts_exceptions_mock, 'exceptions')
install_business_contract_stubs(consts_mock.model)

# Add backend to path before patching backend modules
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../backend"))
sys.path.insert(0, backend_dir)

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
minio_client_mock = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('management.db.client.MinioClient', return_value=minio_client_mock).start()

from management.services.knowledge_base.clustering import calculate_document_embedding, auto_determine_k, kmeans_cluster_documents


class TestDocumentVectorIntegration:
    """Integration tests for document vector operations."""

    def test_complete_workflow(self):
        """Test complete workflow: embedding calculation -> clustering."""
        chunks_1 = [
            {"embedding": [1.0, 0.0], "content": "Document one chunk A"},
            {"embedding": [0.9, 0.1], "content": "Document one chunk B"},
            {"embedding": [0.95, 0.05], "content": "Document one chunk C"},
        ]
        chunks_2 = [
            {"embedding": [0.0, 1.0], "content": "Document two chunk A"},
            {"embedding": [0.1, 0.9], "content": "Document two chunk B"},
        ]
        chunks_3 = [
            {"embedding": [0.85, 0.15], "content": "Document three chunk A"},
            {"embedding": [0.8, 0.2], "content": "Document three chunk B"},
            {"embedding": [0.88, 0.12], "content": "Document three chunk C"},
            {"embedding": [0.83, 0.17], "content": "Document three chunk D"},
        ]

        doc_embedding_1 = calculate_document_embedding(chunks_1, use_weighted=True)
        doc_embedding_2 = calculate_document_embedding(chunks_2, use_weighted=True)
        doc_embedding_3 = calculate_document_embedding(chunks_3, use_weighted=True)

        assert doc_embedding_1 is not None
        assert doc_embedding_2 is not None
        assert doc_embedding_3 is not None

        doc_embeddings = {
            "doc_001": doc_embedding_1,
            "doc_002": doc_embedding_2,
            "doc_003": doc_embedding_3,
        }

        embeddings_array = np.array([doc_embedding_1, doc_embedding_2, doc_embedding_3])
        optimal_k = auto_determine_k(embeddings_array, min_k=2, max_k=3)

        assert optimal_k == 2

        clusters = kmeans_cluster_documents(doc_embeddings, k=optimal_k)

        assert len(clusters) == optimal_k
        assert sum(len(docs) for docs in clusters.values()) == 3
        assert sorted(len(docs) for docs in clusters.values()) == [1, 2]

        cluster_sets = [set(docs) for docs in clusters.values()]
        assert {"doc_001", "doc_003"} in cluster_sets
        assert {"doc_002"} in cluster_sets

    def test_large_dataset_clustering(self):
        """Test clustering with a deterministic larger simulated dataset."""
        cluster_a = {
            f"doc_a_{i:03d}": np.array([1.0 + i * 0.002, 1.0 + i * 0.001, 0.2])
            for i in range(20)
        }
        cluster_b = {
            f"doc_b_{i:03d}": np.array([5.0 + i * 0.002, 5.0 + i * 0.001, 0.4])
            for i in range(15)
        }
        cluster_c = {
            f"doc_c_{i:03d}": np.array([9.0 + i * 0.002, 1.0 + i * 0.001, 0.6])
            for i in range(15)
        }
        doc_embeddings = {**cluster_a, **cluster_b, **cluster_c}
        n_docs = len(doc_embeddings)

        embeddings_array = np.array(list(doc_embeddings.values()))
        optimal_k = auto_determine_k(embeddings_array, min_k=3, max_k=6)

        assert 3 <= optimal_k <= 6

        clusters = kmeans_cluster_documents(doc_embeddings, k=3)

        assert len(clusters) == 3
        assert sum(len(docs) for docs in clusters.values()) == n_docs

        cluster_sizes = sorted(len(docs) for docs in clusters.values())
        assert cluster_sizes == [15, 15, 20]


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

