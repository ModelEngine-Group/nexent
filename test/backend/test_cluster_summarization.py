"""
Test module for cluster summarization

Tests for cluster summarization functionality.
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
consts_const_mock.LANGUAGE = {"ZH": "zh", "EN": "en"}
consts_mock.const = consts_const_mock
sys.modules['consts'] = consts_mock
sys.modules['consts.const'] = consts_const_mock

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
patch('backend.database.client.MinioClient', return_value=minio_client_mock).start()

from backend.utils.document_vector_utils import (
    summarize_cluster,
    merge_cluster_summaries
)


class TestClusterSummarization:
    """Test cluster summarization functionality"""
    
    def test_summarize_cluster_placeholder(self):
        """Test cluster summarization (placeholder implementation)"""
        document_summaries = ["Summary 1", "Summary 2"]
        summary = summarize_cluster(document_summaries, language="zh", max_words=150)
        
        assert summary is not None
        assert isinstance(summary, str)
        assert 'Cluster Summary' in summary or 'Based on' in summary
    
    def test_merge_cluster_summaries(self):
        """Test merging cluster summaries"""
        cluster_summaries = {
            0: "Cluster 0 summary",
            1: "Cluster 1 summary",
            2: "Cluster 2 summary"
        }
        
        merged = merge_cluster_summaries(cluster_summaries)
        
        assert merged is not None
        assert isinstance(merged, str)
        assert "Cluster 0 summary" in merged
        assert "Cluster 1 summary" in merged
        assert "Cluster 2 summary" in merged
    
    def test_merge_cluster_summaries_empty(self):
        """Test merging empty cluster summaries"""
        cluster_summaries = {}
        merged = merge_cluster_summaries(cluster_summaries)
        
        assert merged == ""


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

