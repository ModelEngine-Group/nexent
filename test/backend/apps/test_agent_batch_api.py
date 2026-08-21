"""Unit tests for batch import/export API endpoints in backend/apps/agent_app.py.

Tests use FastAPI's TestClient against the agent_config_router with stubbed
services so the request/response shape can be validated without touching
the database or external services.
"""

import sys
import types
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict


# Path setup
sys.path.insert(
    0,
    __import__("os").path.join(__import__("os").path.dirname(__file__), "../../.."),
)


# ===== Stub third-party dependencies =====

# -- consts package --
consts_pkg = types.ModuleType("consts")
sys.modules["consts"] = consts_pkg

# consts.const
const_mod = types.ModuleType("consts.const")
const_mod.ASSET_OWNER_TENANT_ID = "asset_owner"
sys.modules["consts.const"] = const_mod
consts_pkg.const = const_mod

# consts.exceptions
exceptions_mod = types.ModuleType("consts.exceptions")


class ForbiddenError(Exception):
    pass


class SkillDuplicateError(Exception):
    def __init__(self, duplicate_names=None):
        self.duplicate_names = duplicate_names or []
        super().__init__()


class AppException(Exception):
    pass


class UnauthorizedError(Exception):
    pass


exceptions_mod.ForbiddenError = ForbiddenError
exceptions_mod.SkillDuplicateError = SkillDuplicateError
exceptions_mod.AppException = AppException
exceptions_mod.UnauthorizedError = UnauthorizedError
sys.modules["consts.exceptions"] = exceptions_mod
consts_pkg.exceptions = exceptions_mod


# -- consts.model --
# All models must be real Pydantic BaseModel subclasses so FastAPI can
# register routes and parse/serialize request/response bodies.

class _StubBase(BaseModel):
    """Base class for stub models that accept extra fields."""
    model_config = ConfigDict(extra="allow")


class AgentRequest(_StubBase):
    query: str = ""
    agent_id: Optional[int] = None
    is_debug: Optional[bool] = False


class NL2AgentRunRequest(_StubBase):
    query: str = ""


class AgentInfoRequest(_StubBase):
    agent_id: Optional[int] = None
    name: Optional[str] = None


class AgentIDRequest(BaseModel):
    agent_id: int


class ConversationResponse(_StubBase):
    code: int = 0
    message: str = "success"
    data: Any = None


class AgentImportRequest(_StubBase):
    agent_info: Any = None
    force_import: bool = False
    skills: Optional[list] = None


class AgentBatchExportRequest(BaseModel):
    agent_ids: List[int]


class AgentBatchImportResultItem(BaseModel):
    name: str
    display_name: Optional[str] = None
    success: bool
    error: Optional[str] = None


class AgentBatchImportResult(BaseModel):
    total: int
    success_count: int
    failed_count: int
    items: List[AgentBatchImportResultItem]


class AgentNameBatchCheckItem(BaseModel):
    name: str
    display_name: Optional[str] = None
    agent_id: Optional[int] = None


class AgentNameBatchCheckRequest(BaseModel):
    items: List[AgentNameBatchCheckItem]


class AgentNameBatchRegenerateItem(BaseModel):
    name: str
    display_name: Optional[str] = None
    task_description: Optional[str] = ""
    agent_id: Optional[int] = None


class AgentNameBatchRegenerateRequest(BaseModel):
    items: List[AgentNameBatchRegenerateItem]


class VersionPublishRequest(_StubBase):
    version_name: Optional[str] = None
    release_note: Optional[str] = None
    publish_as_a2a: bool = False


class VersionListItemResponse(_StubBase):
    id: int = 0
    version_no: int = 0
    status: str = "RELEASED"


class VersionListResponse(BaseModel):
    items: List[VersionListItemResponse] = []
    total: int = 0


class VersionDetailResponse(_StubBase):
    id: int = 0
    version_no: int = 0
    status: str = "RELEASED"


class VersionRollbackRequest(_StubBase):
    version_name: Optional[str] = None
    release_note: Optional[str] = None


class VersionStatusRequest(BaseModel):
    status: str


class VersionUpdateRequest(_StubBase):
    version_name: Optional[str] = None
    release_note: Optional[str] = None


class VersionCompareRequest(BaseModel):
    version_no_a: int
    version_no_b: int


class CurrentVersionResponse(_StubBase):
    version_no: int = 0
    status: str = "RELEASED"


