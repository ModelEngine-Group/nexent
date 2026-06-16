"""Unit tests for agent marketplace repository service."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Mock DB layer before importing the service under test
sys.modules.setdefault("sqlalchemy", MagicMock())
sys.modules.setdefault("sqlalchemy.dialects", MagicMock())
sys.modules.setdefault("sqlalchemy.dialects.postgresql", MagicMock())

_agent_repo_db_mock = MagicMock()
_agent_repo_db_mock.STATUS_PENDING_REVIEW = "PENDING_REVIEW"
_agent_repo_db_mock.VALID_REPOSITORY_STATUSES = frozenset({
    "NOT_SHARED",
    "PENDING_REVIEW",
    "REJECTED",
    "SHARED",
})
_agent_repo_db_mock.get_agent_repository_by_id = MagicMock()
_agent_repo_db_mock.get_agent_repository_by_agent_id = MagicMock()
_agent_repo_db_mock.insert_agent_repository_record = MagicMock()
_agent_repo_db_mock.update_agent_repository_by_id = MagicMock()
sys.modules["database.agent_repository_db"] = _agent_repo_db_mock

_agent_db_mock = MagicMock()
_agent_db_mock.search_agent_info_by_agent_id = MagicMock()
sys.modules["database.agent_db"] = _agent_db_mock

_agent_version_db_mock = MagicMock()
_agent_version_db_mock.search_version_by_version_no = MagicMock()
sys.modules["database.agent_version_db"] = _agent_version_db_mock

class _SkillZipEntryMock:
    def __init__(self, skill_name: str, skill_zip_base64: str):
        self.skill_name = skill_name
        self.skill_zip_base64 = skill_zip_base64


class _AgentRepositorySnapshotMock:
    def __init__(self, **kwargs):
        self._data = kwargs

    def model_dump(self):
        data = dict(self._data)
        skills = data.get("skills")
        if skills:
            data["skills"] = [
                {
                    "skill_name": entry.skill_name,
                    "skill_zip_base64": entry.skill_zip_base64,
                }
                for entry in skills
            ]
        return data


_consts_model_mock = MagicMock()
_consts_model_mock.AgentRepositorySnapshot = _AgentRepositorySnapshotMock
_consts_model_mock.SkillZipEntry = _SkillZipEntryMock
sys.modules["consts.model"] = _consts_model_mock

_agent_service_mock = MagicMock()
_agent_service_mock.collect_skill_zip_entries = MagicMock(return_value=[])
_agent_service_mock.export_agent_dict_for_repository_impl = AsyncMock(return_value={
    "agent_id": 1,
    "agent_info": {
        "1": {
            "agent_id": 1,
            "name": "agent_one",
            "description": "desc",
            "business_description": "biz",
            "max_steps": 5,
            "provide_run_summary": False,
            "enabled": True,
            "tools": [],
            "managed_agents": [],
        }
    },
    "mcp_info": [],
})
sys.modules["services.agent_service"] = _agent_service_mock

from consts.const import ASSET_OWNER_TENANT_ID

from backend.services import agent_repository_service as ars


@pytest.mark.asyncio
async def test_create_agent_repository_listing_impl_success():
    agent_info_json = {
        "agent_id": 1,
        "agent_info": {"1": {"agent_id": 1, "name": "agent_one"}},
        "mcp_info": [],
        "skills": None,
    }
    with patch.object(
        ars, "_build_repository_data_from_agent", new_callable=AsyncMock
    ) as mock_build_data, patch.object(
        ars, "get_agent_repository_by_agent_id"
    ) as mock_get_by_agent_id, patch.object(
        ars, "insert_agent_repository_record"
    ) as mock_insert, patch.object(
        ars, "get_agent_repository_by_id"
    ) as mock_get_by_id:
        mock_build_data.return_value = {
            "agent_id": 1,
            "source_version_no": 1,
            "name": "agent_one",
            "agent_info_json": agent_info_json,
            "status": "PENDING_REVIEW",
        }
        mock_get_by_agent_id.return_value = None
        mock_insert.return_value = 42
        mock_get_by_id.return_value = {
            "agent_repository_id": 42,
            "agent_id": 1,
            "name": "agent_one",
            "agent_info_json": agent_info_json,
            "source_version_no": 1,
            "status": "PENDING_REVIEW",
            "tags": [],
        }

        result = await ars.create_agent_repository_listing_impl(
            agent_id=1,
            tenant_id="tenant_a",
            user_id="user_a",
            version_no=1,
        )

    assert result["agent_repository_id"] == 42
    assert result["agent_info_json"] == agent_info_json
    assert result["is_updated"] is False
    mock_insert.assert_called_once()
    mock_get_by_agent_id.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_create_agent_repository_listing_impl_updates_existing():
    agent_info_json = {
        "agent_id": 1,
        "agent_info": {"1": {"agent_id": 1, "name": "agent_one"}},
        "mcp_info": [],
        "skills": None,
    }
    with patch.object(
        ars, "_build_repository_data_from_agent", new_callable=AsyncMock
    ) as mock_build_data, patch.object(
        ars, "get_agent_repository_by_agent_id"
    ) as mock_get_by_agent_id, patch.object(
        ars, "update_agent_repository_by_id"
    ) as mock_update, patch.object(
        ars, "get_agent_repository_by_id"
    ) as mock_get_by_id:
        mock_build_data.return_value = {
            "agent_id": 1,
            "source_version_no": 2,
            "name": "agent_one",
            "agent_info_json": agent_info_json,
            "status": "PENDING_REVIEW",
        }
        mock_get_by_agent_id.return_value = {"agent_repository_id": 42}
        mock_update.return_value = 1
        mock_get_by_id.return_value = {
            "agent_repository_id": 42,
            "agent_id": 1,
            "name": "agent_one",
            "agent_info_json": agent_info_json,
            "source_version_no": 2,
            "status": "PENDING_REVIEW",
            "tags": [],
        }

        result = await ars.create_agent_repository_listing_impl(
            agent_id=1,
            tenant_id="tenant_a",
            user_id="user_a",
            version_no=2,
        )

    assert result["agent_repository_id"] == 42
    assert result["is_updated"] is True
    mock_update.assert_called_once()
    mock_update.assert_called_with(
        repository_id=42,
        publisher_tenant_id="tenant_a",
        user_id="user_a",
        updates={
            "source_version_no": 2,
            "agent_info_json": agent_info_json,
            "status": "PENDING_REVIEW",
        },
    )


@pytest.mark.asyncio
async def test_create_agent_repository_listing_impl_accepts_draft_version():
    agent_info_json = {
        "agent_id": 1,
        "agent_info": {"1": {"agent_id": 1, "name": "agent_one"}},
        "mcp_info": [],
        "skills": None,
    }
    with patch.object(
        ars, "_build_repository_data_from_agent", new_callable=AsyncMock
    ) as mock_build_data, patch.object(
        ars, "get_agent_repository_by_agent_id"
    ) as mock_get_by_agent_id, patch.object(
        ars, "insert_agent_repository_record"
    ) as mock_insert, patch.object(
        ars, "get_agent_repository_by_id"
    ) as mock_get_by_id:
        mock_build_data.return_value = {
            "agent_id": 1,
            "source_version_no": 0,
            "name": "agent_one",
            "agent_info_json": agent_info_json,
            "status": "PENDING_REVIEW",
        }
        mock_get_by_agent_id.return_value = None
        mock_insert.return_value = 42
        mock_get_by_id.return_value = {
            "agent_repository_id": 42,
            "agent_id": 1,
            "name": "agent_one",
            "agent_info_json": agent_info_json,
            "source_version_no": 0,
            "status": "PENDING_REVIEW",
            "tags": [],
        }

        result = await ars.create_agent_repository_listing_impl(
            agent_id=1,
            tenant_id="tenant_a",
            user_id="user_a",
            version_no=0,
        )

    assert result["agent_repository_id"] == 42
    assert result["source_version_no"] == 0
    mock_build_data.assert_awaited_once_with(1, "tenant_a", "user_a", 0)


@pytest.mark.asyncio
async def test_create_agent_repository_listing_impl_rejects_negative_version():
    with pytest.raises(ValueError, match="version_no must be >= 0"):
        await ars.create_agent_repository_listing_impl(
            agent_id=1,
            tenant_id="tenant_a",
            user_id="user_a",
            version_no=-1,
        )


def test_validate_create_payload_requires_agent_info_json():
    with pytest.raises(ValueError, match="agent_info_json"):
        ars._validate_create_payload({
            "agent_id": 1,
            "source_version_no": 1,
            "name": "agent_one",
        })

    with pytest.raises(ValueError, match="agent_info_json must contain"):
        ars._validate_create_payload({
            "agent_id": 1,
            "source_version_no": 1,
            "name": "agent_one",
            "agent_info_json": {"agent_id": 1},
        })


@pytest.mark.asyncio
async def test_build_repository_data_from_agent_includes_skills():
    SkillZipEntry = _consts_model_mock.SkillZipEntry

    _agent_db_mock.search_agent_info_by_agent_id.return_value = {
        "name": "agent_one",
        "display_name": "Agent One",
        "description": "desc",
        "author": "author",
    }
    _agent_service_mock.export_agent_dict_for_repository_impl.return_value = {
        "agent_id": 1,
        "agent_info": {
            "1": {
                "agent_id": 1,
                "name": "agent_one",
                "description": "desc",
                "business_description": "biz",
                "max_steps": 5,
                "provide_run_summary": False,
                "enabled": True,
                "tools": [],
                "managed_agents": [],
            }
        },
        "mcp_info": [],
    }
    _agent_service_mock.collect_skill_zip_entries.return_value = [
        SkillZipEntry(skill_name="SkillA", skill_zip_base64="abc=")
    ]
    _agent_version_db_mock.search_version_by_version_no.return_value = {
        "version_name": "v1.0"
    }

    result = await ars._build_repository_data_from_agent(
        agent_id=1,
        tenant_id="tenant_a",
        user_id="user_a",
        version_no=1,
    )

    assert result["agent_info_json"]["agent_id"] == 1
    assert result["agent_info_json"]["skills"][0]["skill_name"] == "SkillA"
    assert result["version_label"] == "v1.0"


def test_validate_agent_info_json_rejects_asset_owner_agent():
    agent_info_json = {
        "agent_id": 1,
        "agent_info": {
            "1": {"agent_id": 1, "tenant_id": ASSET_OWNER_TENANT_ID, "name": "owner_agent"},
        },
        "mcp_info": [],
    }
    with pytest.raises(ValueError, match="租户管理员智能体无法共享"):
        ars._validate_agent_info_json_shareable(agent_info_json)


def test_validate_agent_info_json_allows_normal_tenant():
    agent_info_json = {
        "agent_id": 1,
        "agent_info": {
            "1": {"agent_id": 1, "tenant_id": "tenant_a", "name": "agent_one"},
            "2": {"agent_id": 2, "tenant_id": "tenant_b", "name": "sub_agent"},
        },
        "mcp_info": [],
    }
    ars._validate_agent_info_json_shareable(agent_info_json)


@pytest.mark.asyncio
async def test_build_repository_data_from_agent_rejects_asset_owner():
    _agent_db_mock.search_agent_info_by_agent_id.return_value = {
        "name": "agent_one",
        "display_name": "Agent One",
        "description": "desc",
        "author": "author",
    }
    _agent_service_mock.export_agent_dict_for_repository_impl.return_value = {
        "agent_id": 1,
        "agent_info": {
            "1": {
                "agent_id": 1,
                "tenant_id": "tenant_a",
                "name": "agent_one",
                "description": "desc",
                "business_description": "biz",
                "max_steps": 5,
                "provide_run_summary": False,
                "enabled": True,
                "tools": [],
                "managed_agents": [],
            },
            "2": {
                "agent_id": 2,
                "tenant_id": ASSET_OWNER_TENANT_ID,
                "name": "sub_owner_agent",
                "description": "desc",
                "business_description": "biz",
                "max_steps": 5,
                "provide_run_summary": False,
                "enabled": True,
                "tools": [],
                "managed_agents": [],
            },
        },
        "mcp_info": [],
    }
    _agent_service_mock.collect_skill_zip_entries.return_value = []
    _agent_version_db_mock.search_version_by_version_no.return_value = {
        "version_name": "v1.0"
    }

    with pytest.raises(ValueError, match="租户管理员智能体无法共享"):
        await ars._build_repository_data_from_agent(
            agent_id=1,
            tenant_id="tenant_a",
            user_id="user_a",
            version_no=1,
        )
