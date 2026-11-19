# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""
Unit tests for knowledge_summary_app module.

These tests focus on testing the app layer endpoints with services mocked.
All module mocks are provided by conftest.py.
"""
from test.common.contract_stubs import install_business_contract_stubs
import asyncio
import sys
import os
import types
import importlib.machinery
from unittest.mock import patch, MagicMock, AsyncMock

from nexent.storage.errors import ScopeDenied

import pytest
from pydantic import BaseModel

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


class MockAgentVerificationConfig:
    @classmethod
    def model_validate(cls, value):
        mock_config = MagicMock()
        mock_config.model_dump.return_value = value
        return mock_config


nexent_core_agents_agent_model.ToolConfig = MockToolConfig
nexent_core_agents_agent_model.AgentVerificationConfig = MockAgentVerificationConfig
sys.modules['nexent.core.agents.agent_model'] = nexent_core_agents_agent_model
nexent_nexent_vector_database = types.ModuleType('nexent.vector_database')
sys.modules['nexent.vector_database'] = nexent_nexent_vector_database
nexent_nexent_vector_database = types.ModuleType('nexent.vector_database.base')


class MockVectorDatabaseCore:
    pass


nexent_nexent_vector_database.VectorDatabaseCore = MockVectorDatabaseCore
sys.modules['nexent.vector_database.base'] = nexent_nexent_vector_database
# Create mock for vectordatabase_service BEFORE importing the app
vectordatabase_service_mock = types.ModuleType('management.services.knowledge_base.service')


class MockElasticSearchService:
    def __init__(self, *args, **kwargs):
        pass

    @staticmethod
    def require_knowledge_base_edit_permission(index_name, user_id, tenant_id=None):
        return "EDIT"


def mock_get_vector_db_core():
    return MagicMock()


vectordatabase_service_mock.ElasticSearchService = MockElasticSearchService
vectordatabase_service_mock.get_vector_db_core = mock_get_vector_db_core
sys.modules['management.services.knowledge_base.service'] = vectordatabase_service_mock

summary_service_mock = types.ModuleType('management.services.knowledge_base.summary_service')
summary_service_mock.KnowledgeSummaryService = MagicMock()
sys.modules['management.services.knowledge_base.summary_service'] = summary_service_mock

# Mock other services that might be imported
sys.modules['management.services.knowledge_base.task_state'] = types.ModuleType('management.services.knowledge_base.task_state')
sys.modules['management.services.permission.identity.groups'] = types.ModuleType('management.services.permission.identity.groups')

# knowledge_summary_app only needs this request model from contracts.agent. Keeping
# it local avoids importing unrelated EmailStr models and optional validators.
consts_model_mock = types.ModuleType('contracts.agent')


class ChangeSummaryRequest(BaseModel):
    summary_result: str


consts_model_mock.ChangeSummaryRequest = ChangeSummaryRequest
install_business_contract_stubs(consts_model_mock)

# Mock utils modules used by knowledge_summary_app to avoid deep DB/storage import chains
utils_auth_utils_mock = types.ModuleType('management.services.permission.identity.session')
utils_auth_utils_mock.get_current_user_id = MagicMock(return_value=("test_user_id", "test_tenant_id"))
utils_auth_utils_mock.authenticate = lambda: None
utils_auth_utils_mock.get_current_user_context = MagicMock(return_value=("test_user_id", "test_tenant_id", ("DEV",)))
utils_auth_utils_mock.get_current_user_info = MagicMock(return_value=("test_user_id", "test_tenant_id", "en"))
sys.modules['management.services.permission.identity.session'] = utils_auth_utils_mock

utils_config_utils_mock = types.ModuleType('management.services.configuration.tenant.settings')
mock_tenant_config_manager = MagicMock()
mock_tenant_config = MagicMock()
mock_tenant_config.get.return_value = None
mock_tenant_config_manager.load_config.return_value = mock_tenant_config
utils_config_utils_mock.tenant_config_manager = mock_tenant_config_manager
sys.modules['management.services.configuration.tenant.settings'] = utils_config_utils_mock

# Import the modules we need
from fastapi.testclient import TestClient
from fastapi import FastAPI
from fastapi import HTTPException
from management.utils import knowledge_permission as permission_utils
from management.api.knowledge_base.knowledge_summary import router

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


def test_permission_utils_maps_missing_knowledge_base_to_404(monkeypatch):
    def raise_missing(**_kwargs):
        raise ValueError("Knowledge base 'missing' not found")

    monkeypatch.setattr(
        permission_utils.ElasticSearchService,
        "require_knowledge_base_edit_permission",
        raise_missing,
    )

    with pytest.raises(HTTPException) as exc_info:
        permission_utils.require_knowledge_base_edit_permission(
            "missing", "user-1", "tenant-1"
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Knowledge base 'missing' not found"


def test_permission_utils_maps_permission_error_to_403(monkeypatch):
    def raise_forbidden(**_kwargs):
        raise PermissionError("No permission to modify this knowledge base")

    monkeypatch.setattr(
        permission_utils.ElasticSearchService,
        "require_knowledge_base_edit_permission",
        raise_forbidden,
    )

    with pytest.raises(HTTPException) as exc_info:
        permission_utils.require_knowledge_base_edit_permission(
            "kb", "user-1", "tenant-1"
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "No permission to modify this knowledge base"


@pytest.fixture(autouse=True)
def default_model_boundary(monkeypatch):
    from management.api.knowledge_base import knowledge_summary as module
    monkeypatch.setattr(module, 'read_default_summary_model', AsyncMock(return_value=None))


class TestAutoSummary:
    """Test auto summary generation endpoint"""

    @patch('management.api.knowledge_base.knowledge_summary.KnowledgeSummaryService')
    @patch('management.api.knowledge_base.knowledge_summary.get_current_user_info')
    def test_auto_summary_success(self, mock_user_info, mock_service_class, test_data):
        """Test successful auto summary generation"""

        mock_user_info_value = ("test_user_id", "test_tenant_id", "en")
        mock_user_info.return_value = mock_user_info_value

        mock_service_instance = MagicMock()
        mock_service_instance.generate = AsyncMock(return_value="summary")
        mock_service_class.return_value = mock_service_instance

        response = client.post(
            f"/summary/{test_data['index_name']}/auto_summary?batch_size=500&model_id=1",
            headers=test_data["auth_header"]
        )

        assert response.status_code == 200
        assert mock_service_instance.generate.call_count == 1

        call_kwargs = mock_service_instance.generate.call_args.kwargs
        assert call_kwargs['index_name'] == test_data['index_name']
        assert call_kwargs['batch_size'] == 500
        assert call_kwargs['tenant_id'] == mock_user_info_value[1]
        assert call_kwargs['language'] == mock_user_info_value[2]
        assert call_kwargs['model_id'] == 1

    @patch('management.api.knowledge_base.knowledge_summary.KnowledgeSummaryService')
    @patch('management.api.knowledge_base.knowledge_summary.get_current_user_info')
    def test_auto_summary_forbidden_for_read_only(self, mock_user_info, mock_service_class, test_data):
        """The SI-backed service must deny a read-only summary requester."""
        mock_user_info.return_value = test_data['user_info']
        service = mock_service_class.return_value
        service.generate = AsyncMock(side_effect=ScopeDenied())
        response = client.post(f"/summary/{test_data['index_name']}/auto_summary", headers=test_data['auth_header'])
        assert response.status_code == 403
        assert response.json()['detail'] == 'No permission to modify this knowledge base'
        service.generate.assert_awaited_once()

    @patch('management.api.knowledge_base.knowledge_summary.KnowledgeSummaryService')
    @patch('management.api.knowledge_base.knowledge_summary.get_current_user_info')
    def test_auto_summary_without_model_id(self, mock_user_info, mock_service_class, test_data):
        """Test successful auto summary generation without model_id parameter"""

        mock_user_info_value = ("test_user_id", "test_tenant_id", "en")
        mock_user_info.return_value = mock_user_info_value

        mock_service_instance = MagicMock()
        mock_service_instance.generate = AsyncMock(return_value="summary")
        mock_service_class.return_value = mock_service_instance

        response = client.post(
            f"/summary/{test_data['index_name']}/auto_summary?batch_size=500",
            headers=test_data["auth_header"]
        )

        assert response.status_code == 200
        assert mock_service_instance.generate.call_count == 1

        call_kwargs = mock_service_instance.generate.call_args.kwargs
        assert call_kwargs['index_name'] == test_data['index_name']
        assert call_kwargs['batch_size'] == 500
        assert call_kwargs['model_id'] is None

    @patch('management.api.knowledge_base.knowledge_summary.KnowledgeSummaryService')
    @patch('management.api.knowledge_base.knowledge_summary.get_current_user_info')
    def test_auto_summary_exception(self, mock_user_info, mock_service_class, test_data):
        """Test auto summary generation with exception"""

        mock_user_info_value = ("test_user_id", "test_tenant_id", "en")
        mock_user_info.return_value = mock_user_info_value

        mock_service_instance = MagicMock()
        mock_service_instance.generate = AsyncMock(
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

    @patch('management.api.knowledge_base.knowledge_summary.KnowledgeSummaryService')
    @patch('management.api.knowledge_base.knowledge_summary.get_current_user_info')
    @patch('management.api.knowledge_base.knowledge_summary.read_default_summary_model')
    def test_auto_summary_uses_tenant_llm_id(
        self, mock_config_manager, mock_user_info, mock_service_class, test_data
    ):
        """Test that auto summary uses LLM_ID from tenant config when model_id is not provided"""

        mock_user_info_value = ("test_user_id", "test_tenant_id", "en")
        mock_user_info.return_value = mock_user_info_value

        mock_config_manager.return_value = 5

        mock_service_instance = MagicMock()
        mock_service_instance.generate = AsyncMock(return_value="summary")
        mock_service_class.return_value = mock_service_instance

        response = client.post(
            f"/summary/{test_data['index_name']}/auto_summary?batch_size=100",
            headers=test_data["auth_header"]
        )

        assert response.status_code == 200
        assert mock_config_manager.await_count == 1
        actor = mock_config_manager.await_args.args[0]
        assert (actor.user_id, actor.tenant_id) == ('test_user_id', 'test_tenant_id')

        call_kwargs = mock_service_instance.generate.call_args.kwargs
        assert call_kwargs['model_id'] == 5

    @patch('management.api.knowledge_base.knowledge_summary.KnowledgeSummaryService')
    @patch('management.api.knowledge_base.knowledge_summary.get_current_user_info')
    @patch('management.api.knowledge_base.knowledge_summary.read_default_summary_model')
    def test_auto_summary_tenant_config_no_llm_id(
        self, mock_config_manager, mock_user_info, mock_service_class, test_data
    ):
        """Test auto summary when tenant config has no LLM_ID"""

        mock_user_info_value = ("test_user_id", "test_tenant_id", "en")
        mock_user_info.return_value = mock_user_info_value

        mock_config_manager.return_value = None

        mock_service_instance = MagicMock()
        mock_service_instance.generate = AsyncMock(return_value="summary")
        mock_service_class.return_value = mock_service_instance

        response = client.post(
            f"/summary/{test_data['index_name']}/auto_summary",
            headers=test_data["auth_header"]
        )

        assert response.status_code == 200
        call_kwargs = mock_service_instance.generate.call_args.kwargs
        assert call_kwargs['model_id'] is None

    @patch('management.api.knowledge_base.knowledge_summary.KnowledgeSummaryService')
    @patch('management.api.knowledge_base.knowledge_summary.get_current_user_info')
    @patch('management.api.knowledge_base.knowledge_summary.read_default_summary_model')
    def test_auto_summary_tenant_config_exception(
        self, mock_config_manager, mock_user_info, mock_service_class, test_data
    ):
        """Test auto summary when loading tenant config raises exception"""

        mock_user_info_value = ("test_user_id", "test_tenant_id", "en")
        mock_user_info.return_value = mock_user_info_value

        mock_config_manager.side_effect = Exception("Config error")

        mock_service_instance = MagicMock()
        mock_service_instance.generate = AsyncMock(return_value="summary")
        mock_service_class.return_value = mock_service_instance

        response = client.post(
            f"/summary/{test_data['index_name']}/auto_summary",
            headers=test_data["auth_header"]
        )

        assert response.status_code == 200
        call_kwargs = mock_service_instance.generate.call_args.kwargs
        assert call_kwargs['model_id'] is None





class TestTokenExpired:
    """Expired tokens must map to 401 on summary endpoints."""

    @patch('management.api.knowledge_base.knowledge_summary.get_current_user_info')
    def test_auto_summary_token_expired(self, mock_user_info, test_data):
        from contracts.errors.exceptions import TokenExpiredError

        mock_user_info.side_effect = TokenExpiredError("expired")

        response = client.post(
            f"/summary/{test_data['index_name']}/auto_summary",
            headers=test_data["auth_header"]
        )

        assert response.status_code == 401
        assert "expired" in response.json()["detail"]

    @patch('management.api.knowledge_base.knowledge_summary.get_current_user_id')
    def test_change_summary_token_expired(self, mock_user_id, test_data):
        from contracts.errors.exceptions import TokenExpiredError

        mock_user_id.side_effect = TokenExpiredError("expired")

        response = client.post(
            f"/summary/{test_data['index_name']}/summary",
            json={"summary_result": "test summary"},
            headers=test_data["auth_header"]
        )

        assert response.status_code == 401
        assert "expired" in response.json()["detail"]
