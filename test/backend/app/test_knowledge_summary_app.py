"""
Unit tests for knowledge_summary_app module.

These tests focus on testing the app layer endpoints with services mocked.
All module mocks are provided by conftest.py.
"""
import asyncio
import sys
import os
import types
import importlib.machinery
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

# Apply patches that need to be active before imports
from unittest.mock import patch as mock_patch

# Mock external dependencies
boto3_module = types.ModuleType("boto3")
boto3_module.client = MagicMock()
boto3_module.resource = MagicMock()
boto3_module.__spec__ = importlib.machinery.ModuleSpec("boto3", loader=None)
sys.modules['boto3'] = boto3_module
sys.modules['botocore'] = MagicMock()
sys.modules['botocore.client'] = MagicMock()
sys.modules['botocore.exceptions'] = MagicMock()
sys.modules['nexent'] = MagicMock()
nexent_core = types.ModuleType('nexent.core')
sys.modules['nexent.core'] = nexent_core
nexent_core_agents = types.ModuleType('nexent.core.agents')
sys.modules['nexent.core.agents'] = nexent_core_agents


nexent_core_agents_agent_model = types.ModuleType('nexent.core.agents.agent_model')


class MockToolConfig:
    pass


nexent_core_agents_agent_model.ToolConfig = MockToolConfig
sys.modules['nexent.core.agents.agent_model'] = nexent_core_agents_agent_model
nexent_nexent_vector_database = types.ModuleType('nexent.vector_database')
sys.modules['nexent.vector_database'] = nexent_nexent_vector_database
nexent_nexent_vector_database = types.ModuleType('nexent.vector_database.base')


class MockVectorDatabaseCore:
    pass


nexent_nexent_vector_database.VectorDatabaseCore = MockVectorDatabaseCore
sys.modules['nexent.vector_database.base'] = nexent_nexent_vector_database
# Create mock for vectordatabase_service BEFORE importing the app
vectordatabase_service_mock = types.ModuleType('services.vectordatabase_service')


class MockElasticSearchService:
    def __init__(self, *args, **kwargs):
        pass


def mock_get_vector_db_core():
    return MagicMock()


vectordatabase_service_mock.ElasticSearchService = MockElasticSearchService
vectordatabase_service_mock.get_vector_db_core = mock_get_vector_db_core
sys.modules['services.vectordatabase_service'] = vectordatabase_service_mock

# Mock other services that might be imported
sys.modules['services.redis_service'] = types.ModuleType('services.redis_service')
sys.modules['services.group_service'] = types.ModuleType('services.group_service')

# Mock utils modules used by knowledge_summary_app to avoid deep DB/storage import chains
utils_auth_utils_mock = types.ModuleType('utils.auth_utils')
utils_auth_utils_mock.get_current_user_id = MagicMock(return_value=("test_user_id", "test_tenant_id"))
utils_auth_utils_mock.get_current_user_info = MagicMock(return_value=("test_user_id", "test_tenant_id", "en"))
sys.modules['utils.auth_utils'] = utils_auth_utils_mock

utils_config_utils_mock = types.ModuleType('utils.config_utils')
mock_tenant_config_manager = MagicMock()
mock_tenant_config = MagicMock()
mock_tenant_config.get.return_value = None
mock_tenant_config_manager.load_config.return_value = mock_tenant_config
utils_config_utils_mock.tenant_config_manager = mock_tenant_config_manager
sys.modules['utils.config_utils'] = utils_config_utils_mock

# Import the modules we need
from fastapi.testclient import TestClient
from fastapi import FastAPI
from pydantic import BaseModel
from apps.knowledge_summary_app import router

# Create a test app and client
app = FastAPI()
app.include_router(router)
client = TestClient(app)


# Fixture for test setup
@pytest.fixture
def test_data():
    data = {
        "index_name": "test_index",
        "user_id": ("test_user_id", "test_tenant_id"),
        "user_info": ("test_user_id", "test_tenant_id", "en"),
        "summary_result": "This is a test summary for the knowledge base",
        "auth_header": {"Authorization": "Bearer test_token"}
    }
    return data


