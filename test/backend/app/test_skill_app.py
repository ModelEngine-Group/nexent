"""
Unit tests for backend.apps.skill_app module.
"""
import sys
import os
import io
import types
import zipfile

# Add backend path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../backend"))

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

# Define SkillInstanceInfoRequest inline to avoid import chain issues
class SkillInstanceInfoRequest(BaseModel):
    skill_id: int
    agent_id: int
    enabled: bool = True
    version_no: int = 0

# Mock external dependencies before any imports
boto3_mock = MagicMock()
sys.modules['boto3'] = boto3_mock

# Create nexent module hierarchy
nexent_mock = types.ModuleType('nexent')
nexent_core_mock = types.ModuleType('nexent.core')
nexent_core_agents_mock = types.ModuleType('nexent.core.agents')
nexent_core_agents_agent_model_mock = types.ModuleType('nexent.core.agents.agent_model')
nexent_skills_mock = types.ModuleType('nexent.skills')
nexent_skills_mock.__path__ = []  # Required for submodule lookups
nexent_skills_skill_manager_mock = types.ModuleType('nexent.skills.skill_manager')
nexent_storage_mock = types.ModuleType('nexent.storage')
nexent_storage_storage_client_factory_mock = types.ModuleType('nexent.storage.storage_client_factory')
nexent_storage_minio_config_mock = types.ModuleType('nexent.storage.minio_config')

sys.modules['nexent'] = nexent_mock
sys.modules['nexent.core'] = nexent_core_mock
sys.modules['nexent.core.agents'] = nexent_core_agents_mock
sys.modules['nexent.core.agents.agent_model'] = nexent_core_agents_agent_model_mock
sys.modules['nexent.skills'] = nexent_skills_mock
sys.modules['nexent.skills.skill_manager'] = nexent_skills_skill_manager_mock
sys.modules['nexent.storage'] = nexent_storage_mock
sys.modules['nexent.storage.storage_client_factory'] = nexent_storage_storage_client_factory_mock
sys.modules['nexent.storage.minio_config'] = nexent_storage_minio_config_mock

# Set attributes on nexent_mock for proper submodule resolution
setattr(nexent_mock, 'skills', nexent_skills_mock)

# Mock ToolConfig from agent_model
nexent_core_agents_agent_model_mock.ToolConfig = type('ToolConfig', (), {})

# ModelConfig mock that accepts kwargs
class MockModelConfig:
    def __init__(
        self,
        cite_name: str = None,
        api_key: str = None,
        model_name: str = None,
        url: str = None,
        temperature: float = None,
        top_p: float = None,
        ssl_verify: bool = None,
        model_factory: str = None,
        **kwargs
    ):
        self.cite_name = cite_name
        self.api_key = api_key
        self.model_name = model_name
        self.url = url
        self.temperature = temperature
        self.top_p = top_p
        self.ssl_verify = ssl_verify
        self.model_factory = model_factory

nexent_core_agents_agent_model_mock.ModelConfig = MockModelConfig

# Set up storage mocks
storage_client_mock = MagicMock()
nexent_storage_storage_client_factory_mock.create_storage_client_from_config = MagicMock(return_value=storage_client_mock)

# Set up MinIOStorageConfig mock properly
class MockMinIOStorageConfig:
    def validate(self):
        pass
nexent_storage_minio_config_mock.MinIOStorageConfig = MockMinIOStorageConfig

# Mock SkillManager
class MockSkillManager:
    def __init__(self, local_skills_dir=None, **kwargs):
        self.local_skills_dir = local_skills_dir
nexent_skills_mock.SkillManager = MockSkillManager

# Mock consts
consts_mock = types.ModuleType('consts')
consts_exceptions_mock = types.ModuleType('consts.exceptions')
consts_model_mock = types.ModuleType('consts.model')
consts_const_mock = types.ModuleType('consts.const')
sys.modules['consts'] = consts_mock
sys.modules['consts.exceptions'] = consts_exceptions_mock
sys.modules['consts.model'] = consts_model_mock
sys.modules['consts.const'] = consts_const_mock
consts_const_mock.MODEL_CONFIG_MAPPING = {"llm": "llm_model"}
consts_const_mock.APP_VERSION = "v2.0.2"
consts_const_mock.STREAMABLE_CONTENT_TYPES = frozenset(["text/event-stream"])

class SkillException(Exception):
    pass
consts_exceptions_mock.SkillException = SkillException
consts_exceptions_mock.UnauthorizedError = type('UnauthorizedError', (Exception,), {})

# Use real Pydantic model for SkillInstanceInfoRequest
consts_model_mock.BaseModel = BaseModel
consts_model_mock.SkillInstanceInfoRequest = SkillInstanceInfoRequest

# Add mock Pydantic models for all required imports
from pydantic import Field
from typing import Any, Dict, List, Optional

class MockSkillCreateRequest(BaseModel):
    name: str
    description: str
    content: str
    tool_ids: Optional[List[int]] = []
    tool_names: Optional[List[str]] = []
    tags: Optional[List[str]] = []
    source: Optional[str] = "custom"
    config_schemas: Optional[Dict[str, Any]] = None
    config_values: Optional[Dict[str, Any]] = None
    files: Optional[List[Dict[str, str]]] = None

class MockSkillFileData(BaseModel):
    path: str
    content: str

class MockSkillUpdateRequest(BaseModel):
    description: Optional[str] = None
    content: Optional[str] = None
    tool_ids: Optional[List[int]] = None
    tool_names: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    source: Optional[str] = None
    config_schemas: Optional[Dict[str, Any]] = None
    config_values: Optional[Dict[str, Any]] = None
    files: Optional[List[MockSkillFileData]] = None

class MockSkillResponse(BaseModel):
    skill_id: Optional[int] = None
    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None

class MockSkillCreateInteractiveRequest(BaseModel):
    user_request: str
    language: Optional[str] = "zh"
    complexity: Optional[str] = "simple"
    existing_skill: Optional[str] = None

consts_model_mock.SkillCreateRequest = MockSkillCreateRequest
consts_model_mock.SkillUpdateRequest = MockSkillUpdateRequest
consts_model_mock.SkillResponse = MockSkillResponse
consts_model_mock.SkillCreateInteractiveRequest = MockSkillCreateInteractiveRequest

# Mock services
services_mock = types.ModuleType('services')
services_mock.__path__ = []  # Make it a package so submodules can be imported
services_skill_service_mock = types.ModuleType('services.skill_service')
services_asset_owner_visibility_mock = types.ModuleType('services.asset_owner_visibility')
sys.modules['services'] = services_mock
sys.modules['services.skill_service'] = services_skill_service_mock
sys.modules['services.asset_owner_visibility'] = services_asset_owner_visibility_mock
setattr(services_mock, 'skill_service', services_skill_service_mock)
setattr(services_mock, 'asset_owner_visibility', services_asset_owner_visibility_mock)

class MockSkillService:
    def __init__(self):
        self.repository = MagicMock()
        self.skill_manager = MagicMock()
services_skill_service_mock.SkillService = MockSkillService
services_skill_service_mock.get_skill_manager = MagicMock()
services_skill_service_mock.skill_creation_task_manager = MagicMock()
services_skill_service_mock.stream_skill_creation = MagicMock(return_value=("task123", MagicMock()))
services_skill_service_mock.update_skill_list = MagicMock()
services_skill_service_mock.get_official_skills_with_status = MagicMock(return_value=[])
services_skill_service_mock.install_skills_from_zip_for_tenant = MagicMock(return_value=[])
services_asset_owner_visibility_mock.can_view_skill = MagicMock(return_value=True)

