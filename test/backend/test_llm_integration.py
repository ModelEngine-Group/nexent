# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""
Test LLM integration for knowledge base summarization
"""

import pytest
import sys
import os
import types
from unittest.mock import patch, MagicMock

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))

# Mock management.db.client and MinioClient before any imports to avoid MinIO initialization
class _MinioClient:
    pass

if "management.db.client" not in sys.modules:
    database_client_mod = types.ModuleType("management.db.client")
    database_client_mod.MinioClient = _MinioClient
    sys.modules["management.db.client"] = database_client_mod
    from test.common.database_stubs import install_serialization_stub
    install_serialization_stub(sys.modules["management.db.client"])
    from test.common.database_stubs import install_serialization_stub
    install_serialization_stub(sys.modules["management.db.client"])

# Mock management.db.client as well
if "management.db.client" not in sys.modules:
    backend_db_client_mod = types.ModuleType("management.db.client")
    backend_db_client_mod.MinioClient = _MinioClient
    sys.modules["management.db.client"] = backend_db_client_mod
    from test.common.database_stubs import install_serialization_stub
    install_serialization_stub(sys.modules["management.db.client"])

# Ensure database module exists as a package (needs __path__ attribute)
if "database" not in sys.modules:
    database_mod = types.ModuleType("database")
    database_mod.__path__ = []  # Make it a package
    sys.modules["database"] = database_mod

# Mock management.db.model.repository module to avoid MinIO initialization
if "management.db.model.repository" not in sys.modules:
    model_mgmt_db_mod = types.ModuleType("management.db.model.repository")
    model_mgmt_db_mod.get_model_by_model_id = MagicMock(return_value=None)
    sys.modules["management.db.model.repository"] = model_mgmt_db_mod
    setattr(sys.modules["database"], "model_management_db", model_mgmt_db_mod)

# Mock management.db.configuration.tenant to avoid import errors
if "management.db.configuration.tenant" not in sys.modules:
    tenant_config_db_mod = types.ModuleType("management.db.configuration.tenant")
    # Mock all functions that config_utils imports
    tenant_config_db_mod.delete_config_by_tenant_config_id = MagicMock()
    tenant_config_db_mod.get_all_configs_by_tenant_id = MagicMock()
    tenant_config_db_mod.get_single_config_info = MagicMock()
    tenant_config_db_mod.insert_config = MagicMock()
    tenant_config_db_mod.update_config_by_tenant_config_id_and_data = MagicMock()
    sys.modules["management.db.configuration.tenant"] = tenant_config_db_mod
    setattr(sys.modules["database"], "tenant_config_db", tenant_config_db_mod)

from management.services.knowledge_base.summary import summarize_document, summarize_cluster


class TestLLMIntegration:
    """Test LLM integration functionality"""
    
    def test_summarize_document_without_llm(self):
        """Test document summarization without LLM (fallback mode)"""
        content = "This is a test document with some content about machine learning and AI."
        filename = "test_doc.txt"
        
        result = summarize_document(content, filename, language="zh", max_words=50)
        
        # Should return placeholder when no model_id/tenant_id provided
        assert "[Document Summary: test_doc.txt]" in result
        assert "max 50 words" in result
        assert "Content:" in result
    
    def test_summarize_document_with_llm_params_no_config(self):
        """Test document summarization with LLM parameters but no model config"""
        content = "This is a test document with some content about machine learning and AI."
        filename = "test_doc.txt"
        
        # Mock get_model_by_model_id to return None (no config found)
        # Use the already mocked module and just ensure it returns None
        from management.db.model import repository as model_mgmt_db
        model_mgmt_db.get_model_by_model_id = MagicMock(return_value=None)
        
        # Test with model_id and tenant_id but no actual LLM call (will fallback due to missing config)
        result = summarize_document(
            content, filename, language="zh", max_words=50, 
            model_id=1, tenant_id="test_tenant"
        )
        
        # Should return placeholder summary when model config not found (fallback behavior)
        assert "[Document Summary: test_doc.txt]" in result
        assert "max 50 words" in result
        assert "Content:" in result
    
    def test_summarize_cluster_without_llm(self):
        """Test cluster summarization without LLM (fallback mode)"""
        document_summaries = [
            "Document 1 is about machine learning algorithms.",
            "Document 2 discusses neural networks and deep learning.",
            "Document 3 covers AI applications in healthcare."
        ]
        
        result = summarize_cluster(document_summaries, language="zh", max_words=100)
        
        # Should return placeholder when no model_id/tenant_id provided
        assert "[Cluster Summary]" in result
        assert "max 100 words" in result
        assert "Based on 3 documents" in result
    
    def test_summarize_cluster_with_llm_params_no_config(self):
        """Test cluster summarization with LLM parameters but no model config"""
        document_summaries = [
            "Document 1 is about machine learning algorithms.",
            "Document 2 discusses neural networks and deep learning."
        ]
        
        # Mock get_model_by_model_id to return None (no config found)
        # Use the already mocked module and just ensure it returns None
        from management.db.model import repository as model_mgmt_db
        model_mgmt_db.get_model_by_model_id = MagicMock(return_value=None)
        
        result = summarize_cluster(
            document_summaries, language="zh", max_words=100,
            model_id=1, tenant_id="test_tenant"
        )
        
        # Should return placeholder summary when model config not found (fallback behavior)
        assert "[Cluster Summary]" in result
        assert "max 100 words" in result
        assert "Based on 2 documents" in result
    
    def test_summarize_document_english(self):
        """Test document summarization in English"""
        content = "This is a test document with some content about machine learning and AI."
        filename = "test_doc.txt"
        
        result = summarize_document(content, filename, language="en", max_words=50)
        
        # Should return placeholder when no model_id/tenant_id provided
        assert "[Document Summary: test_doc.txt]" in result
        assert "max 50 words" in result
        assert "Content:" in result
    
    def test_summarize_cluster_english(self):
        """Test cluster summarization in English"""
        document_summaries = [
            "Document 1 is about machine learning algorithms.",
            "Document 2 discusses neural networks and deep learning."
        ]
        
        result = summarize_cluster(document_summaries, language="en", max_words=100)
        
        # Should return placeholder when no model_id/tenant_id provided
        assert "[Cluster Summary]" in result
        assert "max 100 words" in result
        assert "Based on 2 documents" in result