model_mod = types.ModuleType("consts.model")
model_mod.AgentRequest = AgentRequest
model_mod.AgentInfoRequest = AgentInfoRequest
model_mod.AgentIDRequest = AgentIDRequest
model_mod.ConversationResponse = ConversationResponse
model_mod.AgentImportRequest = AgentImportRequest
model_mod.AgentBatchExportRequest = AgentBatchExportRequest
model_mod.AgentBatchImportResult = AgentBatchImportResult
model_mod.AgentBatchImportResultItem = AgentBatchImportResultItem
model_mod.AgentNameBatchCheckRequest = AgentNameBatchCheckRequest
model_mod.AgentNameBatchCheckItem = AgentNameBatchCheckItem
model_mod.AgentNameBatchRegenerateRequest = AgentNameBatchRegenerateRequest
model_mod.AgentNameBatchRegenerateItem = AgentNameBatchRegenerateItem
model_mod.VersionPublishRequest = VersionPublishRequest
model_mod.VersionListResponse = VersionListResponse
model_mod.VersionListItemResponse = VersionListItemResponse
model_mod.VersionDetailResponse = VersionDetailResponse
model_mod.VersionRollbackRequest = VersionRollbackRequest
model_mod.VersionStatusRequest = VersionStatusRequest
model_mod.CurrentVersionResponse = CurrentVersionResponse
model_mod.VersionCompareRequest = VersionCompareRequest
model_mod.VersionUpdateRequest = VersionUpdateRequest
model_mod.NL2AgentRunRequest = NL2AgentRunRequest
sys.modules["consts.model"] = model_mod
consts_pkg.model = model_mod


# -- services package --
services_pkg = types.ModuleType("services")
sys.modules["services"] = services_pkg

# services.agent_service
agent_service_mod = types.ModuleType("services.agent_service")

# The two functions under test — pre-create as AsyncMock with defaults
agent_service_mod.export_agents_batch_impl = AsyncMock(
    return_value={"data": b"fake-zip-data", "filename": "agents_batch_export.zip"}
)
agent_service_mod.import_agents_batch_impl = AsyncMock(
    return_value={
        "total": 2,
        "success_count": 2,
        "failed_count": 0,
        "items": [
            {"name": "agent1", "display_name": "Agent 1", "success": True, "error": None},
            {"name": "agent2", "display_name": "Agent 2", "success": True, "error": None},
        ],
    }
)

_all_agent_service_funcs = [
    "get_agent_info_impl",
    "get_creating_sub_agent_info_impl",
    "update_agent_info_impl",
    "delete_agent_impl",
    "export_agent_impl",
    "import_agent_impl",
    "check_agent_name_conflict_batch_impl",
    "regenerate_agent_name_batch_impl",
    "list_all_agent_info_impl",
    "run_agent_stream",
    "stop_agent_tasks",
    "get_agent_call_relationship_impl",
    "clear_agent_new_mark_impl",
    "get_agent_by_name_impl",
    "export_agent_with_skills_impl",
    "import_agent_with_skills_impl",
]
for _name in _all_agent_service_funcs:
    setattr(agent_service_mod, _name, MagicMock())

sys.modules["services.agent_service"] = agent_service_mod
services_pkg.agent_service = agent_service_mod

# services.asset_owner_visibility
asset_owner_mod = types.ModuleType("services.asset_owner_visibility")
asset_owner_mod.apply_agent_detail_prompt_visibility = MagicMock()
sys.modules["services.asset_owner_visibility"] = asset_owner_mod
services_pkg.asset_owner_visibility = asset_owner_mod

# services.prompt_service
prompt_service_mod = types.ModuleType("services.prompt_service")
prompt_service_mod.generate_guardrail_rules_impl = MagicMock()
sys.modules["services.prompt_service"] = prompt_service_mod
services_pkg.prompt_service = prompt_service_mod

# services.nl2agent_service
nl2agent_service_mod = types.ModuleType("services.nl2agent_service")
nl2agent_service_mod.create_nl2agent_stream = MagicMock()
sys.modules["services.nl2agent_service"] = nl2agent_service_mod
services_pkg.nl2agent_service = nl2agent_service_mod

# services.agent_version_service
agent_version_mod = types.ModuleType("services.agent_version_service")
_version_funcs = [
    "publish_version_impl",
    "get_version_list_impl",
    "get_version_impl",
    "get_version_detail_impl",
    "_get_version_detail_or_draft",
    "rollback_version_impl",
    "update_version_status_impl",
    "update_version_impl",
    "delete_version_impl",
    "get_current_version_impl",
    "compare_versions_impl",
    "list_published_agents_impl",
]
for _name in _version_funcs:
    setattr(agent_version_mod, _name, MagicMock())