# Mock utils
utils_mock = types.ModuleType('utils')
utils_mock.__path__ = []  # Empty __path__ to make it a namespace package
utils_auth_utils_mock = types.ModuleType('utils.auth_utils')
utils_config_utils_mock = types.ModuleType('utils.config_utils')
sys.modules['utils'] = utils_mock
sys.modules['utils.auth_utils'] = utils_auth_utils_mock
sys.modules['utils.config_utils'] = utils_config_utils_mock
utils_auth_utils_mock.get_current_user_id = MagicMock(return_value=("user123", "tenant123"))
utils_auth_utils_mock.get_current_user_info = MagicMock(return_value=("user123", "tenant123", "zh"))
utils_config_utils_mock.tenant_config_manager = MagicMock()
utils_config_utils_mock.get_model_name_from_config = MagicMock(return_value="gpt-4")
# Set utils.config_utils as attribute for attribute-based imports
setattr(utils_mock, 'config_utils', utils_config_utils_mock)

# Mock utils.prompt_template_utils
utils_prompt_template_utils_mock = types.ModuleType('utils.prompt_template_utils')
sys.modules['utils.prompt_template_utils'] = utils_prompt_template_utils_mock
utils_prompt_template_utils_mock.get_skill_creation_simple_prompt_template = MagicMock(return_value={
    "system_prompt": "You are a skill creator",
    "user_prompt": "Create a skill"
})

# Mock agents module
agents_mock = types.ModuleType('agents')
agents_skill_creation_agent_mock = types.ModuleType('agents.skill_creation_agent')
sys.modules['agents'] = agents_mock
sys.modules['agents.skill_creation_agent'] = agents_skill_creation_agent_mock
agents_skill_creation_agent_mock.create_simple_skill_from_request = MagicMock()

# Mock nexent.core.utils
nexent_core_utils_mock = types.ModuleType('nexent.core.utils')
nexent_core_utils_observer_mock = types.ModuleType('nexent.core.utils.observer')
sys.modules['nexent.core.utils'] = nexent_core_utils_mock
sys.modules['nexent.core.utils.observer'] = nexent_core_utils_observer_mock
nexent_core_utils_observer_mock.MessageObserver = type('MessageObserver', (), {})

# Mock database
database_mock = types.ModuleType('database')
database_skill_db_mock = types.ModuleType('database.skill_db')
sys.modules['database'] = database_mock
sys.modules['database.skill_db'] = database_skill_db_mock

# Set up MinIOStorageConfig mock properly
class MockMinIOStorageConfig:
    def validate(self):
        pass
nexent_storage_minio_config_mock.MinIOStorageConfig = MockMinIOStorageConfig

# Skip redundant patches - mocks are already set up via sys.modules
# These patches would fail because the modules are already mocked

# Now import the app module
from backend.apps import skill_app


