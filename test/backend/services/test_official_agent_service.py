"""Unit tests for official agent listing service."""

import json
import sys
import types
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, model_validator

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# Mock consts.model before importing the service under test so the module stays
# isolated from other test files that install their own fake consts.model.
consts_model = types.ModuleType("consts.model")


class _ModelConnectStatusEnum(Enum):
    AVAILABLE = "available"


class _KnowledgeBaseSeedDoc(BaseModel):
    file_name: str
    content: Optional[str] = None
    file_path: Optional[str] = None


class _ProcessParams(BaseModel):
    chunking_strategy: Optional[str] = "basic"
    source_type: str
    index_name: str
    authorization: Optional[str] = None
    model_id: Optional[int] = None


class _KnowledgeBaseSeed(BaseModel):
    logical_index_name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    documents: List[_KnowledgeBaseSeedDoc] = []


class _ToolConfig(BaseModel):
    class_name: str
    name: Optional[str] = None
    params: Dict[str, Any] = {}
    source: str = "local"


class _ExportAndImportAgentInfo(BaseModel):
    name: str
    display_name: Optional[str] = None
    tools: List[_ToolConfig] = []
    skill_names: Optional[List[str]] = None
    model_ids: Optional[List[int]] = None


class _MCPInfo(BaseModel):
    mcp_server_name: str
    mcp_url: str


class _OfficialAgentBundle(BaseModel):
    name: Optional[str] = None
    agent_id: int
    agent_info: Dict[str, _ExportAndImportAgentInfo] = {}
    mcp_info: List[_MCPInfo] = []
    skills: Optional[List] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    tags: List[str] = []
    version_label: Optional[str] = None
    knowledge_bases: List[_KnowledgeBaseSeed] = []

    @model_validator(mode="after")
    def _derive_card_fields(self):
        root_agent = self.agent_info.get(str(self.agent_id))
        root_name = getattr(root_agent, "name", None) if root_agent else None
        root_display_name = (
            getattr(root_agent, "display_name", None) if root_agent else None
        )
        if not self.name:
            self.name = root_name or "agent"
        if not self.display_name:
            self.display_name = root_display_name or self.name
        if not self.icon:
            self.icon = "🤖"
        if not self.version_label:
            self.version_label = "V1"
        return self


class _OfficialAgentListItem(BaseModel):
    name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    tags: List[str] = []
    version_label: Optional[str] = None
    status: str
    has_knowledge: bool
    mcp_count: int
    skill_count: int
    kb_count: int
    missing_models: List[str] = []
    agents: List = []
    mcps: List = []


class _OfficialAgentAgentInfo(BaseModel):
    name: str
    display_name: Optional[str] = None


class _OfficialAgentMcpPreview(BaseModel):
    mcp_server_name: str
    mcp_url: str
    installed: bool = False


class _SkillZipEntry(BaseModel):
    skill_name: str
    skill_zip_base64: str


class _OfficialAgentInstallItem(BaseModel):
    name: str
    status: str
    message: Optional[str] = None
    steps: Optional[List] = None
    missing_models: List[str] = []
    agent_id: Optional[int] = None


class _OfficialAgentInstallStep(BaseModel):
    name: str
    status: str
    message: Optional[str] = None


consts_model.ModelConnectStatusEnum = _ModelConnectStatusEnum
consts_model.OfficialAgentBundle = _OfficialAgentBundle
consts_model.OfficialAgentListItem = _OfficialAgentListItem
consts_model.OfficialAgentAgentInfo = _OfficialAgentAgentInfo
consts_model.OfficialAgentMcpPreview = _OfficialAgentMcpPreview
consts_model.OfficialAgentInstallItem = _OfficialAgentInstallItem
consts_model.OfficialAgentInstallStep = _OfficialAgentInstallStep
consts_model.KnowledgeBaseSeedDoc = _KnowledgeBaseSeedDoc
consts_model.SkillZipEntry = _SkillZipEntry
consts_model.ProcessParams = _ProcessParams
sys.modules["consts.model"] = consts_model

from services import official_agent_service  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bundle_dict(
    name,
    *,
    has_knowledge=False,
    mcp_count=0,
    skill_count=0,
):
    bundle = {
        "name": name,
        "display_name": f"Display {name}",
        "description": f"desc {name}",
        "icon": "🧪",
        "tags": ["tag1"],
        "version_label": "1.0.0",
        "agent_id": 1,
        "agent_info": {"1": {"name": f"{name}_agent"}},
        "mcp_info": [
            {"mcp_server_name": f"mcp-{i}", "mcp_url": f"http://mcp-{i}"}
            for i in range(mcp_count)
        ],
        "skills": [
            {"skill_name": f"skill-{i}", "skill_zip_base64": "c2tpbGw="}
            for i in range(skill_count)
        ],
        "knowledge_bases": (
            [
                {
                    "logical_index_name": "kb-1",
                    "display_name": "KB",
                    "documents": [{"file_name": "a.md", "content": "hi"}],
                }
            ]
            if has_knowledge
            else []
        ),
    }
    return bundle


def _write_bundle(tmp_path, name, **kwargs):
    (tmp_path / f"{name}.json").write_text(
        json.dumps(_bundle_dict(name, **kwargs)), encoding="utf-8"
    )


def _make_bundle(**kwargs) -> _OfficialAgentBundle:
    return _OfficialAgentBundle.model_validate(_bundle_dict(**kwargs))


# ---------------------------------------------------------------------------
# list_official_agents_with_status
# ---------------------------------------------------------------------------


async def test_empty_or_missing_directory_returns_empty_list(tmp_path):
    with patch.object(
        official_agent_service, "OFFICIAL_AGENTS_PATH", str(tmp_path)
    ):
        items = await official_agent_service.list_official_agents_with_status(
            "tenant-1"
        )
    assert items == []


