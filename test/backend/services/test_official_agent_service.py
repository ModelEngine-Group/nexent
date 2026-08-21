"""Unit tests for official agent listing service."""

import json
import os
import subprocess
import sys
import types
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, model_validator

from consts.exceptions import RepoSourceError

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


class _SkillZipEntry(BaseModel):
    skill_name: str
    skill_zip_base64: str


class _OfficialAgentBundle(BaseModel):
    name: Optional[str] = None
    agent_id: int
    agent_info: Dict[str, _ExportAndImportAgentInfo] = {}
    mcp_info: List[_MCPInfo] = []
    skills: Optional[List[_SkillZipEntry]] = None
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
    skills: List = []
    knowledge_bases: List = []


class _OfficialAgentAgentInfo(BaseModel):
    name: str
    display_name: Optional[str] = None


class _OfficialAgentMcpPreview(BaseModel):
    mcp_server_name: str
    mcp_url: str
    installed: bool = False
    conflict: bool = False


class _OfficialAgentSkillPreview(BaseModel):
    name: str
    exists: bool = False


class _OfficialAgentKbPreview(BaseModel):
    logical_index_name: str
    display_name: Optional[str] = None
    exists: bool = False


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


class _OfficialAgentGithubCategory(BaseModel):
    name: str
    bundles: List = []


class _OfficialAgentGithubGroup(BaseModel):
    name: str
    categories: List = []


class _OfficialAgentGithubDiscoverResult(BaseModel):
    repo: str
    ref: str
    commit: Optional[str] = None
    groups: List = []


class _OfficialAgentGithubInstallResult(BaseModel):
    repo: str
    commit: Optional[str] = None
    results: List = []


consts_model.ModelConnectStatusEnum = _ModelConnectStatusEnum
consts_model.OfficialAgentBundle = _OfficialAgentBundle
consts_model.OfficialAgentListItem = _OfficialAgentListItem
consts_model.OfficialAgentAgentInfo = _OfficialAgentAgentInfo
consts_model.OfficialAgentMcpPreview = _OfficialAgentMcpPreview
consts_model.OfficialAgentSkillPreview = _OfficialAgentSkillPreview
consts_model.OfficialAgentKbPreview = _OfficialAgentKbPreview
consts_model.OfficialAgentInstallItem = _OfficialAgentInstallItem
consts_model.OfficialAgentInstallStep = _OfficialAgentInstallStep
consts_model.OfficialAgentGithubCategory = _OfficialAgentGithubCategory
consts_model.OfficialAgentGithubGroup = _OfficialAgentGithubGroup
consts_model.OfficialAgentGithubDiscoverResult = _OfficialAgentGithubDiscoverResult
consts_model.OfficialAgentGithubInstallResult = _OfficialAgentGithubInstallResult
consts_model.KnowledgeBaseSeedDoc = _KnowledgeBaseSeedDoc
consts_model.SkillZipEntry = _SkillZipEntry
consts_model.ProcessParams = _ProcessParams
sys.modules["consts.model"] = consts_model

from services import official_agent_service  # noqa: E402


@pytest.fixture(autouse=True)
def _no_db_conflict_queries():
    """Keep the skill/KB conflict previews off the real database in unit tests.

    ``_status_item_for_bundle`` now probes existing skills/KBs per bundle; these
    queries are irrelevant to the isolated behaviour under test, so default them
    to "no existing resource" and let individual tests override as needed.
    """
    with patch("database.skill_db.list_skills", return_value=[]), patch(
        "database.knowledge_db.get_knowledge_record", return_value=None
    ):
        yield


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


async def test_item_reports_skill_and_kb_conflicts(tmp_path):
    _write_bundle(tmp_path, "full", has_knowledge=True, skill_count=2)

    fake_remote_db = types.ModuleType("database.remote_mcp_db")
    fake_remote_db.get_mcp_server_by_name_and_tenant = MagicMock(return_value="")

    with patch.object(
        official_agent_service, "OFFICIAL_AGENTS_PATH", str(tmp_path)
    ), patch.object(
        official_agent_service, "_is_agent_installed", return_value=False
    ), patch.object(
        official_agent_service,
        "_missing_model_types",
        new_callable=AsyncMock,
        return_value=[],
    ), patch.dict(sys.modules, {"database.remote_mcp_db": fake_remote_db}), patch(
        "database.skill_db.list_skills",
        return_value=[{"name": "skill-0", "skill_id": 1}],
    ), patch(
        "database.knowledge_db.get_knowledge_record",
        return_value={"index_name": "kb-real", "knowledge_name": "KB"},
    ):
        items = await official_agent_service.list_official_agents_with_status(
            "tenant-1"
        )

    item = items[0]
    # skill-0 exists in the tenant, skill-1 does not
    assert [(s.name, s.exists) for s in item.skills] == [
        ("skill-0", True),
        ("skill-1", False),
    ]
    # KB display name "KB" already exists in the tenant
    assert item.knowledge_bases[0].logical_index_name == "kb-1"
    assert item.knowledge_bases[0].display_name == "KB"
    assert item.knowledge_bases[0].exists is True