sys.modules["services.agent_version_service"] = agent_version_mod
services_pkg.agent_version_service = agent_version_mod

# -- utils.auth_utils --
auth_utils_mod = types.ModuleType("utils.auth_utils")
auth_utils_mod.get_current_user_info = MagicMock(
    return_value=("user1", "tenant1", "en")
)
auth_utils_mod.get_current_user_id = MagicMock(
    return_value=("user1", "tenant1")
)
sys.modules["utils.auth_utils"] = auth_utils_mod

# Also register under backend.utils.auth_utils for safety
backend_utils_pkg = types.ModuleType("backend.utils")
sys.modules["backend.utils"] = backend_utils_pkg
backend_utils_pkg.auth_utils = auth_utils_mod
sys.modules["backend.utils.auth_utils"] = auth_utils_mod


# Default return values for resetting mocks between tests
_EXPORT_DEFAULT = {"data": b"fake-zip-data", "filename": "agents_batch_export.zip"}
_IMPORT_DEFAULT = {
    "total": 2,
    "success_count": 2,
    "failed_count": 0,
    "items": [
        {"name": "agent1", "display_name": "Agent 1", "success": True, "error": None},
        {"name": "agent2", "display_name": "Agent 2", "success": True, "error": None},
    ],
}


@pytest.fixture
def client():
    """Build a TestClient with mocked services for batch API tests.

    Resets the AsyncMock state before each test so call counts and
    side_effects do not leak across tests.
    """
    from apps import agent_app

    export_mock = agent_service_mod.export_agents_batch_impl
    import_mock = agent_service_mod.import_agents_batch_impl

    export_mock.reset_mock()
    import_mock.reset_mock()

    export_mock.return_value = _EXPORT_DEFAULT
    export_mock.side_effect = None
    import_mock.return_value = _IMPORT_DEFAULT
    import_mock.side_effect = None

    app = FastAPI()
    app.include_router(agent_app.agent_config_router)
    cli = TestClient(app, raise_server_exceptions=False)
    return cli, {
        "export": export_mock,
        "import": import_mock,
    }