async def test_kb_bundle_needs_model_when_embedding_missing(tmp_path):
    _write_bundle(tmp_path, "research", has_knowledge=True)
    _write_bundle(tmp_path, "cleaner", has_knowledge=False)

    async def fake_missing(bundle, tenant_id):
        return ["embedding"] if bundle.knowledge_bases else []

    with patch.object(
        official_agent_service, "OFFICIAL_AGENTS_PATH", str(tmp_path)
    ), patch.object(
        official_agent_service, "_is_agent_installed", return_value=False
    ), patch.object(
        official_agent_service, "_missing_model_types", new=fake_missing
    ):
        items = await official_agent_service.list_official_agents_with_status(
            "tenant-1"
        )

    by_name = {item.name: item for item in items}
    assert by_name["research"].status == "needs_model"
    assert by_name["research"].missing_models == ["embedding"]
    assert by_name["cleaner"].status == "installable"


async def test_installable_when_models_available(tmp_path):
    _write_bundle(tmp_path, "research", has_knowledge=True)

    with patch.object(
        official_agent_service, "OFFICIAL_AGENTS_PATH", str(tmp_path)
    ), patch.object(
        official_agent_service, "_is_agent_installed", return_value=False
    ), patch.object(
        official_agent_service,
        "_missing_model_types",
        new_callable=AsyncMock,
        return_value=[],
    ):
        items = await official_agent_service.list_official_agents_with_status(
            "tenant-1"
        )

    assert items[0].status == "installable"
    assert items[0].missing_models == []


async def test_installed_takes_priority_over_missing_model(tmp_path):
    _write_bundle(tmp_path, "research", has_knowledge=True)

    with patch.object(
        official_agent_service, "OFFICIAL_AGENTS_PATH", str(tmp_path)
    ), patch.object(
        official_agent_service, "_is_agent_installed", return_value=True
    ), patch.object(
        official_agent_service,
        "_missing_model_types",
        new_callable=AsyncMock,
        return_value=["embedding"],
    ):
        items = await official_agent_service.list_official_agents_with_status(
            "tenant-1"
        )

    assert items[0].status == "installed"


async def test_invalid_bundle_is_skipped(tmp_path):
    _write_bundle(tmp_path, "good", has_knowledge=False)
    (tmp_path / "broken.json").write_text("{not-json", encoding="utf-8")

    with patch.object(
        official_agent_service, "OFFICIAL_AGENTS_PATH", str(tmp_path)
    ), patch.object(
        official_agent_service, "_is_agent_installed", return_value=False
    ), patch.object(
        official_agent_service,
        "_missing_model_types",
        new_callable=AsyncMock,
        return_value=[],
    ):
        items = await official_agent_service.list_official_agents_with_status(
            "tenant-1"
        )

    assert [item.name for item in items] == ["good"]


async def test_item_field_mapping(tmp_path):
    _write_bundle(
        tmp_path,
        "full",
        has_knowledge=True,
        mcp_count=2,
        skill_count=3,
    )

    fake_remote_db = types.ModuleType("database.remote_mcp_db")
    fake_remote_db.get_mcp_server_by_name_and_tenant = MagicMock(
        side_effect=["http://mcp-0", ""]
    )

    with patch.object(
        official_agent_service, "OFFICIAL_AGENTS_PATH", str(tmp_path)
    ), patch.object(
        official_agent_service, "_is_agent_installed", return_value=False
    ), patch.object(
        official_agent_service,
        "_missing_model_types",
        new_callable=AsyncMock,
        return_value=[],
    ), patch.dict(sys.modules, {"database.remote_mcp_db": fake_remote_db}):
        items = await official_agent_service.list_official_agents_with_status(
            "tenant-1"
        )

    item = items[0]
    assert item.name == "full"
    assert item.display_name == "Display full"
    assert item.description == "desc full"
    assert item.icon == "🧪"
    assert item.tags == ["tag1"]
    assert item.version_label == "1.0.0"
    assert item.has_knowledge is True
    assert item.mcp_count == 2
    assert item.skill_count == 3
    assert item.kb_count == 1
    assert item.missing_models == []
    # agents: root agent "full_agent" from agent_info
    assert [a.name for a in item.agents] == ["full_agent"]
    # mcps: mcp-0 already installed (same url), mcp-1 not installed
    assert [(m.mcp_server_name, m.installed) for m in item.mcps] == [
        ("mcp-0", True),
        ("mcp-1", False),
    ]


# ---------------------------------------------------------------------------
# _is_agent_installed
# ---------------------------------------------------------------------------


def test_is_agent_installed_when_agent_exists():
    bundle = _make_bundle(name="research")
    fake = types.ModuleType("database.agent_db")
    fake.search_agent_id_by_agent_name = MagicMock(return_value=42)
    with patch.dict(sys.modules, {"database.agent_db": fake}):
        assert official_agent_service._is_agent_installed(bundle, "tenant-1") is True


def test_is_agent_installed_when_agent_missing():
    bundle = _make_bundle(name="research")
    fake = types.ModuleType("database.agent_db")
    fake.search_agent_id_by_agent_name = MagicMock(
        side_effect=ValueError("agent not found")
    )
    with patch.dict(sys.modules, {"database.agent_db": fake}):
        assert official_agent_service._is_agent_installed(bundle, "tenant-1") is False


# ---------------------------------------------------------------------------
# _has_available_embedding_model
# ---------------------------------------------------------------------------


async def test_has_available_embedding_model_true():
    fake = types.ModuleType("services.model_management_service")
    fake.list_models_for_tenant = AsyncMock(
        return_value=[
            {"model_id": 1, "model_type": "llm", "connect_status": "available"},
            {"model_id": 2, "model_type": "embedding", "connect_status": "available"},
        ]
    )
    with patch.dict(sys.modules, {"services.model_management_service": fake}):
        assert (
            await official_agent_service._has_available_embedding_model("tenant-1")
            is True
        )


