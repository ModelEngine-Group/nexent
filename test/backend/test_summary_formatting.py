"""
Test summary formatting and display
"""

import pytest
import sys
import os
from unittest.mock import MagicMock, patch

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

# Add backend to path before patching backend modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
minio_client_mock = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('backend.database.client.MinioClient', return_value=minio_client_mock).start()

from utils.document_vector_utils import merge_cluster_summaries


class TestSummaryFormatting:
    """Test summary formatting functionality"""
    
    def test_merge_cluster_summaries_with_html_separators(self):
        """Test that cluster summaries are properly wrapped in HTML paragraph tags"""
        cluster_summaries = {
            0: "这是第一个簇的总结，包含关于机器学习和人工智能的内容。",
            1: "这是第二个簇的总结，包含关于深度学习和神经网络的内容。",
            2: "这是第三个簇的总结，包含关于自然语言处理的内容。"
        }
        
        result = merge_cluster_summaries(cluster_summaries)
        
        # Should contain HTML paragraph tags
        assert "<p>" in result
        assert "</p>" in result
        assert result.count("<p>") == 3  # Should have 3 paragraph tags for 3 clusters
        
        # Should contain all cluster summaries
        assert "第一个簇的总结" in result
        assert "第二个簇的总结" in result
        assert "第三个簇的总结" in result
        
        # Should be properly formatted with paragraph tags
        assert "<p>这是第一个簇的总结" in result
        assert "<p>这是第二个簇的总结" in result
        assert "<p>这是第三个簇的总结" in result
    
    def test_merge_cluster_summaries_single_cluster(self):
        """Test merging with single cluster (wrapped in paragraph tag)"""
        cluster_summaries = {
            0: "这是唯一的簇总结。"
        }
        
        result = merge_cluster_summaries(cluster_summaries)
        
        # Should be wrapped in paragraph tag
        assert "<p>" in result
        assert "</p>" in result
        assert result == "<p>这是唯一的簇总结。</p>"
    
    def test_merge_cluster_summaries_empty(self):
        """Test merging with empty input"""
        result = merge_cluster_summaries({})
        assert result == ""
    
    def test_merge_cluster_summaries_order(self):
        """Test that clusters are merged in correct order"""
        cluster_summaries = {
            2: "第三个簇",
            0: "第一个簇", 
            1: "第二个簇"
        }
        
        result = merge_cluster_summaries(cluster_summaries)
        
        # Should be in cluster ID order
        lines = result.split('\n')
        content_lines = [line for line in lines if line.strip() and '<p>' in line]
        
        assert "第一个簇" in content_lines[0]
        assert "第二个簇" in content_lines[1] 
        assert "第三个簇" in content_lines[2]