class TestAutoSummary:
    """Test auto summary generation endpoint"""

    @patch('apps.knowledge_summary_app.ElasticSearchService')
    @patch('apps.knowledge_summary_app.get_vector_db_core')
    @patch('apps.knowledge_summary_app.get_current_user_info')
    def test_auto_summary_success(self, mock_user_info, mock_vdb_core, mock_service_class, test_data):
        """Test successful auto summary generation"""
        mock_vdb_core_instance = MagicMock()
        mock_vdb_core.return_value = mock_vdb_core_instance

        mock_user_info_value = ("test_user_id", "test_tenant_id", "en")
        mock_user_info.return_value = mock_user_info_value

        mock_service_instance = MagicMock()
        mock_service_instance.summary_index_name = AsyncMock(return_value=MagicMock())
        mock_service_class.return_value = mock_service_instance

        response = client.post(
            f"/summary/{test_data['index_name']}/auto_summary?batch_size=500&model_id=1",
            headers=test_data["auth_header"]
        )

        assert response.status_code == 200
        assert mock_service_instance.summary_index_name.call_count == 1

        call_kwargs = mock_service_instance.summary_index_name.call_args.kwargs
        assert call_kwargs['index_name'] == test_data['index_name']
        assert call_kwargs['batch_size'] == 500
        assert call_kwargs['tenant_id'] == mock_user_info_value[1]
        assert call_kwargs['language'] == mock_user_info_value[2]
        assert call_kwargs['model_id'] == 1

    @patch('apps.knowledge_summary_app.ElasticSearchService')
    @patch('apps.knowledge_summary_app.get_vector_db_core')
    @patch('apps.knowledge_summary_app.get_current_user_info')
    def test_auto_summary_without_model_id(self, mock_user_info, mock_vdb_core, mock_service_class, test_data):
        """Test successful auto summary generation without model_id parameter"""
        mock_vdb_core_instance = MagicMock()
        mock_vdb_core.return_value = mock_vdb_core_instance

        mock_user_info_value = ("test_user_id", "test_tenant_id", "en")
        mock_user_info.return_value = mock_user_info_value

        mock_service_instance = MagicMock()
        mock_service_instance.summary_index_name = AsyncMock(return_value=MagicMock())
        mock_service_class.return_value = mock_service_instance

        response = client.post(
            f"/summary/{test_data['index_name']}/auto_summary?batch_size=500",
            headers=test_data["auth_header"]
        )

        assert response.status_code == 200
        assert mock_service_instance.summary_index_name.call_count == 1

        call_kwargs = mock_service_instance.summary_index_name.call_args.kwargs
        assert call_kwargs['index_name'] == test_data['index_name']
        assert call_kwargs['batch_size'] == 500
        assert call_kwargs['model_id'] is None

    @patch('apps.knowledge_summary_app.ElasticSearchService')
    @patch('apps.knowledge_summary_app.get_vector_db_core')
    @patch('apps.knowledge_summary_app.get_current_user_info')
    def test_auto_summary_exception(self, mock_user_info, mock_vdb_core, mock_service_class, test_data):
        """Test auto summary generation with exception"""
        mock_vdb_core_instance = MagicMock()
        mock_vdb_core.return_value = mock_vdb_core_instance

        mock_user_info_value = ("test_user_id", "test_tenant_id", "en")
        mock_user_info.return_value = mock_user_info_value

        mock_service_instance = MagicMock()
        mock_service_instance.summary_index_name = AsyncMock(
            side_effect=Exception("Error generating summary")
        )
        mock_service_class.return_value = mock_service_instance

        response = client.post(
            f"/summary/{test_data['index_name']}/auto_summary",
            headers=test_data["auth_header"]
        )

        assert response.status_code == 500
        assert "text/event-stream" in response.headers["content-type"]
        assert "Knowledge base summary generation failed" in response.text

    @patch('apps.knowledge_summary_app.ElasticSearchService')
    @patch('apps.knowledge_summary_app.get_vector_db_core')
    @patch('apps.knowledge_summary_app.get_current_user_info')
    @patch('apps.knowledge_summary_app.tenant_config_manager')
    def test_auto_summary_uses_tenant_llm_id(
        self, mock_config_manager, mock_user_info, mock_vdb_core, mock_service_class, test_data
    ):
        """Test that auto summary uses LLM_ID from tenant config when model_id is not provided"""
        mock_vdb_core_instance = MagicMock()
        mock_vdb_core.return_value = mock_vdb_core_instance

        mock_user_info_value = ("test_user_id", "test_tenant_id", "en")
        mock_user_info.return_value = mock_user_info_value

        mock_config = MagicMock()
        mock_config.get.return_value = "5"
        mock_config_manager.load_config.return_value = mock_config

        mock_service_instance = MagicMock()
        mock_service_instance.summary_index_name = AsyncMock(return_value=MagicMock())
        mock_service_class.return_value = mock_service_instance

        response = client.post(
            f"/summary/{test_data['index_name']}/auto_summary?batch_size=100",
            headers=test_data["auth_header"]
        )

        assert response.status_code == 200
        mock_config_manager.load_config.assert_called_once_with("test_tenant_id")

        call_kwargs = mock_service_instance.summary_index_name.call_args.kwargs
        assert call_kwargs['model_id'] == 5

    @patch('apps.knowledge_summary_app.ElasticSearchService')
    @patch('apps.knowledge_summary_app.get_vector_db_core')
    @patch('apps.knowledge_summary_app.get_current_user_info')
    @patch('apps.knowledge_summary_app.tenant_config_manager')
    def test_auto_summary_tenant_config_no_llm_id(
        self, mock_config_manager, mock_user_info, mock_vdb_core, mock_service_class, test_data
    ):
        """Test auto summary when tenant config has no LLM_ID"""
        mock_vdb_core_instance = MagicMock()
        mock_vdb_core.return_value = mock_vdb_core_instance

        mock_user_info_value = ("test_user_id", "test_tenant_id", "en")
        mock_user_info.return_value = mock_user_info_value

        mock_config = MagicMock()
        mock_config.get.return_value = None
        mock_config_manager.load_config.return_value = mock_config

        mock_service_instance = MagicMock()
        mock_service_instance.summary_index_name = AsyncMock(return_value=MagicMock())
        mock_service_class.return_value = mock_service_instance

        response = client.post(
            f"/summary/{test_data['index_name']}/auto_summary",
            headers=test_data["auth_header"]
        )

        assert response.status_code == 200
        call_kwargs = mock_service_instance.summary_index_name.call_args.kwargs
        assert call_kwargs['model_id'] is None

    @patch('apps.knowledge_summary_app.ElasticSearchService')
    @patch('apps.knowledge_summary_app.get_vector_db_core')
    @patch('apps.knowledge_summary_app.get_current_user_info')
    @patch('apps.knowledge_summary_app.tenant_config_manager')
    def test_auto_summary_tenant_config_exception(
        self, mock_config_manager, mock_user_info, mock_vdb_core, mock_service_class, test_data
    ):
        """Test auto summary when loading tenant config raises exception"""
        mock_vdb_core_instance = MagicMock()
        mock_vdb_core.return_value = mock_vdb_core_instance

        mock_user_info_value = ("test_user_id", "test_tenant_id", "en")
        mock_user_info.return_value = mock_user_info_value

        mock_config_manager.load_config.side_effect = Exception("Config error")

        mock_service_instance = MagicMock()
        mock_service_instance.summary_index_name = AsyncMock(return_value=MagicMock())
        mock_service_class.return_value = mock_service_instance

        response = client.post(
            f"/summary/{test_data['index_name']}/auto_summary",
            headers=test_data["auth_header"]
        )

        assert response.status_code == 200
        call_kwargs = mock_service_instance.summary_index_name.call_args.kwargs
        assert call_kwargs['model_id'] is None