async def test_first_available_embedding_model_id_returns_id():
    fake = types.ModuleType("services.model_management_service")
    fake.list_models_for_tenant = AsyncMock(
        return_value=[
            {"model_id": 1, "model_type": "llm", "connect_status": "available"},
            {"model_id": 2, "model_type": "embedding", "connect_status": "available"},
            {"model_id": 3, "model_type": "multi_embedding", "connect_status": "available"},
        ]
    )
    with patch.dict(sys.modules, {"services.model_management_service": fake}):
        model_id = await official_agent_service._first_available_embedding_model_id(
            "tenant-1"
        )
    assert model_id == 2


async def test_has_available_embedding_model_false_when_unavailable():
    fake = types.ModuleType("services.model_management_service")
    fake.list_models_for_tenant = AsyncMock(
        return_value=[
            {"model_id": 1, "model_type": "embedding", "connect_status": "unavailable"},
            {"model_id": 2, "model_type": "llm", "connect_status": "available"},
        ]
    )
    with patch.dict(sys.modules, {"services.model_management_service": fake}):
        assert (
            await official_agent_service._has_available_embedding_model("tenant-1")
            is False
        )


async def test_missing_model_types_reports_all_missing():
    bundle = _make_bundle(name="research", has_knowledge=True)
    fake = types.ModuleType("services.model_management_service")
    fake.list_models_for_tenant = AsyncMock(return_value=[])
    with patch.dict(sys.modules, {"services.model_management_service": fake}):
        missing = await official_agent_service._missing_model_types(bundle, "tenant-1")
    assert missing == ["llm", "embedding"]


async def test_missing_model_types_reports_rerank_when_enabled():
    bundle = _make_bundle(name="research", has_knowledge=True)
    bundle.agent_info["1"].tools = [
        _ToolConfig(
            class_name="KnowledgeBaseSearchTool",
            name="kb",
            params={"index_names": ["kb-1"], "rerank": True},
        )
    ]
    fake = types.ModuleType("services.model_management_service")
    fake.list_models_for_tenant = AsyncMock(
        return_value=[
            {"model_id": 1, "model_type": "llm", "connect_status": "available"},
            {"model_id": 2, "model_type": "embedding", "connect_status": "available"},
        ]
    )
    with patch.dict(sys.modules, {"services.model_management_service": fake}):
        missing = await official_agent_service._missing_model_types(bundle, "tenant-1")
    assert missing == ["rerank"]


async def test_missing_model_types_empty_when_all_present():
    bundle = _make_bundle(name="research", has_knowledge=True)
    fake = types.ModuleType("services.model_management_service")
    fake.list_models_for_tenant = AsyncMock(
        return_value=[
            {"model_id": 1, "model_type": "llm", "connect_status": "available"},
            {"model_id": 2, "model_type": "multi_embedding", "connect_status": "available"},
        ]
    )
    with patch.dict(sys.modules, {"services.model_management_service": fake}):
        missing = await official_agent_service._missing_model_types(bundle, "tenant-1")
    assert missing == []


# ---------------------------------------------------------------------------
# install_official_agents
# ---------------------------------------------------------------------------


async def test_install_success():
    bundle = _make_bundle(name="research", has_knowledge=False)
    with patch.object(
        official_agent_service, "_load_bundle", return_value=bundle
    ), patch.object(
        official_agent_service, "_is_agent_installed", return_value=False
    ), patch.object(
        official_agent_service,
        "_missing_model_types",
        new_callable=AsyncMock,
        return_value=[],
    ), patch.object(
        official_agent_service,
        "_install_bundle",
        new_callable=AsyncMock,
        return_value=42,
    ) as mock_install:
        results = await official_agent_service.install_official_agents(
            ["research"], tenant_id="tenant-1", user_id="u", authorization="auth"
        )

    assert results[0].status == "installed"
    assert results[0].agent_id == 42
    assert mock_install.await_count == 1
    call_kwargs = mock_install.await_args.kwargs
    assert call_kwargs["embedding_model_id"] is None
    assert isinstance(call_kwargs["steps"], list)
    assert mock_install.await_args.args == (bundle, "tenant-1", "u", "auth")


async def test_install_uses_provided_embedding_model():
    bundle = _make_bundle(name="research", has_knowledge=True)
    with patch.object(
        official_agent_service, "_load_bundle", return_value=bundle
    ), patch.object(
        official_agent_service, "_is_agent_installed", return_value=False
    ), patch.object(
        official_agent_service,
        "_missing_model_types",
        new_callable=AsyncMock,
        return_value=[],
    ), patch.object(
        official_agent_service,
        "_first_available_embedding_model_id",
        new_callable=AsyncMock,
    ) as mock_first, patch.object(
        official_agent_service, "_install_bundle", new_callable=AsyncMock
    ) as mock_install:
        results = await official_agent_service.install_official_agents(
            ["research"],
            tenant_id="tenant-1",
            user_id="u",
            authorization="auth",
            embedding_model_ids={"research": 9},
        )

    assert results[0].status == "installed"
    # user-selected embedding model is used and the default lookup is skipped
    assert mock_install.await_args.kwargs["embedding_model_id"] == 9
    mock_first.assert_not_awaited()


async def test_install_falls_back_to_default_embedding_model():
    bundle = _make_bundle(name="research", has_knowledge=True)
    with patch.object(
        official_agent_service, "_load_bundle", return_value=bundle
    ), patch.object(
        official_agent_service, "_is_agent_installed", return_value=False
    ), patch.object(
        official_agent_service,
        "_missing_model_types",
        new_callable=AsyncMock,
        return_value=[],
    ), patch.object(
        official_agent_service,
        "_first_available_embedding_model_id",
        new_callable=AsyncMock,
        return_value=7,
    ), patch.object(
        official_agent_service, "_install_bundle", new_callable=AsyncMock
    ) as mock_install:
        results = await official_agent_service.install_official_agents(
            ["research"], tenant_id="tenant-1", user_id="u", authorization="auth"
        )

    assert results[0].status == "installed"
    assert mock_install.await_args.kwargs["embedding_model_id"] == 7


