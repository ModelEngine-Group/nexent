"""Unit tests for repository import precheck."""

import sys
import types
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

sys.modules.setdefault("sqlalchemy", MagicMock())
sys.modules.setdefault("sqlalchemy.dialects", MagicMock())
sys.modules.setdefault("sqlalchemy.dialects.postgresql", MagicMock())

sys.modules.setdefault("database.skill_db", MagicMock())
sys.modules.setdefault("database.knowledge_db", MagicMock())
sys.modules.setdefault("database.model_management_db", MagicMock())
sys.modules.setdefault("database.remote_mcp_db", MagicMock())
sys.modules.setdefault("database.tool_db", MagicMock())

_consts_model = types.ModuleType("consts.model")


class _ModelConnectStatusEnum(Enum):
    AVAILABLE = "available"

    @classmethod
    def get_value(cls, status):
        return status or cls.AVAILABLE.value


class _RepositoryImportRequirementItem(BaseModel):
    type: str
    key: str
    name: str
    description: str | None = None
    available: bool
    reason_code: str | None = None


class _RepositoryImportPrecheckResponse(BaseModel):
    agent_repository_id: int
    display_name: str
    total_count: int
    available_count: int
    percent: int
    has_abnormal: bool
    items: list


class _ToolSourceEnum(Enum):
    MCP = "mcp"


_consts_model.ModelConnectStatusEnum = _ModelConnectStatusEnum
_consts_model.RepositoryImportRequirementItem = _RepositoryImportRequirementItem
_consts_model.RepositoryImportPrecheckResponse = _RepositoryImportPrecheckResponse
_consts_model.ToolSourceEnum = _ToolSourceEnum
sys.modules["consts.model"] = _consts_model

from services.repository_import_precheck import build_repository_import_precheck


def _snapshot(
    *,
    model_name: str = "gpt-5-mini",
    tools: list | None = None,
    mcp_info: list | None = None,
    skills: list | None = None,
):
    return SimpleNamespace(
        agent_id=1,
        agent_info={
            "1": {
                "agent_id": 1,
                "name": "writer",
                "description": "desc",
                "business_description": "biz",
                "max_steps": 5,
                "provide_run_summary": False,
                "enabled": True,
                "tools": tools or [],
                "managed_agents": [],
                "model_name": model_name,
                "skill_names": [],
            }
        },
        mcp_info=mcp_info or [],
        skills=skills,
    )


@patch("services.repository_import_precheck.skill_db.list_skills")
@patch("services.repository_import_precheck.query_all_tools")
@patch("services.repository_import_precheck.get_mcp_server_by_name_and_tenant")
@patch("services.repository_import_precheck.get_knowledge_record")
@patch("services.repository_import_precheck.get_knowledge_name_map_by_index_names")
@patch("services.repository_import_precheck.get_model_by_model_id")
@patch("services.repository_import_precheck.get_model_id_by_display_name")
def test_build_precheck_all_available(
    mock_get_model_id,
    mock_get_model_by_id,
    mock_kb_name_map,
    mock_kb_record,
    mock_mcp_url,
    mock_query_tools,
    mock_list_skills,
):
    mock_get_model_id.return_value = 7
    mock_get_model_by_id.return_value = {"connect_status": "available"}
    mock_kb_name_map.return_value = {"kb_index": "Brand KB"}
    mock_kb_record.return_value = {"knowledge_describe": "Brand tone reference"}
    mock_mcp_url.return_value = "http://mcp.local"
    mock_query_tools.return_value = [{
        "class_name": "KnowledgeBaseSearchTool",
        "source": "local",
        "is_available": True,
    }]
    mock_list_skills.return_value = []

    snapshot = _snapshot(
        tools=[{
            "class_name": "KnowledgeBaseSearchTool",
            "source": "local",
            "name": "knowledge_base_search",
            "params": {"index_names": ["kb_index"]},
        }],
        mcp_info=[SimpleNamespace(
            mcp_server_name="search-mcp",
            mcp_url="http://x",
        )],
        skills=[SimpleNamespace(skill_name="copy-skill", skill_zip_base64="e30=")],
    )

    result = build_repository_import_precheck(
        agent_repository_id=42,
        display_name="Writer",
        snapshot=snapshot,
        tenant_id="tenant_a",
    )

    assert result.percent == 100
    assert result.has_abnormal is False
    assert result.available_count == result.total_count