class TestExportAgentsBatchApi:
    """Tests for POST /agent/export/batch — export_agents_batch_api."""

    def test_export_batch_success(self, client):
        """成功导出，验证返回 ZIP 流及正确的响应头。"""
        cli, svc = client
        svc["export"].return_value = {
            "data": b"fake-zip-data",
            "filename": "custom_name.zip",
        }

        response = cli.post(
            "/agent/export/batch",
            json={"agent_ids": [1, 2, 3]},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        assert "attachment" in response.headers.get("content-disposition", "")
        assert "custom_name.zip" in response.headers.get("content-disposition", "")
        assert response.content == b"fake-zip-data"
        svc["export"].assert_awaited_once()

    def test_export_batch_empty_ids(self, client):
        """空 agent_ids 列表，应返回 400。"""
        cli, svc = client

        response = cli.post(
            "/agent/export/batch",
            json={"agent_ids": []},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 400
        assert "agent_id" in response.json()["detail"].lower()
        svc["export"].assert_not_awaited()

    def test_export_batch_value_error(self, client):
        """服务层抛 ValueError，export_agents_batch_api 将其作为通用
        Exception 捕获，返回 500。"""
        cli, svc = client
        svc["export"].side_effect = ValueError("invalid agent id")

        response = cli.post(
            "/agent/export/batch",
            json={"agent_ids": [1]},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 500
        svc["export"].assert_awaited_once()

    def test_export_batch_http_exception(self, client):
        """服务层抛 HTTPException，应透传状态码。"""
        cli, svc = client
        svc["export"].side_effect = HTTPException(
            status_code=403, detail="forbidden"
        )

        response = cli.post(
            "/agent/export/batch",
            json={"agent_ids": [1]},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 403
        assert response.json()["detail"] == "forbidden"
        svc["export"].assert_awaited_once()

    def test_export_batch_generic_error(self, client):
        """服务层抛通用异常，应返回 500。"""
        cli, svc = client
        svc["export"].side_effect = RuntimeError("unexpected failure")

        response = cli.post(
            "/agent/export/batch",
            json={"agent_ids": [1]},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 500
        svc["export"].assert_awaited_once()

    def test_export_batch_default_filename(self, client):
        """服务层返回值中无 filename 时，使用默认文件名。"""
        cli, svc = client
        svc["export"].return_value = {"data": b"fake-zip-data"}

        response = cli.post(
            "/agent/export/batch",
            json={"agent_ids": [1]},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200
        assert "agents_batch_export.zip" in response.headers.get(
            "content-disposition", ""
        )


class TestImportAgentsBatchApi:
    """Tests for POST /agent/import/batch — import_agents_batch_api."""

    def test_import_batch_success(self, client):
        """成功导入，验证返回摘要结构。"""
        cli, svc = client
        svc["import"].return_value = {
            "total": 2,
            "success_count": 2,
            "failed_count": 0,
            "items": [
                {
                    "name": "agent1",
                    "display_name": "Agent 1",
                    "success": True,
                    "error": None,
                },
                {
                    "name": "agent2",
                    "display_name": "Agent 2",
                    "success": True,
                    "error": None,
                },
            ],
        }

        zip_content = b"PK\x03\x04" + b"fake-zip-content"
        response = cli.post(
            "/agent/import/batch",
            files={"file": ("agents.zip", zip_content, "application/zip")},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert body["success_count"] == 2
        assert body["failed_count"] == 0
        assert len(body["items"]) == 2
        assert body["items"][0]["success"] is True
        svc["import"].assert_awaited_once()

    def test_import_batch_empty_file(self, client):
        """空 ZIP 文件，应返回 400。"""
        cli, svc = client

        response = cli.post(
            "/agent/import/batch",
            files={"file": ("empty.zip", b"", "application/zip")},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()
        svc["import"].assert_not_awaited()

    def test_import_batch_value_error(self, client):
        """服务层抛 ValueError，应返回 400。"""
        cli, svc = client
        svc["import"].side_effect = ValueError("invalid zip structure")

        zip_content = b"PK\x03\x04" + b"fake-zip-content"
        response = cli.post(
            "/agent/import/batch",
            files={"file": ("agents.zip", zip_content, "application/zip")},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 400
        assert "invalid zip structure" in response.json()["detail"]
        svc["import"].assert_awaited_once()

    def test_import_batch_http_exception(self, client):
        """服务层抛 HTTPException，应透传。"""
        cli, svc = client
        svc["import"].side_effect = HTTPException(
            status_code=403, detail="permission denied"
        )

        zip_content = b"PK\x03\x04" + b"fake-zip-content"
        response = cli.post(
            "/agent/import/batch",
            files={"file": ("agents.zip", zip_content, "application/zip")},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 403
        assert response.json()["detail"] == "permission denied"
        svc["import"].assert_awaited_once()

    def test_import_batch_generic_error(self, client):
        """服务层抛通用异常，应返回 500。"""
        cli, svc = client
        svc["import"].side_effect = RuntimeError("disk write failed")

        zip_content = b"PK\x03\x04" + b"fake-zip-content"
        response = cli.post(
            "/agent/import/batch",
            files={"file": ("agents.zip", zip_content, "application/zip")},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 500
        svc["import"].assert_awaited_once()

    def test_import_batch_partial_failure(self, client):
        """部分 agent 导入失败，应在摘要中体现。"""
        cli, svc = client
        svc["import"].return_value = {
            "total": 3,
            "success_count": 2,
            "failed_count": 1,
            "items": [
                {
                    "name": "agent1",
                    "display_name": "Agent 1",
                    "success": True,
                    "error": None,
                },
                {
                    "name": "agent2",
                    "display_name": "Agent 2",
                    "success": True,
                    "error": None,
                },
                {
                    "name": "agent3",
                    "display_name": "Agent 3",
                    "success": False,
                    "error": "skill conflict",
                },
            ],
        }

        zip_content = b"PK\x03\x04" + b"fake-zip-content"
        response = cli.post(
            "/agent/import/batch",
            files={"file": ("agents.zip", zip_content, "application/zip")},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 3
        assert body["success_count"] == 2
        assert body["failed_count"] == 1
        assert body["items"][2]["success"] is False
        assert body["items"][2]["error"] == "skill conflict"

    def test_import_batch_missing_file(self, client):
        """未上传文件，应返回 422。"""
        cli, svc = client

        response = cli.post(
            "/agent/import/batch",
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 422
        svc["import"].assert_not_awaited()