async def test_install_skips_already_installed():
    bundle = _make_bundle(name="research")
    with patch.object(
        official_agent_service, "_load_bundle", return_value=bundle
    ), patch.object(
        official_agent_service, "_is_agent_installed", return_value=True
    ), patch.object(
        official_agent_service, "_install_bundle", new_callable=AsyncMock
    ) as mock_install:
        results = await official_agent_service.install_official_agents(
            ["research"], tenant_id="tenant-1", user_id="u", authorization="auth"
        )

    assert results[0].status == "already_installed"
    mock_install.assert_not_awaited()


def test_apply_install_options_renames_and_sets_model():
    bundle = _make_bundle(name="research")
    bundle.agent_info["2"] = _ExportAndImportAgentInfo(name="sub_agent")

    official_agent_service._apply_install_options(
        bundle,
        renames={"research_agent": "research_v2", "sub_agent": "sub_v2"},
        model_ids={"research": 7},
    )

    assert bundle.agent_info["1"].name == "research_v2"
    assert bundle.agent_info["2"].name == "sub_v2"
    # unified model: applied to every agent in the bundle
    assert bundle.agent_info["1"].model_ids == [7]
    assert bundle.agent_info["2"].model_ids == [7]


async def test_install_proceeds_when_root_renamed():
    bundle = _make_bundle(name="research")
    with patch.object(
        official_agent_service, "_load_bundle", return_value=bundle
    ), patch.object(
        official_agent_service,
        "_missing_model_types",
        new_callable=AsyncMock,
        return_value=[],
    ), patch.object(
        official_agent_service, "_install_bundle", new_callable=AsyncMock
    ) as mock_install:
        results = await official_agent_service.install_official_agents(
            ["research"],
            tenant_id="tenant-1",
            user_id="u",
            authorization="auth",
            renames={"research_agent": "research_v2"},
        )

    assert results[0].status == "installed"
    assert bundle.agent_info["1"].name == "research_v2"
    mock_install.assert_awaited_once()


async def test_install_needs_model_when_model_missing():
    bundle = _make_bundle(name="research", has_knowledge=True)
    with patch.object(
        official_agent_service, "_load_bundle", return_value=bundle
    ), patch.object(
        official_agent_service, "_is_agent_installed", return_value=False
    ), patch.object(
        official_agent_service,
        "_missing_model_types",
        new_callable=AsyncMock,
        return_value=["embedding"],
    ), patch.object(
        official_agent_service, "_install_bundle", new_callable=AsyncMock
    ) as mock_install:
        results = await official_agent_service.install_official_agents(
            ["research"], tenant_id="tenant-1", user_id="u", authorization="auth"
        )

    assert results[0].status == "needs_model"
    assert results[0].missing_models == ["embedding"]
    assert "embedding" in (results[0].message or "")
    mock_install.assert_not_awaited()


async def test_install_not_found_when_bundle_missing():
    with patch.object(
        official_agent_service, "_load_bundle", return_value=None
    ), patch.object(
        official_agent_service, "_install_bundle", new_callable=AsyncMock
    ) as mock_install:
        results = await official_agent_service.install_official_agents(
            ["ghost"], tenant_id="tenant-1", user_id="u", authorization="auth"
        )

    assert results[0].status == "not_found"
    assert "not found" in (results[0].message or "")
    mock_install.assert_not_awaited()


async def test_install_reports_failure_per_agent():
    bundle = _make_bundle(name="research")
    with patch.object(
        official_agent_service, "_load_bundle", return_value=bundle
    ), patch.object(
        official_agent_service, "_is_agent_installed", return_value=False
    ), patch.object(
        official_agent_service,
        "_missing_model_types",
        new_callable=AsyncMock,
        return_value=[],
    ), patch.object(
        official_agent_service,
        "_install_bundle",
        new_callable=AsyncMock,
        side_effect=RuntimeError("boom"),
    ):
        results = await official_agent_service.install_official_agents(
            ["research"], tenant_id="tenant-1", user_id="u", authorization="auth"
        )

    assert results[0].status == "failed"
    assert results[0].message == "boom"


# ---------------------------------------------------------------------------
# _install_bundle
# ---------------------------------------------------------------------------


async def test_install_bundle_with_skills():
    bundle = _make_bundle(name="research", skill_count=1)
    fake_tool = types.ModuleType("services.tool_configuration_service")
    fake_tool.update_tool_list = AsyncMock()
    fake_agent = types.ModuleType("services.agent_service")
    fake_agent.import_agent_impl = AsyncMock()
    fake_agent._create_skills_for_install = AsyncMock(
        return_value={"skill-0": 7}
    )
    fake_agent._import_agent_with_skill_links = AsyncMock(return_value={1: 100})

    with patch.object(
        official_agent_service, "_install_mcp_servers", new_callable=AsyncMock
    ) as mock_mcp, patch.dict(
        sys.modules,
        {
            "services.tool_configuration_service": fake_tool,
            "services.agent_service": fake_agent,
        },
    ):
        result = await official_agent_service._install_bundle(
            bundle, "tenant-1", "u", "auth"
        )

    assert result == 100
    mock_mcp.assert_awaited_once_with(bundle, "tenant-1", "u")
    fake_tool.update_tool_list.assert_awaited_once_with(
        tenant_id="tenant-1", user_id="u"
    )
    fake_agent._create_skills_for_install.assert_awaited_once_with(
        bundle.skills,
        "tenant-1",
        "u",
        reuse_existing_skills=True,
    )
    fake_agent._import_agent_with_skill_links.assert_awaited_once_with(
        bundle,
        {"skill-0": 7},
        "auth",
        tenant_id="tenant-1",
        user_id="u",
    )
    fake_agent.import_agent_impl.assert_not_awaited()