@patch("services.repository_import_precheck.skill_db.list_skills")
@patch("services.repository_import_precheck.query_all_tools")
@patch("services.repository_import_precheck.get_model_by_model_id")
@patch("services.repository_import_precheck.get_model_id_by_display_name")
def test_build_precheck_model_unavailable(
    mock_get_model_id,
    mock_get_model_by_id,
    mock_query_tools,
    mock_list_skills,
):
    mock_get_model_id.return_value = None
    mock_query_tools.return_value = []
    mock_list_skills.return_value = []

    result = build_repository_import_precheck(
        agent_repository_id=1,
        display_name="Writer",
        snapshot=_snapshot(),
        tenant_id="tenant_a",
    )

    model_items = [item for item in result.items if item.type == "model"]
    assert len(model_items) == 1
    assert model_items[0].available is False
    assert model_items[0].reason_code == "model_unavailable"


@patch("services.repository_import_precheck.skill_db.list_skills")
@patch("services.repository_import_precheck.query_all_tools")
@patch("services.repository_import_precheck.get_knowledge_record")
@patch("services.repository_import_precheck.get_knowledge_name_map_by_index_names")
@patch("services.repository_import_precheck.get_model_by_model_id")
@patch("services.repository_import_precheck.get_model_id_by_display_name")
def test_build_precheck_kb_not_found(
    mock_get_model_id,
    mock_get_model_by_id,
    mock_kb_name_map,
    mock_kb_record,
    mock_query_tools,
    mock_list_skills,
):
    mock_get_model_id.return_value = 1
    mock_get_model_by_id.return_value = {"connect_status": "available"}
    mock_kb_name_map.return_value = {"missing_index": "Missing KB"}
    mock_kb_record.return_value = {}
    mock_query_tools.return_value = [{
        "class_name": "KnowledgeBaseSearchTool",
        "source": "local",
        "is_available": True,
    }]
    mock_list_skills.return_value = []

    snapshot = _snapshot(tools=[{
        "class_name": "KnowledgeBaseSearchTool",
        "source": "local",
        "name": "knowledge_base_search",
        "params": {"index_names": ["missing_index"]},
    }])

    result = build_repository_import_precheck(
        agent_repository_id=1,
        display_name="Writer",
        snapshot=snapshot,
        tenant_id="tenant_a",
    )

    kb_items = [item for item in result.items if item.type == "knowledge_base"]
    assert len(kb_items) == 1
    assert kb_items[0].available is False
    assert kb_items[0].reason_code == "kb_not_found"


@patch("services.repository_import_precheck.skill_db.list_skills")
@patch("services.repository_import_precheck.query_all_tools")
@patch("services.repository_import_precheck.get_mcp_server_by_name_and_tenant")
@patch("services.repository_import_precheck.get_model_by_model_id")
@patch("services.repository_import_precheck.get_model_id_by_display_name")
def test_build_precheck_mcp_not_found(
    mock_get_model_id,
    mock_get_model_by_id,
    mock_mcp_url,
    mock_query_tools,
    mock_list_skills,
):
    mock_get_model_id.return_value = 1
    mock_get_model_by_id.return_value = {"connect_status": "available"}
    mock_mcp_url.return_value = None
    mock_query_tools.return_value = []
    mock_list_skills.return_value = []

    snapshot = _snapshot(mcp_info=[SimpleNamespace(
        mcp_server_name="missing-mcp",
        mcp_url="http://x",
    )])

    result = build_repository_import_precheck(
        agent_repository_id=1,
        display_name="Writer",
        snapshot=snapshot,
        tenant_id="tenant_a",
    )

    mcp_items = [item for item in result.items if item.type == "mcp"]
    assert len(mcp_items) == 1
    assert mcp_items[0].available is False
    assert mcp_items[0].reason_code == "mcp_not_found"


@patch("services.repository_import_precheck.skill_db.list_skills")
@patch("services.repository_import_precheck.query_all_tools")
@patch("services.repository_import_precheck.get_model_by_model_id")
@patch("services.repository_import_precheck.get_model_id_by_display_name")
def test_build_precheck_skill_duplicate(
    mock_get_model_id,
    mock_get_model_by_id,
    mock_query_tools,
    mock_list_skills,
):
    mock_get_model_id.return_value = 1
    mock_get_model_by_id.return_value = {"connect_status": "available"}
    mock_query_tools.return_value = []
    mock_list_skills.return_value = [{"name": "dup-skill"}]

    snapshot = _snapshot(
        skills=[SimpleNamespace(skill_name="dup-skill", skill_zip_base64="e30=")],
    )

    result = build_repository_import_precheck(
        agent_repository_id=1,
        display_name="Writer",
        snapshot=snapshot,
        tenant_id="tenant_a",
    )

    skill_items = [item for item in result.items if item.type == "skill"]
    assert len(skill_items) == 1
    assert skill_items[0].available is False
    assert skill_items[0].reason_code == "skill_duplicate"
