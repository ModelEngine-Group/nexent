"""
Pytest fixtures for quota service tests.
"""

import pytest
from unittest.mock import MagicMock, patch
import sys
import os

# Ensure backend is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def mock_tenant_config_db():
    """Mock tenant_config_db module functions."""
    with patch("services.quota_service.get_single_config_info") as mock_get, \
         patch("services.quota_service.insert_config") as mock_insert, \
         patch("services.quota_service.update_config_by_tenant_config_id") as mock_update, \
         patch("services.quota_service.delete_config_by_tenant_config_id") as mock_delete:
        yield {
            "get_single_config_info": mock_get,
            "insert_config": mock_insert,
            "update_config_by_tenant_config_id": mock_update,
            "delete_config_by_tenant_config_id": mock_delete,
        }


@pytest.fixture
def mock_knowledge_db():
    """Mock knowledge_db module functions."""
    with patch("services.quota_service.get_knowledge_info_by_tenant_id") as mock_list, \
         patch("services.quota_service.update_knowledge_record") as mock_update:
        yield {
            "get_knowledge_info_by_tenant_id": mock_list,
            "update_knowledge_record": mock_update,
        }


@pytest.fixture
def quota_service():
    """Create a QuotaService instance for testing."""
    from services.quota_service import QuotaService
    return QuotaService("test-tenant-id", "test-user-id")


@pytest.fixture
def sample_kb_list():
    """Sample knowledge base records for testing."""
    return [
        {
            "knowledge_id": 1,
            "index_name": "kb-1-abc123",
            "knowledge_name": "Research Docs",
            "quota_limit_bytes": 30 * 1024 * 1024 * 1024,  # 30 GB
        },
        {
            "knowledge_id": 2,
            "index_name": "kb-2-def456",
            "knowledge_name": "Sales Docs",
            "quota_limit_bytes": None,  # no quota
        },
        {
            "knowledge_id": 3,
            "index_name": "kb-3-ghi789",
            "knowledge_name": "Ops Docs",
            "quota_limit_bytes": 10 * 1024 * 1024 * 1024,  # 10 GB
        },
    ]


@pytest.fixture
def mock_db_session():
    """Mock database session for KnowledgeRecord queries."""
    with patch("services.quota_service.get_db_session") as mock:
        yield mock


@pytest.fixture
def mock_attachment_list():
    """Mock attachment list_files for usage computation."""
    with patch("services.quota_service.list_files") as mock:
        yield mock