async def test_install_bundle_without_skills():
    bundle = _make_bundle(name="research", skill_count=0)
    fake_tool = types.ModuleType("services.tool_configuration_service")
    fake_tool.update_tool_list = AsyncMock()
    fake_agent = types.ModuleType("services.agent_service")
    fake_agent.import_agent_impl = AsyncMock(return_value={1: 100})
    fake_agent._create_skills_for_install = AsyncMock()
    fake_agent._import_agent_with_skill_links = AsyncMock()

    with patch.object(
        official_agent_service, "_install_mcp_servers", new_callable=AsyncMock
    ), patch.dict(
        sys.modules,
        {
            "services.tool_configuration_service": fake_tool,
            "services.agent_service": fake_agent,
        },
    ):
        result = await official_agent_service._install_bundle(
            bundle, "tenant-1", "u", "auth"
        )

    assert result == 100
    fake_agent.import_agent_impl.assert_awaited_once_with(
        bundle, "auth", tenant_id="tenant-1", user_id="u"
    )
    fake_agent._create_skills_for_install.assert_not_awaited()
    fake_agent._import_agent_with_skill_links.assert_not_awaited()


# ---------------------------------------------------------------------------
# _install_mcp_servers
# ---------------------------------------------------------------------------


async def test_install_mcp_servers_installs_missing_and_skips_installed():
    bundle = _make_bundle(name="research", mcp_count=2)
    fake_remote_db = types.ModuleType("database.remote_mcp_db")
    fake_remote_db.get_mcp_server_by_name_and_tenant = MagicMock(
        side_effect=["", "http://mcp-1"]
    )
    fake_mcp_svc = types.ModuleType("services.remote_mcp_service")
    fake_mcp_svc.add_mcp_service = AsyncMock()

    with patch.dict(
        sys.modules,
        {
            "database.remote_mcp_db": fake_remote_db,
            "services.remote_mcp_service": fake_mcp_svc,
        },
    ):
        await official_agent_service._install_mcp_servers(bundle, "tenant-1", "u")

    fake_mcp_svc.add_mcp_service.assert_awaited_once()
    kwargs = fake_mcp_svc.add_mcp_service.await_args.kwargs
    assert kwargs["name"] == "mcp-0"
    assert kwargs["server_url"] == "http://mcp-0"
    assert kwargs["tenant_id"] == "tenant-1"
    assert kwargs["skip_health_check"] is True


async def test_install_mcp_servers_raises_on_same_name_different_url():
    bundle = _make_bundle(name="research", mcp_count=1)
    fake_remote_db = types.ModuleType("database.remote_mcp_db")
    fake_remote_db.get_mcp_server_by_name_and_tenant = MagicMock(
        return_value="http://old-url"
    )
    fake_mcp_svc = types.ModuleType("services.remote_mcp_service")
    fake_mcp_svc.add_mcp_service = AsyncMock()

    with patch.dict(
        sys.modules,
        {
            "database.remote_mcp_db": fake_remote_db,
            "services.remote_mcp_service": fake_mcp_svc,
        },
    ):
        with pytest.raises(ValueError) as exc_info:
            await official_agent_service._install_mcp_servers(bundle, "tenant-1", "u")

    assert "mcp-0" in str(exc_info.value)
    assert "http://old-url" in str(exc_info.value)
    fake_mcp_svc.add_mcp_service.assert_not_awaited()


# ---------------------------------------------------------------------------
# _create_knowledge_bases
# ---------------------------------------------------------------------------


async def test_create_knowledge_bases_creates_and_indexes():
    bundle = _make_bundle(name="research", has_knowledge=True)
    fake_kb_db = types.ModuleType("database.knowledge_db")
    fake_kb_db.get_knowledge_record = MagicMock(return_value=None)
    fake_vdb = types.ModuleType("services.vectordatabase_service")
    fake_vdb.ElasticSearchService = MagicMock()
    fake_vdb.ElasticSearchService.create_knowledge_base.return_value = {
        "id": "42-abc"
    }
    fake_vdb.ElasticSearchService.index_documents = MagicMock()
    fake_vdb.get_embedding_model_by_id = MagicMock(return_value=(MagicMock(), 5))
    fake_vdb.get_vector_db_core = MagicMock(return_value=MagicMock())

    with patch.dict(
        sys.modules,
        {
            "database.knowledge_db": fake_kb_db,
            "services.vectordatabase_service": fake_vdb,
        },
    ):
        mapping = await official_agent_service._create_knowledge_bases(
            bundle, "tenant-1", "u", embedding_model_id=5, authorization="auth"
        )

    assert mapping == {"kb-1": "42-abc"}
    fake_vdb.ElasticSearchService.create_knowledge_base.assert_called_once_with(
        knowledge_name="KB",
        embedding_dim=None,
        vdb_core=fake_vdb.get_vector_db_core.return_value,
        user_id="u",
        tenant_id="tenant-1",
        embedding_model_id=5,
    )
    fake_vdb.ElasticSearchService.index_documents.assert_called_once()
    call = fake_vdb.ElasticSearchService.index_documents.call_args
    assert call.kwargs["index_name"] == "42-abc"
    assert call.kwargs["model_id"] == 5
    assert call.kwargs["data"] == [
        {
            "content": "hi",
            "path_or_url": "a.md",
            "source_type": "local",
            "filename": "a.md",
            "metadata": {"title": "a.md"},
        }
    ]


