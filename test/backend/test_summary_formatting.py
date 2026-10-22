# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""
Test summary formatting and display
"""

from test.common.contract_stubs import install_shared_contract_stub
from test.common.contract_stubs import install_business_constant_stubs, install_business_contract_stubs
import pytest
import sys
import os
from unittest.mock import MagicMock, patch

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
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))

# Patch storage factory and MinIO config validation to avoid errors during initialization
# These patches must be started before any imports that use MinioClient
storage_client_mock = MagicMock()
minio_client_mock = MagicMock()
patch('nexent.storage.storage_client_factory.create_storage_client_from_config', return_value=storage_client_mock).start()
patch('nexent.storage.minio_config.MinIOStorageConfig.validate', lambda self: None).start()
patch('management.db.client.MinioClient', return_value=minio_client_mock).start()

from management.services.knowledge_base.summary import merge_cluster_summaries


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