# ===== List Skills Endpoint Tests =====
class TestListSkillsEndpoint:
    """Test GET /skills endpoint."""

    def test_list_skills_success(self, mocker):
        """Test successful listing of skills."""
        with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
            mock_auth.return_value = ("user123", "tenant123")
            with patch('backend.apps.skill_app.SkillService') as mock_service_class:
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.list_skills.return_value = [
                    {"skill_id": 1, "name": "skill1", "description": "Desc1"},
                    {"skill_id": 2, "name": "skill2", "description": "Desc2"}
                ]

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.get("/skills", headers={"Authorization": "Bearer token123"})

                assert response.status_code == 200
                data = response.json()
                assert "skills" in data
                assert len(data["skills"]) == 2

    def test_list_skills_empty(self, mocker):
        """Test listing skills when none exist."""
        with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
            mock_auth.return_value = ("user123", "tenant123")
            with patch('backend.apps.skill_app.SkillService') as mock_service_class:
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.list_skills.return_value = []

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.get("/skills", headers={"Authorization": "Bearer token123"})

                assert response.status_code == 200
                data = response.json()
                assert data["skills"] == []

    def test_list_skills_error(self, mocker):
        """Test listing skills when service throws exception."""
        from backend.apps.skill_app import SkillException
        with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
            mock_auth.return_value = ("user123", "tenant123")
            with patch('backend.apps.skill_app.SkillService') as mock_service_class:
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.list_skills.side_effect = SkillException("Database error")

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.get("/skills", headers={"Authorization": "Bearer token123"})

            assert response.status_code == 500

    def test_list_skills_super_admin_with_tenant_id(self, mocker):
        """Test super admin listing skills for a specific tenant via tenant_id query param."""
        with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
            mock_auth.return_value = ("super_user", "super_tenant")
            with patch('backend.apps.skill_app.SkillService') as mock_service_class:
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.list_skills.return_value = [
                    {"skill_id": 10, "name": "admin_skill", "description": "Admin desc"}
                ]

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.get(
                    "/skills?tenant_id=target_tenant",
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 200
                data = response.json()
                assert "skills" in data
                assert len(data["skills"]) == 1
                # Verify the service was called with the target tenant_id, not super_tenant
                mock_service.list_skills.assert_called_once_with(tenant_id="target_tenant")


# ===== Create Skill Endpoint Tests =====
class TestCreateSkillEndpoint:
    """Test POST /skills endpoint."""

    def test_create_skill_success(self, mocker):
        """Test successful skill creation."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.repository.get_tool_ids_by_names.return_value = []
                mock_service.create_skill.return_value = {
                    "skill_id": 1,
                    "name": "new_skill",
                    "description": "A new skill"
                }

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.post(
                    "/skills",
                    json={
                        "name": "new_skill",
                        "description": "A new skill",
                        "content": "# Content"
                    },
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 201
                data = response.json()
                assert data["name"] == "new_skill"

    def test_create_skill_with_tool_names(self, mocker):
        """Test skill creation with tool_names returns 500 (NotImplementedError)."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.post(
                    "/skills",
                    json={
                        "name": "tool_skill",
                        "description": "With tools",
                        "content": "# Content",
                        "tool_names": ["tool1", "tool2"]
                    },
                    headers={"Authorization": "Bearer token123"}
                )

                # Tool names are not supported - returns 500 via NotImplementedError
                assert response.status_code == 500

    def test_create_skill_already_exists(self, mocker):
        """Test skill creation when skill already exists."""
        from backend.apps.skill_app import SkillException
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.create_skill.side_effect = SkillException("Skill 'test' already exists")

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.post(
                    "/skills",
                    json={
                        "name": "test",
                        "description": "Test skill",
                        "content": "# Test skill"
                    },
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 409

    def test_create_skill_unauthorized(self, mocker):
        """Test skill creation with invalid auth."""
        from backend.apps.skill_app import UnauthorizedError
        with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
            mock_auth.side_effect = UnauthorizedError("Invalid token")

            app = FastAPI()
            app.include_router(skill_app.router)
            client = TestClient(app)

            response = client.post(
                "/skills",
                json={
                    "name": "test",
                    "description": "Test skill",
                    "content": "# Test skill"
                },
                headers={"Authorization": "Bearer invalid"}
            )

            assert response.status_code == 401

    def test_create_skill_validation_error(self, mocker):
        """Test skill creation with invalid data."""
        from backend.apps.skill_app import SkillException
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.create_skill.side_effect = SkillException("Validation failed")

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.post(
                    "/skills",
                    json={
                        "name": "test",
                        "description": "Test",
                        "content": "# Test"
                    },
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 400


# ===== Create Skill From File Endpoint Tests =====
class TestCreateSkillFromFileEndpoint:
    """Test POST /skills/upload endpoint."""

    def test_upload_md_file_success(self, mocker):
        """Test successful skill upload from MD file."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.create_skill_from_file.return_value = {
                    "skill_id": 1,
                    "name": "uploaded_skill"
                }

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                content = b"""---
name: uploaded_skill
description: Uploaded skill
---
# Content
"""
                response = client.post(
                    "/skills/upload",
                    files={"file": ("test.md", content, "text/markdown")},
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 201
                data = response.json()
                assert data["name"] == "uploaded_skill"

    def test_upload_zip_file_success(self, mocker):
        """Test successful skill upload from ZIP file."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.create_skill_from_file.return_value = {
                    "skill_id": 1,
                    "name": "zip_skill"
                }

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                # Create a ZIP file
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w') as zf:
                    zf.writestr("SKILL.md", "---\nname: zip_skill\ndescription: ZIP skill\n---\n# Content")
                zip_buffer.seek(0)

                response = client.post(
                    "/skills/upload",
                    files={"file": ("skill.zip", zip_buffer.getvalue(), "application/zip")},
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 201

    def test_upload_with_skill_name_override(self, mocker):
        """Test skill upload with name override."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.create_skill_from_file.return_value = {
                    "skill_id": 1,
                    "name": "custom_name"
                }

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                content = b"---\nname: original\ndescription: Original\n---\n# Content"
                response = client.post(
                    "/skills/upload",
                    files={"file": ("test.md", content, "text/markdown")},
                    data={"skill_name": "custom_name"},
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 201


# ===== Get Skill Endpoint Tests =====
class TestGetSkillEndpoint:
    """Test GET /skills/{skill_name} endpoint."""

    def test_get_skill_success(self, mocker):
        """Test successful skill retrieval."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            mock_service = MagicMock()
            mock_service_class.return_value = mock_service
            mock_service.get_skill.return_value = {
                "skill_id": 1,
                "name": "test_skill",
                "description": "Test skill"
            }

            app = FastAPI()
            app.include_router(skill_app.router)
            client = TestClient(app)

            response = client.get("/skills/test_skill")

            assert response.status_code == 200
            data = response.json()
            assert data["name"] == "test_skill"

    def test_get_skill_not_found(self, mocker):
        """Test skill not found."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            mock_service = MagicMock()
            mock_service_class.return_value = mock_service
            mock_service.get_skill.return_value = None

            app = FastAPI()
            app.include_router(skill_app.router)
            client = TestClient(app)

            response = client.get("/skills/nonexistent")

            assert response.status_code == 404


class TestAssetOwnerSkillVisibility:
    """Test ASSET_OWNER skill visibility enforcement at the app layer."""

    def test_get_skill_file_tree_denied_for_non_asset_owner_tenant(self, mocker):
        """Non-asset-owner callers receive a denial payload for asset-owner skills."""
        asset_owner_tenant_id = "asset_owner_tenant_id"

        with patch("backend.apps.skill_app.can_view_skill", return_value=False), \
             patch("backend.apps.skill_app.get_current_user_id", return_value=("user123", "regular_tenant")), \
             patch("backend.apps.skill_app.SkillService") as mock_service_class:
            mock_service = MagicMock()
            mock_service_class.return_value = mock_service
            mock_service.get_skill.return_value = {
                "name": "ao_skill",
                "tenant_id": asset_owner_tenant_id,
            }

            app = FastAPI()
            app.include_router(skill_app.router)
            client = TestClient(app)

            response = client.get("/skills/ao_skill/files")

            assert response.status_code == 200
            assert response.json() == {"content": "您无权限查看"}
            mock_service.get_skill_file_tree.assert_not_called()


# ===== Update Skill Endpoint Tests =====
class TestUpdateSkillEndpoint:
    """Test PUT /skills/{skill_name} endpoint."""

    def test_update_skill_success(self, mocker):
        """Test successful skill update."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.repository.get_tool_ids_by_names.return_value = []
                mock_service.update_skill.return_value = {
                    "skill_id": 1,
                    "name": "updated_skill",
                    "description": "Updated description"
                }

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.put(
                    "/skills/updated_skill",
                    json={"description": "Updated description"},
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 200

    def test_update_skill_not_found(self, mocker):
        """Test update non-existent skill."""
        from backend.apps.skill_app import SkillException
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.repository.get_tool_ids_by_names.return_value = []
                mock_service.update_skill.side_effect = SkillException("Skill not found: nonexistent")

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.put(
                    "/skills/nonexistent",
                    json={"description": "Updated"},
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 404

    def test_update_skill_no_fields(self, mocker):
        """Test update with no fields to update."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                # Set up update_skill to return a serializable dict
                mock_service.update_skill.return_value = {"name": "test_skill", "updated": True}

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.put(
                    "/skills/test_skill",
                    json={},
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 400


# ===== Delete Skill Endpoint Tests =====
class TestDeleteSkillEndpoint:
    """Test DELETE /skills/{skill_name} endpoint."""

    def test_delete_skill_success(self, mocker):
        """Test successful skill deletion."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.delete_skill.return_value = True

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.delete(
                    "/skills/skill_to_delete",
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 200

    def test_delete_skill_not_found(self, mocker):
        """Test delete non-existent skill."""
        from backend.apps.skill_app import SkillException
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.delete_skill.side_effect = SkillException("Skill not found")

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.delete(
                    "/skills/nonexistent",
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 400


# ===== Get Skill File Tree Endpoint Tests =====
class TestGetSkillFileTreeEndpoint:
    """Test GET /skills/{skill_name}/files endpoint."""

    def test_get_file_tree_success(self, mocker):
        """Test successful file tree retrieval."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            mock_service = MagicMock()
            mock_service_class.return_value = mock_service
            mock_service.get_skill_file_tree.return_value = {
                "name": "test_skill",
                "type": "directory",
                "children": [
                    {"name": "SKILL.md", "type": "file"},
                    {"name": "scripts", "type": "directory"}
                ]
            }

            app = FastAPI()
            app.include_router(skill_app.router)
            client = TestClient(app)

            response = client.get("/skills/test_skill/files")

            assert response.status_code == 200

    def test_get_file_tree_not_found(self, mocker):
        """Test file tree for non-existent skill."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            mock_service = MagicMock()
            mock_service_class.return_value = mock_service
            mock_service.get_skill_file_tree.return_value = None

            app = FastAPI()
            app.include_router(skill_app.router)
            client = TestClient(app)

            response = client.get("/skills/nonexistent/files")

            assert response.status_code == 404


# ===== Get Skill File Content Endpoint Tests =====
class TestGetSkillFileContentEndpoint:
    """Test GET /skills/{skill_name}/files/{file_path} endpoint."""

    def test_get_file_content_success(self, mocker):
        """Test successful file content retrieval."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            mock_service = MagicMock()
            mock_service_class.return_value = mock_service
            mock_service.get_skill_file_content.return_value = "# README content"

            app = FastAPI()
            app.include_router(skill_app.router)
            client = TestClient(app)

            response = client.get("/skills/test_skill/files/README.md")

            assert response.status_code == 200
            data = response.json()
            assert "content" in data

    def test_get_file_content_not_found(self, mocker):
        """Test file content for non-existent file."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            mock_service = MagicMock()
            mock_service_class.return_value = mock_service
            mock_service.get_skill_file_content.return_value = None

            app = FastAPI()
            app.include_router(skill_app.router)
            client = TestClient(app)

            response = client.get("/skills/test_skill/files/nonexistent.md")

            assert response.status_code == 404


# ===== Update Skill From File Endpoint Tests =====
class TestUpdateSkillFromFileEndpoint:
    """Test PUT /skills/{skill_name}/upload endpoint."""

    def test_update_skill_from_md_success(self, mocker):
        """Test successful skill update from MD file."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.update_skill_from_file.return_value = {
                    "skill_id": 1,
                    "name": "updated_skill"
                }

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                content = b"""---
name: updated_skill
description: Updated description
---
# Content
"""
                response = client.put(
                    "/skills/updated_skill/upload",
                    files={"file": ("test.md", content, "text/markdown")},
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 200

    def test_update_skill_not_found(self, mocker):
        """Test update from file for non-existent skill."""
        from backend.apps.skill_app import SkillException
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.update_skill_from_file.side_effect = SkillException("Skill not found: nonexistent")

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                content = b"---\nname: test\ndescription: Test\n---"
                response = client.put(
                    "/skills/nonexistent/upload",
                    files={"file": ("test.md", content, "text/markdown")},
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 404


# ===== Update Skill Instance Endpoint Tests =====
class TestUpdateSkillInstanceEndpoint:
    """Test POST /skills/instance/update endpoint."""

    def test_update_instance_success(self, mocker):
        """Test successful skill instance update."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.get_skill_by_id.return_value = {
                    "skill_id": 1,
                    "name": "test_skill"
                }
                mock_service.create_or_update_skill_instance.return_value = {
                    "skill_id": 1,
                    "agent_id": 1
                }

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.post(
                    "/skills/instance/update",
                    json={
                        "skill_id": 1,
                        "agent_id": 1,
                        "enabled": True
                    },
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 200
                data = response.json()
                assert "instance" in data

    def test_update_instance_skill_not_found(self, mocker):
        """Test update instance for non-existent skill."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.get_skill_by_id.return_value = None

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.post(
                    "/skills/instance/update",
                    json={
                        "skill_id": 999,
                        "agent_id": 1,
                        "enabled": True
                    },
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 404


# ===== List Skill Instances Endpoint Tests =====
class TestListSkillInstancesEndpoint:
    """Test GET /skills/instance/list endpoint."""

    def test_list_instances_success(self, mocker):
        """Test successful skill instances listing."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.list_skill_instances.return_value = [
                    {"skill_id": 1, "agent_id": 1, "enabled": True}
                ]
                mock_service.get_skill_by_id.return_value = {
                    "skill_id": 1,
                    "name": "test_skill",
                    "description": "Test",
                    "content": "# Test",
                    "params": {}
                }

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.get(
                    "/skills/instance/list?agent_id=1",
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 200
                data = response.json()
                assert "instances" in data

    def test_list_instances_empty(self, mocker):
        """Test listing instances when none exist."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.list_skill_instances.return_value = []

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.get(
                    "/skills/instance/list?agent_id=1",
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 200


# ===== Get Skill Instance Endpoint Tests =====
class TestGetSkillInstanceEndpoint:
    """Test GET /skills/instance endpoint."""

    def test_get_instance_success(self, mocker):
        """Test successful skill instance retrieval."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.get_skill_instance.return_value = {
                    "skill_id": 1,
                    "agent_id": 1,
                    "enabled": True,
                    "version_no": 0
                }
                mock_service.get_skill_by_id.return_value = {
                    "skill_id": 1,
                    "name": "test_skill",
                    "description": "Test",
                    "content": "# Test",
                    "params": {}
                }

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.get(
                    "/skills/instance?agent_id=1&skill_id=1",
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 200

    def test_get_instance_not_found(self, mocker):
        """Test instance not found."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                # Return None for not found
                mock_service.get_skill_instance.return_value = None

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.get(
                    "/skills/instance?agent_id=1&skill_id=999",
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 404


# ===== Error Handling Tests =====
class TestErrorHandling:
    """Test error handling scenarios."""

    def test_unexpected_error_in_list_skills(self, mocker):
        """Test unexpected error handling in list_skills."""
        with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
            mock_auth.return_value = ("user123", "tenant123")
            with patch('backend.apps.skill_app.SkillService') as mock_service_class:
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.list_skills.side_effect = Exception("Unexpected error")

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.get("/skills", headers={"Authorization": "Bearer token123"})

            assert response.status_code == 500
            assert "Internal server error" in response.json()["detail"]

    def test_unexpected_error_in_get_skill(self, mocker):
        """Test unexpected error handling in get_skill."""
        from backend.apps.skill_app import SkillException
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            mock_service = MagicMock()
            mock_service_class.return_value = mock_service
            mock_service.get_skill.side_effect = SkillException("Error")

            app = FastAPI()
            app.include_router(skill_app.router)
            client = TestClient(app)

            response = client.get("/skills/test_skill")

            assert response.status_code == 500

    def test_unauthorized_in_create(self, mocker):
        """Test unauthorized error in create_skill."""
        from backend.apps.skill_app import UnauthorizedError
        with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
            mock_auth.side_effect = UnauthorizedError("No token")

            app = FastAPI()
            app.include_router(skill_app.router)
            client = TestClient(app)

            response = client.post(
                "/skills",
                json={"name": "test", "description": "Test", "content": "# Test"},
                headers={"Authorization": "Bearer invalid"}
            )

            assert response.status_code == 401


    def test_get_instance_not_found(self, mocker):
        """Test instance not found."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                # Return None for not found
                mock_service.get_skill_instance.return_value = None

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.get(
                    "/skills/instance?agent_id=1&skill_id=999",
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 404


# ===== Update Skill Instance Endpoint Additional Tests =====
class TestUpdateSkillInstanceEndpointExtended:
    """Additional tests for POST /skills/instance/update endpoint."""

    def test_update_instance_validation_error(self, mocker):
        """Test update instance with validation error."""
        from backend.apps.skill_app import SkillException
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.get_skill_by_id.return_value = {
                    "skill_id": 1,
                    "name": "test_skill"
                }
                mock_service.create_or_update_skill_instance.side_effect = SkillException("Validation failed")

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.post(
                    "/skills/instance/update",
                    json={
                        "skill_id": 1,
                        "agent_id": 1,
                        "enabled": True
                    },
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 400

    def test_update_instance_unauthorized(self, mocker):
        """Test update instance without authorization."""
        from backend.apps.skill_app import UnauthorizedError
        with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
            mock_auth.side_effect = UnauthorizedError("No token")

            app = FastAPI()
            app.include_router(skill_app.router)
            client = TestClient(app)

            response = client.post(
                "/skills/instance/update",
                json={
                    "skill_id": 1,
                    "agent_id": 1,
                    "enabled": True
                },
                headers={"Authorization": "Bearer invalid"}
            )

            assert response.status_code == 401


# ===== List Skill Instances Endpoint Additional Tests =====
class TestListSkillInstancesEndpointExtended:
    """Additional tests for GET /skills/instance/list endpoint."""

    def test_list_instances_with_skill_info(self, mocker):
        """Test listing instances with enriched skill info."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.list_skill_instances.return_value = [
                    {"skill_id": 1, "agent_id": 1, "enabled": True}
                ]
                mock_service.get_skill_by_id.return_value = {
                    "skill_id": 1,
                    "name": "skill1",
                    "description": "Desc",
                    "content": "# Content",
                    "params": {}
                }

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.get(
                    "/skills/instance/list?agent_id=1",
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 200
                data = response.json()
                assert "instances" in data
                assert len(data["instances"]) == 1
                # Verify enrichment
                instance = data["instances"][0]
                assert instance.get("skill_name") == "skill1"

    def test_list_instances_with_version(self, mocker):
        """Test listing instances with specific version."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.list_skill_instances.return_value = [
                    {"skill_id": 1, "agent_id": 1, "version_no": 5}
                ]
                mock_service.get_skill_by_id.return_value = {
                    "skill_id": 1,
                    "name": "skill1",
                    "description": "Desc",
                    "content": "# Content",
                    "params": {}
                }

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.get(
                    "/skills/instance/list?agent_id=1&version_no=5",
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 200


# ===== Get Skill Instance Endpoint Additional Tests =====
class TestGetSkillInstanceEndpointExtended:
    """Additional tests for GET /skills/instance endpoint."""

    def test_get_instance_with_enrichment(self, mocker):
        """Test instance retrieval with skill info enrichment."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.get_skill_instance.return_value = {
                    "skill_instance_id": 1,
                    "skill_id": 1,
                    "agent_id": 1,
                    "enabled": True,
                    "version_no": 0,
                    "config_values": {"instance_key": "instance_value"}
                }
                mock_service.get_skill_by_id.return_value = {
                    "skill_id": 1,
                    "name": "test_skill",
                    "description": "Test description",
                    "content": "# Test content",
                    "config_schemas": [{"name": "key", "type": "string"}],
                    "config_values": {"template_key": "template_value"}
                }

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.get(
                    "/skills/instance?agent_id=1&skill_id=1",
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 200
                data = response.json()
                # Verify enrichment
                assert data.get("skill_name") == "test_skill"
                assert data.get("skill_description") == "Test description"
                assert data.get("skill_content") == "# Test content"
                assert data.get("config_schemas") == [{"name": "key", "type": "string"}]
                # Endpoint uses template config_values as base, then merges instance params
                # Since instance_params comes from instance's config_values (which was overwritten by template),
                # the result is the template values
                assert data.get("config_values") == {"template_key": "template_value"}

    def test_get_instance_unauthorized(self, mocker):
        """Test instance retrieval without authorization."""
        from backend.apps.skill_app import UnauthorizedError
        with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
            mock_auth.side_effect = UnauthorizedError("No token")

            app = FastAPI()
            app.include_router(skill_app.router)
            client = TestClient(app)

            response = client.get(
                "/skills/instance?agent_id=1&skill_id=1",
                headers={"Authorization": "Bearer invalid"}
            )

            assert response.status_code == 401


# ===== Error Handling Extended Tests =====
class TestErrorHandlingExtended:
    """Additional error handling test scenarios."""

    def test_skill_exception_409_in_create(self, mocker):
        """Test SkillException with 'already exists' returns 409."""
        from backend.apps.skill_app import SkillException
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.create_skill.side_effect = SkillException("Skill 'duplicate' already exists")

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.post(
                    "/skills",
                    json={
                        "name": "duplicate",
                        "description": "Test",
                        "content": "# Test"
                    },
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 409

    def test_skill_exception_409_in_upload(self, mocker):
        """Test SkillException with 'already exists' in upload returns 409."""
        from backend.apps.skill_app import SkillException
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.create_skill_from_file.side_effect = SkillException("Skill 'zip_skill' already exists")

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                content = b"---\nname: zip_skill\ndescription: Desc\n---"
                response = client.post(
                    "/skills/upload",
                    files={"file": ("test.md", content, "text/markdown")},
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 409

    def test_unexpected_error_in_get_skill_instance(self, mocker):
        """Test unexpected error in get_skill_instance."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.get_skill_instance.side_effect = Exception("Unexpected error")

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.get(
                    "/skills/instance?agent_id=1&skill_id=1",
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 500

    def test_unexpected_error_in_list_instances(self, mocker):
        """Test unexpected error in list_skill_instances."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.list_skill_instances.side_effect = Exception("Unexpected error")

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.get(
                    "/skills/instance/list?agent_id=1",
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 500


# ===== Update Skill Endpoint Additional Tests =====
class TestUpdateSkillEndpointExtended:
    """Additional tests for PUT /skills/{skill_name} endpoint - field update variations."""

    def test_update_skill_with_tool_ids_and_tool_names(self, mocker):
        """Test update with both tool_ids and tool_names (both are ignored - returns 400)."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.put(
                    "/skills/test_skill",
                    json={"tool_ids": [1, 2], "tool_names": ["tool3", "tool4"]},
                    headers={"Authorization": "Bearer token123"}
                )

                # Tool_ids/tool_names are not handled - returns 400
                assert response.status_code == 400

    def test_update_skill_with_tool_names_only(self, mocker):
        """Test update with only tool_names (returns 400 - not supported)."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.put(
                    "/skills/test_skill",
                    json={"tool_names": ["tool5", "tool6"]},
                    headers={"Authorization": "Bearer token123"}
                )

                # Tool_names not supported - returns 400
                assert response.status_code == 400

    def test_update_skill_with_tags(self, mocker):
        """Test update skill with tags field."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.update_skill.return_value = {
                    "skill_id": 1,
                    "name": "test_skill",
                    "tags": ["tag1", "tag2"]
                }

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.put(
                    "/skills/test_skill",
                    json={"tags": ["tag1", "tag2"]},
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 200

    def test_update_skill_with_source(self, mocker):
        """Test update skill with source field."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.update_skill.return_value = {
                    "skill_id": 1,
                    "name": "test_skill",
                    "source": "partner"
                }

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.put(
                    "/skills/test_skill",
                    json={"source": "partner"},
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 200

    def test_update_skill_with_config_values(self, mocker):
        """Test update skill with config_values field."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.update_skill.return_value = {
                    "skill_id": 1,
                    "name": "test_skill",
                    "config_values": {"key": "value"}
                }

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.put(
                    "/skills/test_skill",
                    json={"config_values": {"key": "value"}},
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 200

    def test_update_skill_unauthorized(self, mocker):
        """Test update skill without authorization."""
        from backend.apps.skill_app import UnauthorizedError
        with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
            mock_auth.side_effect = UnauthorizedError("No token")

            app = FastAPI()
            app.include_router(skill_app.router)
            client = TestClient(app)

            response = client.put(
                "/skills/test_skill",
                json={"description": "Updated"},
                headers={"Authorization": "Bearer invalid"}
            )

            assert response.status_code == 401

    def test_update_skill_service_exception(self, mocker):
        """Test update skill with generic SkillException (non-404)."""
        from backend.apps.skill_app import SkillException
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.update_skill.side_effect = SkillException("Update failed")

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.put(
                    "/skills/test_skill",
                    json={"description": "Updated"},
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 400

    def test_update_skill_unexpected_error(self, mocker):
        """Test update skill with unexpected error."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.update_skill.side_effect = Exception("Unexpected error")

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.put(
                    "/skills/test_skill",
                    json={"description": "Updated"},
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 500


# ===== Delete Skill Endpoint Additional Tests =====
class TestDeleteSkillEndpointExtended:
    """Additional tests for DELETE /skills/{skill_name} endpoint."""

    def test_delete_skill_unauthorized(self, mocker):
        """Test delete skill without authorization."""
        from backend.apps.skill_app import UnauthorizedError
        with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
            mock_auth.side_effect = UnauthorizedError("No token")

            app = FastAPI()
            app.include_router(skill_app.router)
            client = TestClient(app)

            response = client.delete(
                "/skills/test_skill",
                headers={"Authorization": "Bearer invalid"}
            )

            assert response.status_code == 401

    def test_delete_skill_unexpected_error(self, mocker):
        """Test delete skill with unexpected error."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.delete_skill.side_effect = Exception("Unexpected error")

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.delete(
                    "/skills/test_skill",
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 500


# ===== Get Skill Endpoint Additional Tests =====
class TestGetSkillEndpointExtended:
    """Additional tests for GET /skills/{skill_name} endpoint."""

    def test_get_skill_service_exception(self, mocker):
        """Test get skill with SkillException."""
        from backend.apps.skill_app import SkillException
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            mock_service = MagicMock()
            mock_service_class.return_value = mock_service
            mock_service.get_skill.side_effect = SkillException("Service error")

            app = FastAPI()
            app.include_router(skill_app.router)
            client = TestClient(app)

            response = client.get("/skills/test_skill")

            assert response.status_code == 500

    def test_get_skill_unexpected_error(self, mocker):
        """Test get skill with unexpected error."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            mock_service = MagicMock()
            mock_service_class.return_value = mock_service
            mock_service.get_skill.side_effect = Exception("Unexpected error")

            app = FastAPI()
            app.include_router(skill_app.router)
            client = TestClient(app)

            response = client.get("/skills/test_skill")

            assert response.status_code == 500


# ===== Get Skill File Tree Endpoint Additional Tests =====
class TestGetSkillFileTreeEndpointExtended:
    """Additional tests for GET /skills/{skill_name}/files endpoint."""

    def test_get_file_tree_service_exception(self, mocker):
        """Test file tree with SkillException."""
        from backend.apps.skill_app import SkillException
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            mock_service = MagicMock()
            mock_service_class.return_value = mock_service
            mock_service.get_skill_file_tree.side_effect = SkillException("Service error")

            app = FastAPI()
            app.include_router(skill_app.router)
            client = TestClient(app)

            response = client.get("/skills/test_skill/files")

            assert response.status_code == 500

    def test_get_file_tree_unexpected_error(self, mocker):
        """Test file tree with unexpected error."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            mock_service = MagicMock()
            mock_service_class.return_value = mock_service
            mock_service.get_skill_file_tree.side_effect = Exception("Unexpected error")

            app = FastAPI()
            app.include_router(skill_app.router)
            client = TestClient(app)

            response = client.get("/skills/test_skill/files")

            assert response.status_code == 500


# ===== Get Skill File Content Endpoint Additional Tests =====
class TestGetSkillFileContentEndpointExtended:
    """Additional tests for GET /skills/{skill_name}/files/{file_path} endpoint."""

    def test_get_file_content_service_exception(self, mocker):
        """Test file content with SkillException."""
        from backend.apps.skill_app import SkillException
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            mock_service = MagicMock()
            mock_service_class.return_value = mock_service
            mock_service.get_skill_file_content.side_effect = SkillException("Service error")

            app = FastAPI()
            app.include_router(skill_app.router)
            client = TestClient(app)

            response = client.get("/skills/test_skill/files/README.md")

            assert response.status_code == 500

    def test_get_file_content_unexpected_error(self, mocker):
        """Test file content with unexpected error."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            mock_service = MagicMock()
            mock_service_class.return_value = mock_service
            mock_service.get_skill_file_content.side_effect = Exception("Unexpected error")

            app = FastAPI()
            app.include_router(skill_app.router)
            client = TestClient(app)

            response = client.get("/skills/test_skill/files/README.md")

            assert response.status_code == 500


# ===== Update Skill From File Endpoint Additional Tests =====
class TestUpdateSkillFromFileEndpointExtended:
    """Additional tests for PUT /skills/{skill_name}/upload endpoint."""

    def test_update_from_zip_file(self, mocker):
        """Test update skill from ZIP file."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.update_skill_from_file.return_value = {
                    "skill_id": 1,
                    "name": "updated_skill"
                }

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w') as zf:
                    zf.writestr("SKILL.md", "---\nname: updated_skill\ndescription: Updated\n---\n# Content")
                zip_buffer.seek(0)

                response = client.put(
                    "/skills/updated_skill/upload",
                    files={"file": ("skill.zip", zip_buffer.getvalue(), "application/zip")},
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 200

    def test_update_from_file_unauthorized(self, mocker):
        """Test update from file without authorization."""
        from backend.apps.skill_app import UnauthorizedError
        with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
            mock_auth.side_effect = UnauthorizedError("No token")

            app = FastAPI()
            app.include_router(skill_app.router)
            client = TestClient(app)

            content = b"---\nname: test\ndescription: Test\n---"
            response = client.put(
                "/skills/test/upload",
                files={"file": ("test.md", content, "text/markdown")},
                headers={"Authorization": "Bearer invalid"}
            )

            assert response.status_code == 401

    def test_update_from_file_service_exception(self, mocker):
        """Test update from file with generic SkillException."""
        from backend.apps.skill_app import SkillException
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.update_skill_from_file.side_effect = SkillException("Update failed")

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                content = b"---\nname: test\ndescription: Test\n---"
                response = client.put(
                    "/skills/test/upload",
                    files={"file": ("test.md", content, "text/markdown")},
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 400

    def test_update_from_file_unexpected_error(self, mocker):
        """Test update from file with unexpected error."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.update_skill_from_file.side_effect = Exception("Unexpected error")

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                content = b"---\nname: test\ndescription: Test\n---"
                response = client.put(
                    "/skills/test/upload",
                    files={"file": ("test.md", content, "text/markdown")},
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 500


# ===== Create Skill From File Endpoint Additional Tests =====
class TestCreateSkillFromFileEndpointExtended:
    """Additional tests for POST /skills/upload endpoint."""

    def test_upload_unauthorized(self, mocker):
        """Test upload without authorization."""
        from backend.apps.skill_app import UnauthorizedError
        with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
            mock_auth.side_effect = UnauthorizedError("No token")

            app = FastAPI()
            app.include_router(skill_app.router)
            client = TestClient(app)

            content = b"---\nname: test\ndescription: Test\n---"
            response = client.post(
                "/skills/upload",
                files={"file": ("test.md", content, "text/markdown")},
                headers={"Authorization": "Bearer invalid"}
            )

            assert response.status_code == 401

    def test_upload_service_exception(self, mocker):
        """Test upload with generic SkillException."""
        from backend.apps.skill_app import SkillException
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.create_skill_from_file.side_effect = SkillException("Upload failed")

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                content = b"---\nname: test\ndescription: Test\n---"
                response = client.post(
                    "/skills/upload",
                    files={"file": ("test.md", content, "text/markdown")},
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 400

    def test_upload_unexpected_error(self, mocker):
        """Test upload with unexpected error."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.create_skill_from_file.side_effect = Exception("Unexpected error")

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                content = b"---\nname: test\ndescription: Test\n---"
                response = client.post(
                    "/skills/upload",
                    files={"file": ("test.md", content, "text/markdown")},
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 500


# ===== Create Skill Endpoint Additional Tests =====
class TestCreateSkillEndpointExtended:
    """Additional tests for POST /skills endpoint."""

    def test_create_skill_unexpected_error(self, mocker):
        """Test create skill with unexpected error."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.create_skill.side_effect = Exception("Unexpected error")

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.post(
                    "/skills",
                    json={
                        "name": "test",
                        "description": "Test",
                        "content": "# Test"
                    },
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 500


# ===== Update Skill Instance Endpoint Error Handling Tests =====
class TestUpdateSkillInstanceEndpointErrorHandling:
    """Error handling tests for POST /skills/instance/update endpoint."""

    def test_update_instance_http_exception_propagation(self, mocker):
        """Test HTTPException is propagated from get_skill_by_id."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                # When get_skill_by_id returns None, HTTPException 404 is raised
                mock_service.get_skill_by_id.return_value = None

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.post(
                    "/skills/instance/update",
                    json={
                        "skill_id": 999,
                        "agent_id": 1,
                        "enabled": True
                    },
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 404

    def test_update_instance_unexpected_error(self, mocker):
        """Test update instance with unexpected error."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.get_skill_by_id.side_effect = Exception("Unexpected error")

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.post(
                    "/skills/instance/update",
                    json={
                        "skill_id": 1,
                        "agent_id": 1,
                        "enabled": True
                    },
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 500


# ===== List Skill Instances Endpoint Error Handling Tests =====
class TestListSkillInstancesEndpointErrorHandling:
    """Error handling tests for GET /skills/instance/list endpoint."""

    def test_list_instances_unauthorized(self, mocker):
        """Test list instances without authorization."""
        from backend.apps.skill_app import UnauthorizedError
        with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
            mock_auth.side_effect = UnauthorizedError("No token")

            app = FastAPI()
            app.include_router(skill_app.router)
            client = TestClient(app)

            response = client.get(
                "/skills/instance/list?agent_id=1",
                headers={"Authorization": "Bearer invalid"}
            )

            assert response.status_code == 401


# ===== Get Skill Instance Endpoint Error Handling Tests =====
class TestGetSkillInstanceEndpointErrorHandling:
    """Error handling tests for GET /skills/instance endpoint."""

    def test_get_instance_http_exception_propagation(self, mocker):
        """Test HTTPException is propagated when instance not found."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.get_skill_instance.return_value = None

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.get(
                    "/skills/instance?agent_id=1&skill_id=999",
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 404

    def test_get_instance_http_exception_from_service(self, mocker):
        """Test HTTPException from service layer is propagated."""
        from fastapi import HTTPException as FastAPIHTTPException
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.get_skill_instance.side_effect = FastAPIHTTPException(status_code=403, detail="Forbidden")

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.get(
                    "/skills/instance?agent_id=1&skill_id=1",
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 403


# ===== Update Skill Field Edge Case Tests =====
class TestUpdateSkillFieldEdgeCases:
    """Edge case tests for update skill field handling."""

    def test_update_skill_with_content_field(self, mocker):
        """Test update skill with content field (line 399)."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.update_skill.return_value = {
                    "skill_id": 1,
                    "name": "test_skill",
                    "content": "# Updated content"
                }

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.put(
                    "/skills/test_skill",
                    json={"content": "# Updated content"},
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 200

    def test_update_skill_with_tool_ids_only(self, mocker):
        """Test update skill with tool_ids only (returns 400 - not supported)."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.put(
                    "/skills/test_skill",
                    json={"tool_ids": [1, 2]},
                    headers={"Authorization": "Bearer token123"}
                )

                # Tool_ids not supported in update - returns 400
                assert response.status_code == 400


# ===== List Official Skills Endpoint Tests =====
class TestListOfficialSkillsEndpoint:
    """Test GET /skills/official endpoint."""

    def test_list_official_skills_success(self, mocker):
        """Test successful listing of official skills."""
        with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
            mock_auth.return_value = ("user123", "tenant123")
            with patch('backend.apps.skill_app.get_official_skills_with_status') as mock_func:
                mock_func.return_value = [
                    {"skill_id": 1, "name": "skill1", "source": "official", "status": "installable"},
                    {"skill_id": 2, "name": "skill2", "source": "official", "status": "installed"}
                ]

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.get(
                    "/skills/official",
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 200
                data = response.json()
                assert "skills" in data
                assert len(data["skills"]) == 2
                mock_func.assert_called_once_with(tenant_id="tenant123")

    def test_list_official_skills_empty(self, mocker):
        """Test listing official skills when none available."""
        with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
            mock_auth.return_value = ("user123", "tenant123")
            with patch('backend.apps.skill_app.get_official_skills_with_status') as mock_func:
                mock_func.return_value = []

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.get(
                    "/skills/official",
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 200
                data = response.json()
                assert data["skills"] == []

    def test_list_official_skills_unauthorized(self, mocker):
        """Test listing official skills without auth returns 500 (no explicit UnauthorizedError handler)."""
        from backend.apps.skill_app import UnauthorizedError
        with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
            mock_auth.side_effect = UnauthorizedError("No token")

            app = FastAPI()
            app.include_router(skill_app.router)
            client = TestClient(app)

            response = client.get("/skills/official")

            # Endpoint returns 500 because it doesn't catch UnauthorizedError explicitly
            assert response.status_code == 500

    def test_list_official_skills_super_admin_with_tenant_id(self, mocker):
        """Test super admin listing official skills for a specific tenant via tenant_id query param."""
        with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
            mock_auth.return_value = ("super_user", "super_tenant")
            with patch('backend.apps.skill_app.get_official_skills_with_status') as mock_func:
                mock_func.return_value = [
                    {"skill_id": 1, "name": "admin_skill", "source": "official", "status": "installable"}
                ]

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.get(
                    "/skills/official?tenant_id=target_tenant",
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 200
                data = response.json()
                assert "skills" in data
                assert len(data["skills"]) == 1
                # Verify the function was called with the target tenant_id, not super_tenant
                mock_func.assert_called_once_with(tenant_id="target_tenant")

    def test_list_official_skills_error(self, mocker):
        """Test listing official skills with error."""
        with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
            mock_auth.return_value = ("user123", "tenant123")
            with patch('backend.apps.skill_app.get_official_skills_with_status') as mock_func:
                mock_func.side_effect = Exception("Database error")

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.get(
                    "/skills/official",
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 500


# ===== Install Skills Endpoint Tests =====
class TestInstallSkillsEndpoint:
    """Test POST /skills/install endpoint."""

    def test_install_skills_success(self, mocker):
        """Test successful skill installation."""
        with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
            mock_auth.return_value = ("user123", "tenant123")
            with patch('services.skill_service.install_skills_from_zip_for_tenant') as mock_install:
                mock_install.return_value = ["skill1", "skill2"]

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.post(
                    "/skills/install",
                    json={"skill_names": ["skill1", "skill2"], "locale": "zh"},
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 200
                data = response.json()
                assert data["message"] == "Skills installed successfully"
                assert data["installed"] == ["skill1", "skill2"]
                assert data["total"] == 2
                mock_install.assert_called_once()
                call_kwargs = mock_install.call_args
                assert call_kwargs.kwargs["tenant_id"] == "tenant123"
                assert call_kwargs.kwargs["user_id"] == "user123"

    def test_install_skills_empty_list(self, mocker):
        """Test installing empty skill list."""
        with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
            mock_auth.return_value = ("user123", "tenant123")
            with patch('services.skill_service.install_skills_from_zip_for_tenant') as mock_install:
                mock_install.return_value = []

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.post(
                    "/skills/install",
                    json={"skill_names": []},
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 200
                data = response.json()
                assert data["total"] == 0

    def test_install_skills_unauthorized(self, mocker):
        """Test installing skills without auth returns 500 (no explicit UnauthorizedError handler)."""
        from backend.apps.skill_app import UnauthorizedError
        with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
            mock_auth.side_effect = UnauthorizedError("No token")

            app = FastAPI()
            app.include_router(skill_app.router)
            client = TestClient(app)

            response = client.post(
                "/skills/install",
                json={"skill_names": ["skill1"]}
            )

            # Endpoint returns 500 because it doesn't catch UnauthorizedError explicitly
            assert response.status_code == 500

    def test_install_skills_super_admin_with_tenant_id(self, mocker):
        """Test super admin installing skills for a specific tenant via tenant_id query param."""
        with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
            mock_auth.return_value = ("super_user", "super_tenant")
            with patch('services.skill_service.install_skills_from_zip_for_tenant') as mock_install:
                mock_install.return_value = ["skill1"]

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.post(
                    "/skills/install?tenant_id=target_tenant",
                    json={"skill_names": ["skill1"], "locale": "en"},
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 200
                data = response.json()
                assert data["message"] == "Skills installed successfully"
                assert data["installed"] == ["skill1"]
                # Verify the function was called with the target tenant_id, not super_tenant
                mock_install.assert_called_once()
                call_kwargs = mock_install.call_args
                assert call_kwargs.kwargs["tenant_id"] == "target_tenant"
                assert call_kwargs.kwargs["user_id"] == "super_user"

    def test_install_skills_error(self, mocker):
        """Test installing skills with error."""
        with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
            mock_auth.return_value = ("user123", "tenant123")
            with patch('services.skill_service.install_skills_from_zip_for_tenant') as mock_install:
                mock_install.side_effect = Exception("Installation failed")

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.post(
                    "/skills/install",
                    json={"skill_names": ["skill1"]},
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 500


# ===== Scan Skill Endpoint Tests =====
class TestScanSkillEndpoint:
    """Test GET /skills/scan_skill endpoint."""

    def test_scan_skill_success(self, mocker):
        """Test successful skill scan."""
        with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
            mock_auth.return_value = ("user123", "tenant123")
            async def mock_update(*args, **kwargs):
                return None
            with patch('backend.apps.skill_app.update_skill_list', side_effect=mock_update):
                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.get(
                    "/skills/scan_skill",
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "success"
                assert "message" in data

    def test_scan_skill_unauthorized(self, mocker):
        """Test scanning skills without auth returns 500 (no explicit UnauthorizedError handler)."""
        from backend.apps.skill_app import UnauthorizedError
        with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
            mock_auth.side_effect = UnauthorizedError("No token")

            app = FastAPI()
            app.include_router(skill_app.router)
            client = TestClient(app)

            response = client.get("/skills/scan_skill")

            # Endpoint returns 500 because it doesn't catch UnauthorizedError explicitly
            assert response.status_code == 500

    def test_scan_skill_error(self, mocker):
        """Test scanning skills with error."""
        with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
            mock_auth.return_value = ("user123", "tenant123")
            with patch('services.skill_service.update_skill_list', new_callable=AsyncMock) as mock_update:
                mock_update.side_effect = Exception("Scan failed")

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.get(
                    "/skills/scan_skill",
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 500


# ===== Create Skill Interactive Endpoint Tests =====
class TestCreateSkillInteractiveEndpoint:
    """Test POST /skills/create endpoint (nl2skill)."""

    def test_create_skill_interactive_success(self, mocker):
        """Test successful interactive skill creation."""
        with patch('backend.apps.skill_app.get_current_user_info') as mock_auth:
            mock_auth.return_value = ("user123", "tenant123", "zh")
            with patch('backend.apps.skill_app._build_model_config_from_tenant') as mock_model:
                mock_config = MagicMock()
                mock_model.return_value = mock_config
                with patch('backend.apps.skill_app.stream_skill_creation') as mock_stream:
                    mock_stream.return_value = ("task123", MagicMock())

                    app = FastAPI()
                    app.include_router(skill_app.skill_creator_router)
                    client = TestClient(app)

                    response = client.post(
                        "/skills/create",
                        json={"user_request": "Create a skill", "language": "zh", "complexity": "simple"},
                        headers={"Authorization": "Bearer token123"}
                    )

                    assert response.status_code == 200
                    assert response.headers.get("x-task-id") == "task123"

    def test_create_skill_interactive_unauthorized(self, mocker):
        """Test interactive skill creation without auth."""
        with patch('backend.apps.skill_app.get_current_user_info') as mock_auth:
            mock_auth.side_effect = Exception("Unauthorized")

            app = FastAPI()
            app.include_router(skill_app.skill_creator_router)
            client = TestClient(app)

            response = client.post(
                "/skills/create",
                json={"user_request": "Create a skill"}
            )

            assert response.status_code == 401


# ===== Stop Skill Creation Endpoint Tests =====
class TestStopSkillCreationEndpoint:
    """Test GET /skills/stop/{task_id} endpoint."""

    def test_stop_skill_creation_success(self, mocker):
        """Test successful stop skill creation."""
        with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
            mock_auth.return_value = ("user123", "tenant123")
            with patch('backend.apps.skill_app.skill_creation_task_manager') as mock_manager:
                mock_manager.stop_task.return_value = True

                app = FastAPI()
                app.include_router(skill_app.skill_creator_router)
                client = TestClient(app)

                response = client.get(
                    "/skills/stop/task123",
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "success"

    def test_stop_skill_creation_not_found(self, mocker):
        """Test stop skill creation when task not found."""
        with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
            mock_auth.return_value = ("user123", "tenant123")
            with patch('backend.apps.skill_app.skill_creation_task_manager') as mock_manager:
                mock_manager.stop_task.return_value = False

                app = FastAPI()
                app.include_router(skill_app.skill_creator_router)
                client = TestClient(app)

                response = client.get(
                    "/skills/stop/nonexistent",
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 404
                data = response.json()
                assert data["status"] == "not_found"

    def test_stop_skill_creation_unauthorized(self, mocker):
        """Test stop skill creation without auth."""
        with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
            mock_auth.side_effect = Exception("Unauthorized")

            app = FastAPI()
            app.include_router(skill_app.skill_creator_router)
            client = TestClient(app)

            response = client.get("/skills/stop/task123")

            assert response.status_code == 401


# ===== Update Skill Instance with config_values merge tests =====
class TestUpdateSkillInstanceWithConfigMerge:
    """Test config_values merge in update skill instance."""

    def test_update_instance_with_config_values_merge(self, mocker):
        """Test instance update with config_values merges with template defaults (lines 368-371)."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.get_skill_by_id.return_value = {
                    "skill_id": 1,
                    "name": "test_skill",
                    "description": "Test",
                    "content": "# Test",
                    "config_schemas": [{"name": "key1", "type": "string"}],
                    "config_values": {"template_key": "template_value"}
                }
                mock_service.create_or_update_skill_instance.return_value = {
                    "skill_id": 1,
                    "agent_id": 1,
                    "enabled": True,
                    "config_values": {"instance_key": "instance_value"}
                }

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.post(
                    "/skills/instance/update",
                    json={
                        "skill_id": 1,
                        "agent_id": 1,
                        "enabled": True
                    },
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 200
                data = response.json()
                assert "instance" in data


# ===== Update Skill with config_schemas tests =====
class TestUpdateSkillWithConfigSchemas:
    """Test update skill with config_schemas field."""

    def test_update_skill_with_config_schemas(self, mocker):
        """Test update skill with config_schemas (line 482)."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.update_skill.return_value = {
                    "skill_id": 1,
                    "name": "test_skill",
                    "config_schemas": {"param1": {"type": "string"}}
                }

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.put(
                    "/skills/test_skill",
                    json={"config_schemas": {"param1": {"type": "string"}}},
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 200


# ===== Update Skill with files tests =====
class TestUpdateSkillWithFiles:
    """Test update skill with files field."""

    def test_update_skill_with_files(self, mocker):
        """Test update skill with files (line 486)."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.update_skill.return_value = {
                    "skill_id": 1,
                    "name": "test_skill"
                }

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.put(
                    "/skills/test_skill",
                    json={
                        "files": [
                            {"path": "script.py", "content": "# script content"}
                        ]
                    },
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 200


# ===== Build Model Config From Tenant Tests =====
class TestBuildModelConfigFromTenant:
    """Test _build_model_config_from_tenant helper function (lines 532-553)."""

    def test_build_model_config_success(self, mocker):
        """Test successful model config building."""
        with patch('utils.config_utils.tenant_config_manager') as mock_config_mgr:
            with patch('utils.config_utils.get_model_name_from_config') as mock_get_model:
                mock_config_mgr.get_model_config.return_value = {
                    "display_name": "GPT-4",
                    "api_key": "test-key",
                    "base_url": "https://api.openai.com",
                    "model_factory": "openai"
                }
                mock_get_model.return_value = "gpt-4"

                from backend.apps.skill_app import _build_model_config_from_tenant
                config = _build_model_config_from_tenant("tenant123")

                assert config.cite_name == "GPT-4"
                assert config.api_key == "test-key"
                assert config.model_name == "gpt-4"
                assert config.url == "https://api.openai.com"
                assert config.temperature == 0.1
                assert config.top_p == 0.95
                assert config.ssl_verify == True
                assert config.model_factory == "openai"

    def test_build_model_config_missing_quick_config(self, mocker):
        """Test error when tenant has no LLM model configured."""
        with patch('utils.config_utils.tenant_config_manager') as mock_config_mgr:
            mock_config_mgr.get_model_config.return_value = None

            from backend.apps.skill_app import _build_model_config_from_tenant
            with pytest.raises(ValueError, match="No LLM model configured for tenant"):
                _build_model_config_from_tenant("tenant123")

    def test_build_model_config_empty_quick_config(self, mocker):
        """Test error when tenant has empty LLM model config."""
        with patch('utils.config_utils.tenant_config_manager') as mock_config_mgr:
            mock_config_mgr.get_model_config.return_value = {}

            from backend.apps.skill_app import _build_model_config_from_tenant
            with pytest.raises(ValueError, match="No LLM model configured for tenant"):
                _build_model_config_from_tenant("tenant123")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