async def test_create_knowledge_bases_reuses_existing():
    bundle = _make_bundle(name="research", has_knowledge=True)
    fake_kb_db = types.ModuleType("database.knowledge_db")
    fake_kb_db.get_knowledge_record = MagicMock(
        return_value={"knowledge_id": 9, "index_name": "42-abc"}
    )
    fake_vdb = types.ModuleType("services.vectordatabase_service")
    fake_vdb.ElasticSearchService = MagicMock()
    fake_vdb.get_embedding_model_by_id = MagicMock(return_value=(MagicMock(), 5))
    fake_vdb.get_vector_db_core = MagicMock()

    with patch.dict(
        sys.modules,
        {
            "database.knowledge_db": fake_kb_db,
            "services.vectordatabase_service": fake_vdb,
        },
    ):
        mapping = await official_agent_service._create_knowledge_bases(
            bundle, "tenant-1", "u", embedding_model_id=5, authorization="auth"
        )

    # Reused by display name ("KB" from the bundle), mapped to the existing index.
    assert mapping == {"kb-1": "42-abc"}
    fake_kb_db.get_knowledge_record.assert_called_once_with(
        {"knowledge_name": "KB", "tenant_id": "tenant-1"}
    )
    fake_vdb.ElasticSearchService.create_knowledge_base.assert_not_called()
    fake_vdb.ElasticSearchService.index_documents.assert_not_called()


# ---------------------------------------------------------------------------
# _remap_kb_refs
# ---------------------------------------------------------------------------


def test_remap_kb_refs_rewrites_index_names():
    agent_info = {
        "1": {
            "name": "a",
            "tools": [
                {
                    "class_name": "KnowledgeBaseSearchTool",
                    "name": "kb",
                    "params": {"index_names": ["industry-kb", "other"]},
                    "source": "local",
                }
            ],
        }
    }
    bundle = _OfficialAgentBundle.model_validate(
        {"name": "x", "agent_id": 1, "agent_info": agent_info}
    )
    official_agent_service._remap_kb_refs(bundle, {"industry-kb": "42-abc"})

    tool = bundle.agent_info["1"].tools[0]
    assert tool.params["index_names"] == ["42-abc", "other"]


def test_remap_kb_refs_ignores_non_kb_tools():
    agent_info = {
        "1": {
            "name": "a",
            "tools": [
                {
                    "class_name": "WebSearchTool",
                    "name": "web",
                    "params": {"query": "x"},
                    "source": "local",
                }
            ],
        }
    }
    bundle = _OfficialAgentBundle.model_validate(
        {"name": "x", "agent_id": 1, "agent_info": agent_info}
    )
    official_agent_service._remap_kb_refs(bundle, {"industry-kb": "42-abc"})

    tool = bundle.agent_info["1"].tools[0]
    assert tool.params == {"query": "x"}


# ---------------------------------------------------------------------------
# _install_bundle with knowledge bases
# ---------------------------------------------------------------------------


async def test_install_bundle_creates_kb_and_remaps_refs():
    bundle = _make_bundle(name="research", has_knowledge=True)
    bundle.agent_info["1"].tools = [
        _ToolConfig(
            class_name="KnowledgeBaseSearchTool",
            name="kb",
            params={"index_names": ["kb-1"]},
        )
    ]
    fake_tool = types.ModuleType("services.tool_configuration_service")
    fake_tool.update_tool_list = AsyncMock()
    fake_agent = types.ModuleType("services.agent_service")
    fake_agent.import_agent_impl = AsyncMock()
    fake_agent.import_agent_with_skills_impl = AsyncMock()
    fake_agent._create_skills_for_install = AsyncMock()
    fake_agent._import_agent_with_skill_links = AsyncMock()

    with patch.object(
        official_agent_service, "_install_mcp_servers", new_callable=AsyncMock
    ), patch.object(
        official_agent_service,
        "_create_knowledge_bases",
        new_callable=AsyncMock,
        return_value={"kb-1": "42-abc"},
    ) as mock_kb, patch.dict(
        sys.modules,
        {
            "services.tool_configuration_service": fake_tool,
            "services.agent_service": fake_agent,
        },
    ):
        await official_agent_service._install_bundle(
            bundle, "tenant-1", "u", "auth", embedding_model_id=5
        )

    mock_kb.assert_awaited_once_with(
        bundle, "tenant-1", "u", 5, authorization="auth"
    )
    # tool references were remapped to the tenant-generated index name
    assert bundle.agent_info["1"].tools[0].params["index_names"] == ["42-abc"]
    fake_agent.import_agent_impl.assert_awaited_once_with(
        bundle, "auth", tenant_id="tenant-1", user_id="u"
    )


async def test_install_bundle_derives_embedding_model_when_not_given():
    bundle = _make_bundle(name="research", has_knowledge=True)
    fake_tool = types.ModuleType("services.tool_configuration_service")
    fake_tool.update_tool_list = AsyncMock()
    fake_agent = types.ModuleType("services.agent_service")
    fake_agent.import_agent_impl = AsyncMock()
    fake_agent.import_agent_with_skills_impl = AsyncMock()
    fake_agent._create_skills_for_install = AsyncMock()
    fake_agent._import_agent_with_skill_links = AsyncMock()

    with patch.object(
        official_agent_service, "_install_mcp_servers", new_callable=AsyncMock
    ), patch.object(
        official_agent_service,
        "_first_available_embedding_model_id",
        new_callable=AsyncMock,
        return_value=7,
    ), patch.object(
        official_agent_service,
        "_create_knowledge_bases",
        new_callable=AsyncMock,
        return_value={"kb-1": "42-abc"},
    ) as mock_kb, patch.dict(
        sys.modules,
        {
            "services.tool_configuration_service": fake_tool,
            "services.agent_service": fake_agent,
        },
    ):
        await official_agent_service._install_bundle(bundle, "tenant-1", "u", "auth")

    mock_kb.assert_awaited_once_with(
        bundle, "tenant-1", "u", 7, authorization="auth"
    )


