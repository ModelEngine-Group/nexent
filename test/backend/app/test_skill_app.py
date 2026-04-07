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
from unittest.mock import patch, MagicMock
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

# Mock ToolConfig from agent_model
nexent_core_agents_agent_model_mock.ToolConfig = type('ToolConfig', (), {})
nexent_core_agents_agent_model_mock.ModelConfig = type('ModelConfig', (), {})

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
sys.modules['consts'] = consts_mock
sys.modules['consts.exceptions'] = consts_exceptions_mock
sys.modules['consts.model'] = consts_model_mock

class SkillException(Exception):
    pass
consts_exceptions_mock.SkillException = SkillException
consts_exceptions_mock.UnauthorizedError = type('UnauthorizedError', (Exception,), {})

# Use real Pydantic model for SkillInstanceInfoRequest
consts_model_mock.BaseModel = BaseModel
consts_model_mock.SkillInstanceInfoRequest = SkillInstanceInfoRequest

# Mock services
services_mock = types.ModuleType('services')
services_skill_service_mock = types.ModuleType('services.skill_service')
sys.modules['services'] = services_mock
sys.modules['services.skill_service'] = services_skill_service_mock

class MockSkillService:
    def __init__(self):
        self.repository = MagicMock()
        self.skill_manager = MagicMock()
services_skill_service_mock.SkillService = MockSkillService
services_skill_service_mock.get_skill_manager = MagicMock()

# Mock utils
utils_mock = types.ModuleType('utils')
utils_auth_utils_mock = types.ModuleType('utils.auth_utils')
sys.modules['utils'] = utils_mock
sys.modules['utils.auth_utils'] = utils_auth_utils_mock
utils_auth_utils_mock.get_current_user_id = MagicMock(return_value=("user123", "tenant123"))
utils_auth_utils_mock.get_current_user_info = MagicMock(return_value=("user123", "tenant123", "zh"))

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

            response = client.get("/skills")

            assert response.status_code == 200
            data = response.json()
            assert "skills" in data
            assert len(data["skills"]) == 2

    def test_list_skills_empty(self, mocker):
        """Test listing skills when none exist."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            mock_service = MagicMock()
            mock_service_class.return_value = mock_service
            mock_service.list_skills.return_value = []

            app = FastAPI()
            app.include_router(skill_app.router)
            client = TestClient(app)

            response = client.get("/skills")

            assert response.status_code == 200
            data = response.json()
            assert data["skills"] == []

    def test_list_skills_error(self, mocker):
        """Test listing skills when service throws exception."""
        from backend.apps.skill_app import SkillException
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            mock_service = MagicMock()
            mock_service_class.return_value = mock_service
            mock_service.list_skills.side_effect = SkillException("Database error")

            app = FastAPI()
            app.include_router(skill_app.router)
            client = TestClient(app)

            response = client.get("/skills")

            assert response.status_code == 500


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
        """Test skill creation with tool names."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.repository.get_tool_ids_by_names.return_value = [1, 2]
                mock_service.create_skill.return_value = {
                    "skill_id": 1,
                    "name": "tool_skill",
                    "description": "With tools"
                }

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

                assert response.status_code == 201
                mock_service.repository.get_tool_ids_by_names.assert_called_once()

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
        with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
            mock_auth.return_value = ("user123", "tenant123")

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
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            mock_service = MagicMock()
            mock_service_class.return_value = mock_service
            mock_service.list_skills.side_effect = Exception("Unexpected error")

            app = FastAPI()
            app.include_router(skill_app.router)
            client = TestClient(app)

            response = client.get("/skills")

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
                    "version_no": 0
                }
                mock_service.get_skill_by_id.return_value = {
                    "skill_id": 1,
                    "name": "test_skill",
                    "description": "Test description",
                    "content": "# Test content",
                    "params": {"key": "value"}
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
                assert data.get("skill_params") == {"key": "value"}

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
        """Test update with both tool_ids and tool_names (tool_names takes precedence)."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.repository.get_tool_ids_by_names.return_value = [3, 4]
                mock_service.update_skill.return_value = {
                    "skill_id": 1,
                    "name": "test_skill",
                    "tool_ids": [3, 4]
                }

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.put(
                    "/skills/test_skill",
                    json={"tool_ids": [1, 2], "tool_names": ["tool3", "tool4"]},
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 200
                # tool_names should take precedence
                mock_service.repository.get_tool_ids_by_names.assert_called_once_with(["tool3", "tool4"], "tenant123")

    def test_update_skill_with_tool_names_only(self, mocker):
        """Test update with only tool_names (converted to tool_ids)."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.repository.get_tool_ids_by_names.return_value = [5, 6]
                mock_service.update_skill.return_value = {
                    "skill_id": 1,
                    "name": "test_skill",
                    "tool_ids": [5, 6]
                }

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.put(
                    "/skills/test_skill",
                    json={"tool_names": ["tool5", "tool6"]},
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 200

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

    def test_update_skill_with_params(self, mocker):
        """Test update skill with params field."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.update_skill.return_value = {
                    "skill_id": 1,
                    "name": "test_skill",
                    "params": {"key": "value"}
                }

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.put(
                    "/skills/test_skill",
                    json={"params": {"key": "value"}},
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
        """Test update skill with tool_ids only (line 405)."""
        with patch('backend.apps.skill_app.SkillService') as mock_service_class:
            with patch('backend.apps.skill_app.get_current_user_id') as mock_auth:
                mock_auth.return_value = ("user123", "tenant123")
                mock_service = MagicMock()
                mock_service_class.return_value = mock_service
                mock_service.update_skill.return_value = {
                    "skill_id": 1,
                    "name": "test_skill",
                    "tool_ids": [1, 2]
                }

                app = FastAPI()
                app.include_router(skill_app.router)
                client = TestClient(app)

                response = client.put(
                    "/skills/test_skill",
                    json={"tool_ids": [1, 2]},
                    headers={"Authorization": "Bearer token123"}
                )

                assert response.status_code == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