async def test_install_forwards_skill_and_kb_renames():
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
        "_install_bundle",
        new_callable=AsyncMock,
        return_value=42,
    ) as mock_install:
        await official_agent_service.install_official_agents(
            ["research"],
            tenant_id="tenant-1",
            user_id="u",
            authorization="auth",
            embedding_model_ids={"research": 9},
            skill_renames={"skill-0": "skill-0-v2"},
            kb_renames={"kb-1": "KB-v2"},
        )

    assert mock_install.await_args.kwargs["skill_renames"] == {
        "skill-0": "skill-0-v2"
    }
    assert mock_install.await_args.kwargs["kb_renames"] == {"kb-1": "KB-v2"}


async def test_install_from_gitcode_forwards_skill_and_kb_renames(tmp_path):
    (tmp_path / "research" / "agent.json").parent.mkdir(parents=True)
    (tmp_path / "research" / "agent.json").write_text(
        json.dumps(_bundle_dict("research", has_knowledge=True)),
        encoding="utf-8",
    )

    bundle = _make_bundle(name="research", has_knowledge=True)
    with patch.object(
        official_agent_service, "_resolve_repo_source", return_value=("url", "o", "r", "main")
    ), patch.object(
        official_agent_service,
        "_gitcode_file_paths",
        return_value=["research/agent.json"],
    ), patch.object(
        official_agent_service,
        "_download_gitcode_bundle",
        return_value=str(tmp_path),
    ), patch.object(
        official_agent_service, "_load_bundle", return_value=bundle
    ), patch.object(
        official_agent_service, "_install_one_bundle", new_callable=AsyncMock
    ) as mock_one:
        await official_agent_service.install_from_gitcode(
            ["research"],
            tenant_id="tenant-1",
            user_id="u",
            authorization="auth",
            skill_renames={"skill-0": "skill-0-v2"},
            kb_renames={"kb-1": "KB-v2"},
        )

    assert mock_one.await_args.kwargs["skill_renames"] == {"skill-0": "skill-0-v2"}
    assert mock_one.await_args.kwargs["kb_renames"] == {"kb-1": "KB-v2"}


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
    mock_mcp.assert_awaited_once_with(
        bundle, "tenant-1", "u", mcp_renames=None, mcp_skips=None
    )
    fake_tool.update_tool_list.assert_awaited_once_with(
        tenant_id="tenant-1", user_id="u"
    )
    fake_agent._create_skills_for_install.assert_awaited_once_with(
        bundle.skills,
        "tenant-1",
        "u",
        reuse_existing_skills=True,
        skill_renames=None,
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


async def test_install_mcp_servers_rename_on_same_name_different_url():
    bundle = _make_bundle(name="research", mcp_count=1)
    fake_remote_db = types.ModuleType("database.remote_mcp_db")
    # renamed name no longer collides -> returns "" so it is created
    fake_remote_db.get_mcp_server_by_name_and_tenant = MagicMock(return_value="")
    fake_mcp_svc = types.ModuleType("services.remote_mcp_service")
    fake_mcp_svc.add_mcp_service = AsyncMock()

    with patch.dict(
        sys.modules,
        {
            "database.remote_mcp_db": fake_remote_db,
            "services.remote_mcp_service": fake_mcp_svc,
        },
    ):
        await official_agent_service._install_mcp_servers(
            bundle, "tenant-1", "u", mcp_renames={"mcp-0": "mcp-0-renamed"}
        )

    fake_mcp_svc.add_mcp_service.assert_awaited_once()
    kwargs = fake_mcp_svc.add_mcp_service.await_args.kwargs
    assert kwargs["name"] == "mcp-0-renamed"
    assert kwargs["server_url"] == "http://mcp-0"


async def test_install_mcp_servers_skips_requested():
    bundle = _make_bundle(name="research", mcp_count=2)
    fake_remote_db = types.ModuleType("database.remote_mcp_db")
    # mcp-0 skipped entirely; mcp-1 missing -> created
    fake_remote_db.get_mcp_server_by_name_and_tenant = MagicMock(
        side_effect=["", ""]
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
        await official_agent_service._install_mcp_servers(
            bundle, "tenant-1", "u", mcp_skips=["mcp-0"]
        )

    fake_mcp_svc.add_mcp_service.assert_awaited_once()
    kwargs = fake_mcp_svc.add_mcp_service.await_args.kwargs
    assert kwargs["name"] == "mcp-1"


def test_mcp_previews_detects_conflict():
    bundle = _make_bundle(name="research", mcp_count=2)
    fake_remote_db = types.ModuleType("database.remote_mcp_db")
    # mcp-0 same url (installed), mcp-1 same name different url (conflict)
    fake_remote_db.get_mcp_server_by_name_and_tenant = MagicMock(
        side_effect=["http://mcp-0", "http://old-url"]
    )

    with patch.dict(sys.modules, {"database.remote_mcp_db": fake_remote_db}):
        previews = official_agent_service._mcp_previews(bundle, "tenant-1")

    assert [(p.mcp_server_name, p.installed, p.conflict) for p in previews] == [
        ("mcp-0", True, False),
        ("mcp-1", False, True),
    ]


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
        bundle, "tenant-1", "u", 5, authorization="auth", kb_renames=None
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
        bundle, "tenant-1", "u", 7, authorization="auth", kb_renames=None
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


# ---------------------------------------------------------------------------
# GitCode 固定源：源解析 / 快照 / 目录发现 / 安装
# ---------------------------------------------------------------------------


def _write_remote_snapshot(tmp_path, rel_paths):
    """Write a minimal agent.json per relative path under tmp_path."""
    for rel in rel_paths:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            '{"agent_id": 1, "agent_info": {"1": {"name": "x"}}, "mcp_info": []}',
            encoding="utf-8",
        )


def test_resolve_repo_source_default():
    with patch.object(
        official_agent_service, "OFFICIAL_AGENTS_REPO_URL", "https://gitcode.com/ModelEngine/AgentsHub"
    ), patch.object(official_agent_service, "OFFICIAL_AGENTS_REPO_REF", "main"):
        url, owner, repo, ref = official_agent_service._resolve_repo_source()
    assert (owner, repo, ref) == ("ModelEngine", "AgentsHub", "main")
    assert url == "https://gitcode.com/ModelEngine/AgentsHub"


def test_resolve_repo_source_prefers_explicit_ref():
    with patch.object(
        official_agent_service, "OFFICIAL_AGENTS_REPO_URL", "https://gitcode.com/ModelEngine/AgentsHub"
    ), patch.object(official_agent_service, "OFFICIAL_AGENTS_REPO_REF", "main"):
        _url, _owner, _repo, ref = official_agent_service._resolve_repo_source(ref="v2")
    assert ref == "v2"


def test_resolve_repo_source_rejects_non_gitcode_host():
    with patch.object(official_agent_service, "OFFICIAL_AGENTS_REPO_URL", "https://github.com/a/b"):
        with pytest.raises(RepoSourceError) as exc:
            official_agent_service._resolve_repo_source()
    assert exc.value.code == "repo_source_not_configured"


def test_resolve_repo_source_rejects_bad_path():
    with patch.object(official_agent_service, "OFFICIAL_AGENTS_REPO_URL", "https://gitcode.com/not-a-repo"):
        with pytest.raises(RepoSourceError) as exc:
            official_agent_service._resolve_repo_source()
    assert exc.value.code == "repo_source_not_configured"


def test_git_clone_snapshot_missing_git(tmp_path):
    with patch.object(official_agent_service.shutil, "which", return_value=None):
        with pytest.raises(RepoSourceError) as exc:
            official_agent_service._git_clone_snapshot(
                "https://gitcode.com/a/b", "main", str(tmp_path / "d")
            )
    assert exc.value.code == "git_binary_missing"


def test_git_clone_snapshot_success(tmp_path):
    clone_result = subprocess.CompletedProcess([], 0, stdout="", stderr="")
    rev_result = subprocess.CompletedProcess([], 0, stdout="abc123\n", stderr="")
    target = str(tmp_path / "d")
    with patch.object(
        official_agent_service.shutil, "which", return_value="/usr/bin/git"
    ), patch.object(
        official_agent_service.subprocess,
        "run",
        side_effect=[clone_result, rev_result],
    ) as mock_run:
        commit = official_agent_service._git_clone_snapshot(
            "https://gitcode.com/a/b", "main", target
        )
    assert commit == "abc123"
    assert mock_run.call_args_list[0].args[0][:7] == [
        "git", "clone", "--depth", "1", "--branch", "main", "https://gitcode.com/a/b",
    ]
    assert mock_run.call_args_list[1].args[0] == [
        "git", "-C", target, "rev-parse", "HEAD",
    ]


def test_git_clone_snapshot_reports_failure(tmp_path):
    err = subprocess.CalledProcessError(128, ["git"], stderr="fatal: could not read")
    with patch.object(
        official_agent_service.shutil, "which", return_value="/usr/bin/git"
    ), patch.object(
        official_agent_service.subprocess, "run", side_effect=err
    ):
        with pytest.raises(RepoSourceError) as exc:
            official_agent_service._git_clone_snapshot(
                "https://gitcode.com/a/b", "main", str(tmp_path / "d")
            )
    assert exc.value.code == "repo_clone_failed"


def test_ensure_repo_snapshot_caches_after_first_clone(tmp_path):
    snapshot_root = tmp_path / "snap"

    def fake_clone(url, ref, staging):
        os.makedirs(staging, exist_ok=True)
        return "abc123"

    with patch.object(
        official_agent_service, "_SNAPSHOT_ROOT", str(snapshot_root)
    ), patch.object(official_agent_service, "SNAPSHOT_MAX_BYTES", 10**9), patch.object(
        official_agent_service, "_git_clone_snapshot", side_effect=fake_clone
    ) as mock_clone:
        d1, c1 = official_agent_service._ensure_repo_snapshot("url", "main")
        d2, c2 = official_agent_service._ensure_repo_snapshot("url", "main")
    assert (c1, c2) == ("abc123", "abc123")
    assert d1 == d2
    assert os.path.isdir(d1)
    mock_clone.assert_called_once()


def test_ensure_repo_snapshot_rejects_oversized(tmp_path):
    snapshot_root = tmp_path / "snap"

    def fake_clone(url, ref, staging):
        os.makedirs(staging, exist_ok=True)
        with open(os.path.join(staging, "big.bin"), "wb") as f:
            f.write(b"x" * 100)
        return "abc123"

    with patch.object(
        official_agent_service, "_SNAPSHOT_ROOT", str(snapshot_root)
    ), patch.object(official_agent_service, "SNAPSHOT_MAX_BYTES", 50), patch.object(
        official_agent_service, "_git_clone_snapshot", side_effect=fake_clone
    ):
        with pytest.raises(RepoSourceError) as exc:
            official_agent_service._ensure_repo_snapshot("url", "main")
    assert exc.value.code == "snapshot_too_large"
    # neither the staging clone nor a cache entry is left behind
    assert not os.path.exists(snapshot_root) or not os.listdir(snapshot_root)


def test_discover_bundles_in_dir_directory_only(tmp_path):
    _write_remote_snapshot(
        tmp_path,
        [
            "行业智能体/医疗/体检报告解读助手/agent.json",
            "行业智能体/医疗/病历助手/agent.json",
            "通用智能体/内容创作/文案创作者/agent.json",
            "通用智能体/内容创作/某助手/agent.json",
        ],
    )
    # loose bundle-shaped JSON files and hidden dirs must be ignored
    (tmp_path / "行业智能体" / "stray.json").write_text("{}", encoding="utf-8")
    (tmp_path / "通用智能体" / "内容创作" / "某助手" / "extra.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".github").mkdir()

    keys = official_agent_service._discover_bundles_in_dir(str(tmp_path))

    assert keys == sorted(
        [
            "行业智能体/医疗/病历助手",
            "行业智能体/医疗/体检报告解读助手",
            "通用智能体/内容创作/文案创作者",
            "通用智能体/内容创作/某助手",
        ]
    )


def test_group_and_categorize_derives_groups():
    keys = [
        "行业智能体/医疗/体检报告解读助手",
        "行业智能体/医疗/病历助手",
        "通用智能体/内容创作/文案创作者",
        "新分组/分类/某助手",
    ]
    grouped = official_agent_service._group_and_categorize(keys)
    assert "行业智能体" in grouped
    assert grouped["行业智能体"]["医疗"] == [
        "行业智能体/医疗/体检报告解读助手",
        "行业智能体/医疗/病历助手",
    ]
    assert grouped["通用智能体"]["内容创作"] == ["通用智能体/内容创作/文案创作者"]
    # unknown first-level group falls into 其他
    assert "新分组" not in grouped
    assert grouped["其他"]["分类"] == ["新分组/分类/某助手"]


async def test_discover_from_gitcode_groups_and_status(tmp_path):
    with patch.object(
        official_agent_service, "OFFICIAL_AGENTS_REPO_URL", "https://gitcode.com/ModelEngine/AgentsHub"
    ), patch.object(official_agent_service, "OFFICIAL_AGENTS_REPO_REF", "main"), patch.object(
        official_agent_service,
        "_ensure_repo_snapshot",
    ) as mock_snapshot, patch.object(
        official_agent_service,
        "_gitcode_file_paths",
        return_value=[
            "行业智能体/医疗/体检报告解读助手/agent.json",
            "通用智能体/内容创作/文案创作者/agent.json",
        ],
    ), patch.object(
        official_agent_service,
        "_is_remote_bundle_installed_with_names",
        return_value=False,
    ):
        result = await official_agent_service.discover_from_gitcode("tenant-1")

    mock_snapshot.assert_not_called()
    assert result.repo == "ModelEngine/AgentsHub"
    assert result.ref == "main"
    assert result.commit is None
    groups = {g.name: g for g in result.groups}
    assert set(groups) == {"行业智能体", "通用智能体"}
    assert {c.name for c in groups["行业智能体"].categories} == {"医疗"}
    assert len(groups["行业智能体"].categories[0].bundles) == 1
    assert groups["行业智能体"].categories[0].bundles[0].name == "行业智能体/医疗/体检报告解读助手"


async def test_install_from_gitcode_success(tmp_path):
    bundle = _make_bundle(name="research")
    fake_item = _OfficialAgentInstallItem(name="k", status="installed")
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    with patch.object(
        official_agent_service, "OFFICIAL_AGENTS_REPO_URL", "https://gitcode.com/ModelEngine/AgentsHub"
    ), patch.object(
        official_agent_service,
        "_gitcode_file_paths",
        return_value=[
            "行业智能体/医疗/a/agent.json",
            "行业智能体/医疗/a/skills/example.zip",
        ],
    ), patch.object(
        official_agent_service,
        "_download_gitcode_bundle",
        return_value=str(staging_dir),
    ), patch.object(
        official_agent_service, "_load_bundle", return_value=bundle
    ), patch.object(
        official_agent_service,
        "_install_one_bundle",
        new_callable=AsyncMock,
        return_value=fake_item,
    ) as mock_install:
        result = await official_agent_service.install_from_gitcode(
            ["行业智能体/医疗/a"],
            tenant_id="t",
            user_id="u",
            authorization="auth",
        )

    assert result.repo == "ModelEngine/AgentsHub"
    assert result.commit is None
    assert result.results[0].status == "installed"
    assert mock_install.await_args.args[:2] == (bundle, "行业智能体/医疗/a")


async def test_install_from_gitcode_not_found(tmp_path):
    with patch.object(
        official_agent_service,
        "_gitcode_file_paths",
        return_value=["行业智能体/医疗/existing/agent.json"],
    ):
        result = await official_agent_service.install_from_gitcode(
            ["行业智能体/医疗/ghost"],
            tenant_id="t",
            user_id="u",
            authorization="auth",
        )
    assert result.results[0].status == "not_found"


def test_attach_md_skill_from_dir(tmp_path):
    _write_dir_bundle(tmp_path, "foldered", skill_names=("my-skill",))
    (tmp_path / "foldered" / "skills" / "my-skill.zip").unlink()
    (tmp_path / "foldered" / "skills" / "my-skill.md").write_text("hello", encoding="utf-8")

    with patch.object(
        official_agent_service, "OFFICIAL_AGENTS_PATH", str(tmp_path)
    ):
        bundle = official_agent_service._load_bundle("foldered")

    assert len(bundle.skills or []) == 1
    import base64 as _b64
    import io as _io
    import zipfile as _zip

    raw = _b64.b64decode(bundle.skills[0].skill_zip_base64)
    with _zip.ZipFile(_io.BytesIO(raw)) as zf:
        assert zf.read("SKILL.md") == b"hello"


def test_clear_repo_snapshot_cache_removes_dir(tmp_path):
    snapshot_root = tmp_path / "snap"
    os.makedirs(snapshot_root, exist_ok=True)
    with patch.object(official_agent_service, "_SNAPSHOT_ROOT", str(snapshot_root)):
        official_agent_service.clear_repo_snapshot_cache()
    assert not os.path.exists(snapshot_root)


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


async def test_create_knowledge_bases_rename_new_binary_docs(tmp_path):
    """重命名新建 + binary 文档时,文档仍会上传并触发处理到新 index。"""
    bundle = _make_bundle(name="research", has_knowledge=True)
    binary_file = tmp_path / "b.docx"
    binary_file.write_bytes(b"%PDF-1.4 fake")
    bundle.knowledge_bases[0].documents = [
        _KnowledgeBaseSeedDoc(file_name="b.docx", file_path=str(binary_file))
    ]
    fake_kb_db = types.ModuleType("database.knowledge_db")
    fake_kb_db.get_knowledge_record = MagicMock(return_value=None)
    fake_vdb = types.ModuleType("services.vectordatabase_service")
    fake_vdb.ElasticSearchService = MagicMock()
    fake_vdb.ElasticSearchService.create_knowledge_base.return_value = {
        "id": "new-abc"
    }
    fake_vdb.get_embedding_model_by_id = MagicMock(return_value=(MagicMock(), 5))
    fake_vdb.get_vector_db_core = MagicMock()
    fake_file_svc = types.ModuleType("services.file_management_service")
    fake_file_svc.upload_files_impl = AsyncMock(
        return_value=([], ["minio/b.docx"], ["b.docx"])
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
            bundle, "tenant-1", "u", embedding_model_id=5, authorization="auth",
            kb_renames={"kb-1": "KB-重命名"},
        )

    assert mapping == {"kb-1": "new-abc"}
    # 用新名创建
    create_kwargs = fake_vdb.ElasticSearchService.create_knowledge_base.call_args.kwargs
    assert create_kwargs["knowledge_name"] == "KB-重命名"
    # binary 文档上传到新 index
    fake_file_svc.upload_files_impl.assert_awaited_once()
    assert fake_file_svc.upload_files_impl.await_args.kwargs["index_name"] == "new-abc"
    # 触发数据处理,使用新 index
    fake_utils.trigger_data_process.assert_awaited_once()
    _, pp = fake_utils.trigger_data_process.await_args.args
    assert pp.index_name == "new-abc"
    assert pp.source_type == "minio"


@pytest.mark.parametrize("part", [None, "", ".", "..", "a/b", r"a\\b"])
def test_safe_path_under_rejects_unsafe_parts(tmp_path, part):
    assert official_agent_service._safe_path_under(str(tmp_path), part) is None


def test_safe_path_under_rejects_resolved_path_escape(tmp_path):
    root = Path(tmp_path)
    outside = root.parent / "outside"
    with patch.object(
        official_agent_service.Path,
        "resolve",
        side_effect=[root, outside],
    ):
        assert official_agent_service._safe_path_under(str(root), "safe") is None


@pytest.mark.parametrize("relative_path", [None, "", "a//b", r"a\\b"])
def test_safe_relative_path_under_rejects_invalid_paths(tmp_path, relative_path):
    assert official_agent_service._safe_relative_path_under(str(tmp_path), relative_path) is None


def test_list_bundle_files_handles_missing_and_oserror(tmp_path):
    with patch.object(official_agent_service.os.path, "isdir", return_value=False):
        assert official_agent_service._list_bundle_files(str(tmp_path)) == []
    with patch.object(official_agent_service.os, "listdir", side_effect=OSError("denied")):
        assert official_agent_service._list_bundle_files(str(tmp_path)) == []


def test_attach_skills_skips_unsafe_and_missing_skill_files(tmp_path):
    bundle = _make_bundle(name="agent", skill_count=0)
    bundle.agent_info[str(bundle.agent_id)].skill_names = ["../bad", "missing"]
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    official_agent_service._attach_skills_from_dir(bundle, str(tmp_path))
    assert bundle.skills == []


def test_attach_kb_docs_skips_invalid_kb_dir(tmp_path):
    bundle = _make_bundle(name="agent", has_knowledge=True)
    bundle.knowledge_bases[0].documents = []
    official_agent_service._attach_kb_docs_from_dir(bundle, "../unsafe")
    official_agent_service._attach_kb_docs_from_dir(bundle, str(tmp_path))
    (tmp_path / "kb").mkdir()
    bundle.knowledge_bases[0].logical_index_name = "../bad"
    official_agent_service._attach_kb_docs_from_dir(bundle, str(tmp_path))
    assert bundle.knowledge_bases[0].documents == []


def test_attach_kb_docs_skips_unsafe_file_and_non_file(tmp_path):
    bundle = _make_bundle(name="agent", has_knowledge=True)
    logical = tmp_path / "kb" / "kb-1"
    logical.mkdir(parents=True)
    (logical / "ok.md").write_text("ok", encoding="utf-8")
    (logical / "subdir").mkdir()
    with patch.object(
        official_agent_service.os,
        "listdir",
        return_value=["../escape", "subdir", "ok.md"],
    ):
        official_agent_service._attach_kb_docs_from_dir(bundle, str(tmp_path))
    assert [doc.file_name for doc in bundle.knowledge_bases[0].documents] == ["ok.md"]


def test_attach_kb_docs_handles_oserror(tmp_path):
    bundle = _make_bundle(name="agent", has_knowledge=True)
    bundle.knowledge_bases[0].documents = []
    (tmp_path / "kb" / "kb-1").mkdir(parents=True)
    with patch.object(official_agent_service.os, "listdir", side_effect=OSError("denied")):
        official_agent_service._attach_kb_docs_from_dir(bundle, str(tmp_path))
    assert bundle.knowledge_bases[0].documents == []


@pytest.mark.parametrize("payload", ["{invalid", {"agent_id": "not-an-int"}])
def test_load_bundle_invalid_json_or_model_returns_none(tmp_path, payload):
    path = tmp_path / "broken.json"
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    assert official_agent_service._load_bundle("broken", str(tmp_path)) is None


def test_load_bundle_invalid_directory_bundle_returns_none(tmp_path):
    bundle_dir = tmp_path / "broken"
    bundle_dir.mkdir()
    (bundle_dir / "agent.json").write_text("{invalid", encoding="utf-8")
    assert official_agent_service._load_bundle("broken", str(tmp_path)) is None


async def test_upload_binary_docs_skips_empty_upload_result(tmp_path):
    doc = tmp_path / "a.pdf"
    doc.write_bytes(b"pdf")
    fake_file_svc = types.ModuleType("services.file_management_service")
    fake_file_svc.upload_files_impl = AsyncMock(return_value=([], [], []))
    fake_utils = types.ModuleType("utils.file_management_utils")
    fake_utils.trigger_data_process = AsyncMock()
    with patch.dict(
        sys.modules,
        {
            "services.file_management_service": fake_file_svc,
            "utils.file_management_utils": fake_utils,
        },
    ):
        await official_agent_service._index_binary_docs(
            [_KnowledgeBaseSeedDoc(file_name="a.pdf", file_path=str(doc))],
            "idx",
            tenant_id="tenant",
            user_id="user",
            embedding_model_id=3,
            authorization="auth",
        )
    fake_utils.trigger_data_process.assert_not_awaited()


@pytest.mark.parametrize(
    "error,code",
    [(subprocess.TimeoutExpired(["git"], 1), "repo_network_error"), (OSError("down"), "repo_network_error")],
)
def test_git_clone_snapshot_handles_network_errors(tmp_path, error, code):
    with patch.object(official_agent_service.shutil, "which", return_value="git"), patch.object(
        official_agent_service.subprocess, "run", side_effect=error
    ):
        with pytest.raises(RepoSourceError) as exc:
            official_agent_service._git_clone_snapshot("url", "main", str(tmp_path / "d"))
    assert exc.value.code == code


def test_snapshot_size_and_commit_file_ignore_oserrors(tmp_path):
    (tmp_path / "x").write_text("x", encoding="utf-8")
    with patch.object(official_agent_service.os.path, "getsize", side_effect=OSError):
        assert official_agent_service._snapshot_size_bytes(str(tmp_path)) == 0
    snapshot_root = tmp_path / "snap"
    snapshot_root.mkdir()
    key = __import__("hashlib").sha1(b"url@main").hexdigest()[:16]
    (snapshot_root / key).mkdir()
    def fake_clone(_url, _ref, staging):
        os.makedirs(staging, exist_ok=True)
        return "commit"

    with patch.object(official_agent_service, "_SNAPSHOT_ROOT", str(snapshot_root)), patch.object(
        official_agent_service, "_git_clone_snapshot", side_effect=fake_clone
    ), patch.object(official_agent_service, "open", side_effect=OSError("read-only"), create=True):
        result = official_agent_service._ensure_repo_snapshot("url", "main")
    assert result[1] == "commit"


def test_gitcode_api_get_decodes_response_and_maps_errors():
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b'{"ok": true}'
    with patch.object(official_agent_service, "urlopen", return_value=Response()) as mock_open:
        assert official_agent_service._gitcode_api_get("https://example.test", {"ref": "main"}) == {"ok": True}
    assert "ref=main" in mock_open.call_args.args[0].full_url
    with patch.object(official_agent_service, "urlopen", side_effect=official_agent_service.URLError("offline")):
        with pytest.raises(RepoSourceError) as exc:
            official_agent_service._gitcode_api_get("https://example.test", {})
    assert exc.value.code == "repo_api_failed"


@pytest.mark.parametrize("payload", [[{"path": "/a"}, {"file_name": "b"}, {"name": "c"}, 3], {"bad": True}])
def test_gitcode_file_paths_normalizes_payloads(payload):
    with patch.object(official_agent_service, "_gitcode_api_get", return_value=payload):
        if isinstance(payload, dict):
            assert official_agent_service._gitcode_file_paths("o", "r", "main") == []
        else:
            assert official_agent_service._gitcode_file_paths("o", "r", "main") == ["a", "b", "c"]


def test_gitcode_agent_metadata_and_installed_checks(monkeypatch):
    with patch.object(official_agent_service, "_gitcode_raw_file", return_value=b'{"agent_info": {"1": {"name": "real"}}}'):
        assert official_agent_service._gitcode_agent_names("o", "r", "main", "group/a") == ["real"]
    with patch.object(
        official_agent_service,
        "_gitcode_raw_file",
        side_effect=RepoSourceError("repo_api_failed", "x"),
    ):
        assert official_agent_service._gitcode_agent_names("o", "r", "main", "group/a") == []
    db = types.ModuleType("database.agent_db")
    db.search_agent_id_by_agent_name = MagicMock(side_effect=[ValueError(), 7])
    with patch.dict(sys.modules, {"database.agent_db": db}):
        assert official_agent_service._is_remote_bundle_installed_with_names("group/a", "t", ["real"])


def test_is_remote_bundle_installed_checks_folder_name():
    db = types.ModuleType("database.agent_db")
    db.search_agent_id_by_agent_name = MagicMock(return_value=7)
    with patch.dict(sys.modules, {"database.agent_db": db}):
        assert official_agent_service._is_remote_bundle_installed("group/a", "t") is True
    db.search_agent_id_by_agent_name.side_effect = ValueError()
    with patch.dict(sys.modules, {"database.agent_db": db}):
        assert official_agent_service._is_remote_bundle_installed("group/a", "t") is False


def test_gitcode_raw_file_maps_http_errors():
    with patch.object(official_agent_service, "urlopen", side_effect=official_agent_service.URLError("offline")):
        with pytest.raises(RepoSourceError) as exc:
            official_agent_service._gitcode_raw_file("o", "r", "main", "a/agent.json")
    assert exc.value.code == "repo_api_failed"


def test_download_gitcode_bundle_validates_missing_path_and_size(tmp_path):
    with pytest.raises(FileNotFoundError):
        official_agent_service._download_gitcode_bundle("o", "r", "main", "missing", [])
    with patch.object(official_agent_service, "SNAPSHOT_MAX_BYTES", 1), patch.object(
        official_agent_service, "_gitcode_raw_file", return_value=b"xx"
    ):
        with pytest.raises(RepoSourceError) as exc:
            official_agent_service._download_gitcode_bundle(
                "o", "r", "main", "group/a", ["group/a/agent.json"]
            )
    assert exc.value.code == "bundle_too_large"