async def test_install_bundle_raises_when_embedding_missing():
    bundle = _make_bundle(name="research", has_knowledge=True)
    fake_tool = types.ModuleType("services.tool_configuration_service")
    fake_tool.update_tool_list = AsyncMock()
    fake_agent = types.ModuleType("services.agent_service")
    fake_agent.import_agent_impl = AsyncMock()
    fake_agent._create_skills_for_install = AsyncMock()
    fake_agent._import_agent_with_skill_links = AsyncMock()

    with patch.object(
        official_agent_service, "_install_mcp_servers", new_callable=AsyncMock
    ), patch.object(
        official_agent_service,
        "_first_available_embedding_model_id",
        new_callable=AsyncMock,
        return_value=None,
    ), patch.dict(
        sys.modules,
        {
            "services.tool_configuration_service": fake_tool,
            "services.agent_service": fake_agent,
        },
    ):
        with pytest.raises(ValueError):
            await official_agent_service._install_bundle(
                bundle, "tenant-1", "u", "auth"
            )


# ---------------------------------------------------------------------------
# Dual-layout bundle loading (single-file JSON + ZIP-style directory)
# ---------------------------------------------------------------------------


def _write_dir_bundle(tmp_path, name, *, skill_names=(), kb_logical=None, kb_docs=()):
    """Create a ZIP-style directory bundle: agent.json + skills/ + kb/."""
    agent_info = {
        "1": {
            "name": f"{name}_agent",
            "display_name": f"Display {name}",
            "tools": [],
        }
    }
    if skill_names:
        agent_info["1"]["skill_names"] = list(skill_names)
    data = {
        "agent_id": 1,
        "agent_info": agent_info,
        "mcp_info": [],
        "knowledge_bases": [],
    }
    if kb_logical:
        data["knowledge_bases"].append(
            {"logical_index_name": kb_logical, "display_name": "KB"}
        )
    bundle_dir = tmp_path / name
    bundle_dir.mkdir()
    (bundle_dir / "agent.json").write_text(json.dumps(data), encoding="utf-8")
    if skill_names:
        (bundle_dir / "skills").mkdir()
        for s in skill_names:
            (bundle_dir / "skills" / f"{s}.zip").write_bytes(b"PK\x03\x04fake")
    if kb_logical and kb_docs:
        kb_path = bundle_dir / "kb" / kb_logical
        kb_path.mkdir(parents=True)
        for doc_name in kb_docs:
            (kb_path / doc_name).write_text(f"content of {doc_name}", encoding="utf-8")


def test_list_bundle_files_recognizes_directory_and_single(tmp_path):
    (tmp_path / "single.json").write_text("{}", encoding="utf-8")
    _write_dir_bundle(tmp_path, "foldered")

    with patch.object(
        official_agent_service, "OFFICIAL_AGENTS_PATH", str(tmp_path)
    ):
        assert official_agent_service._list_bundle_files() == ["foldered", "single"]


def test_load_bundle_directory_layout_attaches_skills_and_kb_docs(tmp_path):
    _write_dir_bundle(
        tmp_path,
        "foldered",
        skill_names=("skill-a",),
        kb_logical="industry-kb",
        kb_docs=("overview.md",),
    )

    with patch.object(
        official_agent_service, "OFFICIAL_AGENTS_PATH", str(tmp_path)
    ):
        bundle = official_agent_service._load_bundle("foldered")

    assert bundle is not None
    assert bundle.name == "foldered"
    assert bundle.display_name == "Display foldered"
    assert bundle.icon == "🤖"
    assert bundle.version_label == "V1"
    assert len(bundle.skills or []) == 1
    skill = bundle.skills[0]
    assert skill.skill_name == "skill-a"
    assert skill.skill_zip_base64 == "UEsDBGZha2U="  # base64(b"PK\x03\x04fake")
    assert len(bundle.knowledge_bases) == 1
    assert bundle.knowledge_bases[0].documents[0].file_name == "overview.md"
    assert bundle.knowledge_bases[0].documents[0].content == "content of overview.md"


def test_load_bundle_single_file_still_works(tmp_path):
    (tmp_path / "single.json").write_text(
        json.dumps(_bundle_dict("single")), encoding="utf-8"
    )

    with patch.object(
        official_agent_service, "OFFICIAL_AGENTS_PATH", str(tmp_path)
    ):
        bundle = official_agent_service._load_bundle("single")

    assert bundle is not None
    assert bundle.name == "single"
    assert bundle.display_name == "Display single"


def test_load_bundle_missing_returns_none(tmp_path):
    with patch.object(
        official_agent_service, "OFFICIAL_AGENTS_PATH", str(tmp_path)
    ):
        assert official_agent_service._load_bundle("ghost") is None


def test_attach_kb_docs_distinguishes_text_and_binary(tmp_path):
    # 目录布局：kb/industry-kb/ 里同时放 .md（文本）和 .docx（二进制）
    _write_dir_bundle(tmp_path, "foldered", kb_logical="industry-kb", kb_docs=("a.md",))
    kb_path = tmp_path / "foldered" / "kb" / "industry-kb"
    (kb_path / "b.docx").write_bytes(b"%PDF-1.4 fake")

    with patch.object(
        official_agent_service, "OFFICIAL_AGENTS_PATH", str(tmp_path)
    ):
        bundle = official_agent_service._load_bundle("foldered")

    docs = bundle.knowledge_bases[0].documents
    by_name = {doc.file_name: doc for doc in docs}
    assert by_name["a.md"].content == "content of a.md"
    assert by_name["a.md"].file_path is None
    assert by_name["b.docx"].content is None
    assert by_name["b.docx"].file_path == str(kb_path / "b.docx")