class TestChangeSummary:
    """Test change summary endpoint"""

    @patch('apps.knowledge_summary_app.ElasticSearchService')
    @patch('apps.knowledge_summary_app.get_current_user_id')
    def test_change_summary_success(self, mock_get_user_id, mock_service_class, test_data):
        """Test successful summary update"""
        mock_get_user_id.return_value = test_data["user_id"]

        expected_response = {
            "success": True,
            "index_name": test_data["index_name"],
            "summary": test_data["summary_result"]
        }

        mock_service_instance = MagicMock()
        mock_service_instance.change_summary.return_value = expected_response
        mock_service_class.return_value = mock_service_instance

        request_data = {"summary_result": test_data["summary_result"]}
        response = client.post(
            f"/summary/{test_data['index_name']}/summary",
            json=request_data,
            headers=test_data["auth_header"]
        )

        assert response.status_code == 200
        response_json = response.json()
        assert response_json["success"] is True
        assert response_json["index_name"] == test_data["index_name"]
        assert response_json["summary"] == test_data["summary_result"]

        mock_service_instance.change_summary.assert_called_once_with(
            index_name=test_data["index_name"],
            summary_result=test_data["summary_result"],
            user_id=test_data["user_id"][0]
        )

    @patch('apps.knowledge_summary_app.ElasticSearchService')
    @patch('apps.knowledge_summary_app.get_current_user_id')
    def test_change_summary_exception(self, mock_get_user_id, mock_service_class, test_data):
        """Test summary update with exception"""
        mock_get_user_id.return_value = test_data["user_id"]

        mock_service_instance = MagicMock()
        mock_service_instance.change_summary.side_effect = Exception("Error updating summary")
        mock_service_class.return_value = mock_service_instance

        request_data = {"summary_result": test_data["summary_result"]}
        response = client.post(
            f"/summary/{test_data['index_name']}/summary",
            json=request_data,
            headers=test_data["auth_header"]
        )

        assert response.status_code == 500
        assert "Knowledge base summary update failed" in response.json()["detail"]


class TestGetSummary:
    """Test get summary endpoint"""

    @patch('apps.knowledge_summary_app.ElasticSearchService')
    def test_get_summary_success(self, mock_service_class, test_data):
        """Test successful summary retrieval"""
        expected_response = {
            "success": True,
            "index_name": test_data["index_name"],
            "summary": test_data["summary_result"]
        }

        mock_service_instance = MagicMock()
        mock_service_instance.get_summary.return_value = expected_response
        mock_service_class.return_value = mock_service_instance

        response = client.get(f"/summary/{test_data['index_name']}/summary")

        assert response.status_code == 200
        assert response.json() == expected_response

        mock_service_instance.get_summary.assert_called_once_with(
            index_name=test_data["index_name"]
        )

    @patch('apps.knowledge_summary_app.ElasticSearchService')
    def test_get_summary_exception(self, mock_service_class, test_data):
        """Test summary retrieval with exception"""
        mock_service_instance = MagicMock()
        mock_service_instance.get_summary.side_effect = Exception("Error getting summary")
        mock_service_class.return_value = mock_service_instance

        response = client.get(f"/summary/{test_data['index_name']}/summary")

        assert response.status_code == 500
        assert "Failed to get knowledge base summary" in response.json()["detail"]
