# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""
Test module for cluster summarization

Tests for cluster summarization functionality.
"""
from test.common.contract_stubs import install_shared_contract_stub
from test.common.contract_stubs import install_business_constant_stubs, install_business_contract_stubs
import os
import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# Mock consts module before patching management.db.client to avoid ImportError
# management.db.client imports from contracts.constants.environment, so we need to mock it first
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
sys.modules['contracts.constants.environment'] = consts_const_mock
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

from management.services.knowledge_base.summary import summarize_cluster, merge_cluster_summaries


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