async def test_create_knowledge_bases_uploads_binary_docs(tmp_path):
    bundle = _make_bundle(name="research", has_knowledge=True)
    binary_file = tmp_path / "a.docx"
    binary_file.write_bytes(b"%PDF-1.4 fake")
    bundle.knowledge_bases[0].documents = [
        _KnowledgeBaseSeedDoc(file_name="a.docx", file_path=str(binary_file))
    ]
    fake_kb_db = types.ModuleType("database.knowledge_db")
    fake_kb_db.get_knowledge_record = MagicMock(return_value=None)
    fake_vdb = types.ModuleType("services.vectordatabase_service")
    fake_vdb.ElasticSearchService = MagicMock()
    fake_vdb.ElasticSearchService.create_knowledge_base.return_value = {
        "id": "42-abc"
    }
    fake_vdb.get_embedding_model_by_id = MagicMock(return_value=(MagicMock(), 5))
    fake_vdb.get_vector_db_core = MagicMock()
    fake_file_svc = types.ModuleType("services.file_management_service")
    fake_file_svc.upload_files_impl = AsyncMock(
        return_value=([], ["minio/a.docx"], ["a.docx"])
    )
    fake_utils = types.ModuleType("utils.file_management_utils")
    fake_utils.trigger_data_process = AsyncMock()

    with patch.dict(
        sys.modules,
        {
            "consts.model": consts_model,
            "database.knowledge_db": fake_kb_db,
            "services.vectordatabase_service": fake_vdb,
            "services.file_management_service": fake_file_svc,
            "utils.file_management_utils": fake_utils,
        },
    ):
        mapping = await official_agent_service._create_knowledge_bases(
            bundle, "tenant-1", "u", embedding_model_id=5, authorization="auth"
        )

    assert mapping == {"kb-1": "42-abc"}
    fake_vdb.ElasticSearchService.create_knowledge_base.assert_called_once()
    # no text docs -> the text embedding path is not used
    fake_vdb.ElasticSearchService.index_documents.assert_not_called()

    fake_file_svc.upload_files_impl.assert_awaited_once()
    upload_kwargs = fake_file_svc.upload_files_impl.await_args.kwargs
    assert upload_kwargs["destination"] == "minio"
    assert upload_kwargs["index_name"] == "42-abc"
    assert upload_kwargs["user_id"] == "u"
    assert upload_kwargs["uploader_tenant_id"] == "tenant-1"

    fake_utils.trigger_data_process.assert_awaited_once()
    files, process_params = fake_utils.trigger_data_process.await_args.args
    assert files == [{"path_or_url": "minio/a.docx", "filename": "a.docx"}]
    assert process_params.index_name == "42-abc"
    assert process_params.source_type == "minio"
    assert process_params.model_id == 5
    assert process_params.authorization == "auth"


async def test_install_bundle_records_steps():
    bundle = _make_bundle(name="research", skill_count=0)
    fake_tool = types.ModuleType("services.tool_configuration_service")
    fake_tool.update_tool_list = AsyncMock()
    fake_agent = types.ModuleType("services.agent_service")
    fake_agent.import_agent_impl = AsyncMock(return_value={1: 100})
    fake_agent._create_skills_for_install = AsyncMock()
    fake_agent._import_agent_with_skill_links = AsyncMock()
    steps = []

    with patch.object(
        official_agent_service, "_install_mcp_servers", new_callable=AsyncMock
    ), patch.dict(
        sys.modules,
        {
            "services.tool_configuration_service": fake_tool,
            "services.agent_service": fake_agent,
        },
    ):
        await official_agent_service._install_bundle(
            bundle, "tenant-1", "u", "auth", steps=steps
        )

    assert [(s.name, s.status) for s in steps] == [
        ("mcp", "ok"),
        ("agent", "ok"),
    ]


async def test_install_bundle_records_skill_step():
    bundle = _make_bundle(name="research", skill_count=1)
    fake_tool = types.ModuleType("services.tool_configuration_service")
    fake_tool.update_tool_list = AsyncMock()
    fake_agent = types.ModuleType("services.agent_service")
    fake_agent.import_agent_impl = AsyncMock()
    fake_agent._create_skills_for_install = AsyncMock(
        return_value={"skill-0": 7}
    )
    fake_agent._import_agent_with_skill_links = AsyncMock(return_value={1: 100})
    steps = []

    with patch.object(
        official_agent_service, "_install_mcp_servers", new_callable=AsyncMock
    ), patch.dict(
        sys.modules,
        {
            "services.tool_configuration_service": fake_tool,
            "services.agent_service": fake_agent,
        },
    ):
        await official_agent_service._install_bundle(
            bundle, "tenant-1", "u", "auth", steps=steps
        )

    assert [(s.name, s.status) for s in steps] == [
        ("mcp", "ok"),
        ("skill", "ok"),
        ("agent", "ok"),
    ]


async def test_install_bundle_records_failed_step():
    bundle = _make_bundle(name="research")
    fake_tool = types.ModuleType("services.tool_configuration_service")
    fake_tool.update_tool_list = AsyncMock(side_effect=RuntimeError("boom"))
    fake_agent = types.ModuleType("services.agent_service")
    fake_agent.import_agent_impl = AsyncMock()
    fake_agent._create_skills_for_install = AsyncMock()
    fake_agent._import_agent_with_skill_links = AsyncMock()
    steps = []

    with patch.object(
        official_agent_service, "_install_mcp_servers", new_callable=AsyncMock
    ), patch.dict(
        sys.modules,
        {
            "services.tool_configuration_service": fake_tool,
            "services.agent_service": fake_agent,
        },
    ):
        with pytest.raises(RuntimeError):
            await official_agent_service._install_bundle(
                bundle, "tenant-1", "u", "auth", steps=steps
            )

    assert [(s.name, s.status) for s in steps] == [("mcp", "failed")]
    assert steps[0].message == "boom"
