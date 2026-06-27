"""Unit tests for agent marketplace repository service."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Mock DB layer before importing the service under test
sys.modules.setdefault("sqlalchemy", MagicMock())
sys.modules.setdefault("sqlalchemy.dialects", MagicMock())
sys.modules.setdefault("sqlalchemy.dialects.postgresql", MagicMock())

_agent_repo_db_mock = MagicMock()
_agent_repo_db_mock.get_agent_repository_by_id = MagicMock()
_agent_repo_db_mock.get_agent_repository_by_id_and_publisher = MagicMock()
_agent_repo_db_mock.get_agent_repository_by_agent_id = MagicMock()
_agent_repo_db_mock.insert_agent_repository_record = MagicMock()
_agent_repo_db_mock.update_agent_repository_by_id = MagicMock()
_agent_repo_db_mock.update_agent_repository_status_by_id = MagicMock()
_agent_repo_db_mock.reset_agent_repository_status = MagicMock()
_agent_repo_db_mock.increment_agent_repository_downloads = MagicMock(return_value=1)
_agent_repo_db_mock.sum_agent_repository_downloads_by_agent_ids = MagicMock(return_value={})
_agent_repo_db_mock.fetch_draft_agent_mine_metadata = MagicMock(return_value={})
_agent_repo_db_mock.list_agent_repository_by_agent_ids = MagicMock(return_value=[])
sys.modules["database.agent_repository_db"] = _agent_repo_db_mock

_user_tenant_db_mock = MagicMock()
_user_tenant_db_mock.get_user_tenant_by_user_id = MagicMock()
sys.modules["database.user_tenant_db"] = _user_tenant_db_mock

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
        for key, value in kwargs.items():
            setattr(self, key, value)

    @classmethod
    def model_validate(cls, data):
        instance = cls(**data)
        if not hasattr(instance, "skills"):
            instance.skills = data.get("skills")
        return instance

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
_agent_service_mock.list_all_agent_info_impl = AsyncMock(return_value=[])
sys.modules["services.agent_service"] = _agent_service_mock

_precheck_mock = MagicMock()
_precheck_mock.build_repository_import_precheck = MagicMock()
sys.modules["services.repository_import_precheck"] = _precheck_mock

from consts.const import ASSET_OWNER_TENANT_ID
from consts.exceptions import UnauthorizedError

from backend.services import agent_repository_service as ars


def _repository_record(
    *,
    agent_repository_id: int = 1,
    agent_id: int = 10,
    status: str = "not_shared",
    publisher_tenant_id: str = "tenant_a",
    publisher_user_id: str = "user_a",
) -> dict:
    return {
        "agent_repository_id": agent_repository_id,
        "agent_id": agent_id,
        "author": "author",
        "name": "agent_one",
        "display_name": "Agent One",
        "description": "desc",
        "status": status,
        "publisher_tenant_id": publisher_tenant_id,
        "publisher_user_id": publisher_user_id,
    }


def _pending_review_reset_calls(
    *,
    agent_repository_id: int = 1,
    agent_id: int = 10,
    publisher_tenant_id: str = "tenant_a",
) -> list:
    return [
        call(
            agent_repository_id=agent_repository_id,
            agent_id=agent_id,
            status="pending_review",
            publisher_tenant_id=publisher_tenant_id,
        ),
        call(
            agent_repository_id=agent_repository_id,
            agent_id=agent_id,
            status="rejected",
            publisher_tenant_id=publisher_tenant_id,
        ),
    ]


def test_list_repository_listings_passes_agent_id_to_db():
    with patch.object(
        ars,
        "list_agent_repository_summaries",
        return_value=[_repository_record(agent_repository_id=1, agent_id=123)],
    ) as mock_list:
        result = ars.list_agent_repository_listings_impl(
            "tenant_a",
            status="shared",
            agent_id=123,
        )

    mock_list.assert_called_once_with(
        publisher_tenant_id="tenant_a",
        status="shared",
        agent_id=123,
        category_id=None,
    )
    assert [item["agent_repository_id"] for item in result["items"]] == [1]
    assert result["pagination"] == {
        "page": 1,
        "page_size": 10,
        "total": 1,
        "total_pages": 1,
    }


def test_list_repository_listings_filters_by_search_before_pagination():
    records = [
        {
            **_repository_record(
                agent_repository_id=1,
                agent_id=10,
                status="shared",
            ),
            "display_name": "Alpha Agent",
        },
        {
            **_repository_record(
                agent_repository_id=2,
                agent_id=11,
                status="shared",
            ),
            "display_name": "Beta Agent",
        },
        {
            **_repository_record(
                agent_repository_id=3,
                agent_id=12,
                status="shared",
            ),
            "display_name": "Gamma Agent",
        },
    ]

    with patch.object(ars, "list_agent_repository_summaries", return_value=records):
        result = ars.list_agent_repository_listings_impl(
            "tenant_a",
            status="shared",
            page=1,
            page_size=2,
            search="beta",
        )

    assert [item["agent_repository_id"] for item in result["items"]] == [2]
    assert result["pagination"] == {
        "page": 1,
        "page_size": 2,
        "total": 1,
        "total_pages": 1,
    }


def test_list_repository_listings_paginates_filtered_records():
    records = [
        {
            **_repository_record(
                agent_repository_id=index,
                agent_id=index,
                status="shared",
            ),
            "display_name": f"Agent {index}",
        }
        for index in range(1, 8)
    ]

    with patch.object(ars, "list_agent_repository_summaries", return_value=records):
        result = ars.list_agent_repository_listings_impl(
            "tenant_a",
            status="shared",
            page=2,
            page_size=6,
        )

    assert [item["agent_repository_id"] for item in result["items"]] == [7]
    assert result["pagination"] == {
        "page": 2,
        "page_size": 6,
        "total": 7,
        "total_pages": 2,
    }


def test_list_repository_listings_search_matches_author_and_tags():
    records = [
        {
            **_repository_record(agent_repository_id=1, status="shared"),
            "author": "alice@example.com",
            "tags": [],
        },
        {
            **_repository_record(agent_repository_id=2, status="shared"),
            "author": "bob@example.com",
            "tags": ["marketing"],
        },
    ]

    with patch.object(ars, "list_agent_repository_summaries", return_value=records):
        by_author = ars.list_agent_repository_listings_impl(
            "tenant_a",
            status="shared",
            search="alice",
        )
        by_tag = ars.list_agent_repository_listings_impl(
            "tenant_a",
            status="shared",
            search="marketing",
        )

    assert [item["agent_repository_id"] for item in by_author["items"]] == [1]
    assert [item["agent_repository_id"] for item in by_tag["items"]] == [2]


def test_list_repository_listings_rejects_invalid_status_with_agent_id():
    with patch.object(ars, "list_agent_repository_summaries") as mock_list:
        with pytest.raises(ValueError, match="Invalid status"):
            ars.list_agent_repository_listings_impl(
                "tenant_a",
                status="invalid",
                agent_id=123,
            )

    mock_list.assert_not_called()


def test_normalize_listing_tags_trims_dedupes_and_limits():
    assert ars._normalize_listing_tags([" 营销 ", "营销", "数据"]) == ["营销", "数据"]

    with pytest.raises(ValueError, match="at least one"):
        ars._normalize_listing_tags([" ", ""])

    with pytest.raises(ValueError, match="at most 5"):
        ars._normalize_listing_tags(["a", "b", "c", "d", "e", "f"])


def test_validate_card_fields_requires_structural_values():
    base = {
        "agent_id": 1,
        "version_no": 1,
        "name": "agent_one",
        "agent_info_json": {
            "agent_id": 1,
            "agent_info": {"1": {"agent_id": 1}},
            "mcp_info": [],
        },
    }

    with pytest.raises(ValueError, match="icon is required"):
        ars._validate_create_payload(base)

    with pytest.raises(ValueError, match="category_id is required"):
        ars._validate_create_payload({**base, "icon": "🤖"})

    with pytest.raises(ValueError, match="tags is required"):
        ars._validate_create_payload({**base, "icon": "🤖", "category_id": 1})

    with pytest.raises(ValueError, match="non-empty string"):
        ars._validate_create_payload({
            **base,
            "icon": "   ",
            "category_id": 1,
            "tags": ["marketing"],
        })

    ars._validate_create_payload({
        **base,
        "icon": "🤖",
        "category_id": 99,
        "tags": ["marketing"],
    })


def _list_all_agent_record(
    *,
    agent_id: int = 1,
    name: str = "agent_one",
    display_name: str = "Agent One",
    permission: str = "EDIT",
) -> dict:
    return {
        "agent_id": agent_id,
        "name": name,
        "display_name": display_name,
        "description": "desc",
        "permission": permission,
    }


def _mine_metadata_record(
    *,
    agent_id: int = 1,
    created_by: str = "user_a",
    current_version_no: int = 0,
    version_name: str = "v0",
) -> dict:
    return {
        "created_by": created_by,
        "current_version_no": current_version_no,
        "version_name": version_name,
        "version_create_time": None,
    }


@pytest.mark.asyncio
async def test_list_my_editable_agents_impl_returns_items_and_counts():
    agents = [
        _list_all_agent_record(agent_id=1),
        _list_all_agent_record(agent_id=2, name="agent_two", display_name="Agent Two"),
    ]
    meta_by_id = {
        1: _mine_metadata_record(agent_id=1, created_by="user_a"),
        2: _mine_metadata_record(agent_id=2, created_by="user_b"),
    }

    with patch.object(
        ars, "list_all_agent_info_impl", new_callable=AsyncMock, return_value=agents
    ) as mock_list_all, patch.object(
        ars, "fetch_draft_agent_mine_metadata", return_value=meta_by_id
    ) as mock_meta, patch.object(
        ars, "list_agent_repository_by_agent_ids", return_value=[]
    ) as mock_repo_list:
        result = await ars.list_my_editable_agents_impl(
            tenant_id="tenant_a",
            user_id="user_a",
            ownership="created",
        )

    mock_list_all.assert_awaited_once_with(tenant_id="tenant_a", user_id="user_a")
    mock_meta.assert_called_once_with("tenant_a", [1, 2])
    mock_repo_list.assert_called_once()
    assert "rejected" in mock_repo_list.call_args.kwargs["statuses"]
    assert result["counts"] == {"all": 2, "created": 1, "others": 1}
    assert result["pagination"] == {
        "page": 1,
        "page_size": 10,
        "total": 1,
        "total_pages": 1,
    }
    assert len(result["items"]) == 1
    assert result["items"][0]["agent_id"] == 1
    assert result["items"][0]["name"] == "Agent One"
    assert result["items"][0]["permission"] == "EDIT"
    assert result["items"][0]["repository_info"] == []
    assert result["pagination"] == {
        "page": 1,
        "page_size": 10,
        "total": 1,
        "total_pages": 1,
    }


@pytest.mark.asyncio
async def test_list_my_editable_agents_impl_includes_rejected_repository_info():
    agents = [_list_all_agent_record(agent_id=1)]
    meta_by_id = {1: _mine_metadata_record(agent_id=1)}
    rejected_record = {
        "agent_repository_id": 99,
        "agent_id": 1,
        "status": "rejected",
        "version_no": 2,
        "version_name": "v2",
        "create_time": "2026-06-01T00:00:00",
    }

    with patch.object(
        ars, "list_all_agent_info_impl", new_callable=AsyncMock, return_value=agents
    ), patch.object(
        ars, "fetch_draft_agent_mine_metadata", return_value=meta_by_id
    ), patch.object(
        ars, "list_agent_repository_by_agent_ids", return_value=[rejected_record]
    ):
        result = await ars.list_my_editable_agents_impl(
            tenant_id="tenant_a",
            user_id="user_a",
            ownership="all",
        )

    repository_info = result["items"][0]["repository_info"]
    assert len(repository_info) == 1
    assert repository_info[0]["agent_repository_id"] == 99
    assert repository_info[0]["status"] == "rejected"
    assert repository_info[0]["version_no"] == 2


@pytest.mark.asyncio
async def test_list_my_editable_agents_impl_returns_empty_items_with_counts():
    with patch.object(
        ars, "list_all_agent_info_impl", new_callable=AsyncMock, return_value=[]
    ), patch.object(
        ars, "fetch_draft_agent_mine_metadata", return_value={}
    ), patch.object(
        ars, "list_agent_repository_by_agent_ids"
    ) as mock_repo_list:
        result = await ars.list_my_editable_agents_impl(
            tenant_id="tenant_a",
            user_id="user_a",
            ownership="all",
        )

    mock_repo_list.assert_not_called()
    assert result == {
        "items": [],
        "counts": {"all": 0, "created": 0, "others": 0},
        "pagination": {
            "page": 1,
            "page_size": 10,
            "total": 0,
            "total_pages": 0,
        },
    }


@pytest.mark.asyncio
async def test_list_my_editable_agents_impl_includes_read_only_agents():
    agents = [
        _list_all_agent_record(agent_id=1, permission="EDIT"),
        _list_all_agent_record(
            agent_id=2,
            name="shared_agent",
            display_name="Shared Agent",
            permission="READ_ONLY",
        ),
    ]
    meta_by_id = {
        1: _mine_metadata_record(agent_id=1, created_by="user_a"),
        2: _mine_metadata_record(agent_id=2, created_by="user_b"),
    }

    with patch.object(
        ars, "list_all_agent_info_impl", new_callable=AsyncMock, return_value=agents
    ), patch.object(
        ars, "fetch_draft_agent_mine_metadata", return_value=meta_by_id
    ), patch.object(
        ars, "list_agent_repository_by_agent_ids", return_value=[]
    ):
        result = await ars.list_my_editable_agents_impl(
            tenant_id="tenant_a",
            user_id="user_a",
            ownership="all",
        )

    assert len(result["items"]) == 2
    read_only_item = next(item for item in result["items"] if item["agent_id"] == 2)
    assert read_only_item["permission"] == "READ_ONLY"


@pytest.mark.asyncio
async def test_list_my_editable_agents_impl_filters_others_ownership():
    agents = [
        _list_all_agent_record(agent_id=1),
        _list_all_agent_record(agent_id=2, name="agent_two", display_name="Agent Two"),
    ]
    meta_by_id = {
        1: _mine_metadata_record(agent_id=1, created_by="user_a"),
        2: _mine_metadata_record(agent_id=2, created_by="user_b"),
    }

    with patch.object(
        ars, "list_all_agent_info_impl", new_callable=AsyncMock, return_value=agents
    ), patch.object(
        ars, "fetch_draft_agent_mine_metadata", return_value=meta_by_id
    ), patch.object(
        ars, "list_agent_repository_by_agent_ids", return_value=[]
    ):
        result = await ars.list_my_editable_agents_impl(
            tenant_id="tenant_a",
            user_id="user_a",
            ownership="others",
        )

    assert len(result["items"]) == 1
    assert result["items"][0]["agent_id"] == 2
    assert result["counts"] == {"all": 2, "created": 1, "others": 1}


@pytest.mark.asyncio
async def test_list_my_editable_agents_impl_paginates_filtered_agents():
    agents = [
        _list_all_agent_record(agent_id=index, name=f"agent_{index}")
        for index in range(1, 6)
    ]
    meta_by_id = {
        index: _mine_metadata_record(agent_id=index, created_by="user_a")
        for index in range(1, 6)
    }

    with patch.object(
        ars, "list_all_agent_info_impl", new_callable=AsyncMock, return_value=agents
    ), patch.object(
        ars, "fetch_draft_agent_mine_metadata", return_value=meta_by_id
    ), patch.object(
        ars, "list_agent_repository_by_agent_ids", return_value=[]
    ) as mock_repo_list:
        result = await ars.list_my_editable_agents_impl(
            tenant_id="tenant_a",
            user_id="user_a",
            ownership="all",
            page=2,
            page_size=2,
        )

    assert [item["agent_id"] for item in result["items"]] == [3, 4]
    assert result["pagination"] == {
        "page": 2,
        "page_size": 2,
        "total": 5,
        "total_pages": 3,
    }
    mock_repo_list.assert_called_once()
    assert mock_repo_list.call_args.args[0] == [3, 4]


@pytest.mark.asyncio
async def test_list_my_editable_agents_impl_page1_with_new_agent_padding():
    agents = [
        _list_all_agent_record(agent_id=index, name=f"agent_{index}")
        for index in range(1, 6)
    ]
    meta_by_id = {
        index: _mine_metadata_record(agent_id=index, created_by="user_a")
        for index in range(1, 6)
    }

    with patch.object(
        ars, "list_all_agent_info_impl", new_callable=AsyncMock, return_value=agents
    ), patch.object(
        ars, "fetch_draft_agent_mine_metadata", return_value=meta_by_id
    ), patch.object(
        ars, "list_agent_repository_by_agent_ids", return_value=[]
    ) as mock_repo_list:
        result = await ars.list_my_editable_agents_impl(
            tenant_id="tenant_a",
            user_id="user_a",
            ownership="all",
            page=1,
            page_size=6,
            new_agent_padding=True,
        )

    assert result["items"][0] == {"new_agent_padding": True}
    assert [item["agent_id"] for item in result["items"][1:]] == [1, 2, 3, 4, 5]
    assert result["counts"] == {"all": 5, "created": 5, "others": 0}
    assert result["pagination"] == {
        "page": 1,
        "page_size": 6,
        "total": 6,
        "total_pages": 1,
    }
    mock_repo_list.assert_called_once()
    assert mock_repo_list.call_args.args[0] == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_list_my_editable_agents_impl_page2_with_new_agent_padding():
    agents = [
        _list_all_agent_record(agent_id=index, name=f"agent_{index}")
        for index in range(1, 7)
    ]
    meta_by_id = {
        index: _mine_metadata_record(agent_id=index, created_by="user_a")
        for index in range(1, 7)
    }

    with patch.object(
        ars, "list_all_agent_info_impl", new_callable=AsyncMock, return_value=agents
    ), patch.object(
        ars, "fetch_draft_agent_mine_metadata", return_value=meta_by_id
    ), patch.object(
        ars, "list_agent_repository_by_agent_ids", return_value=[]
    ) as mock_repo_list:
        result = await ars.list_my_editable_agents_impl(
            tenant_id="tenant_a",
            user_id="user_a",
            ownership="all",
            page=2,
            page_size=6,
            new_agent_padding=True,
        )

    assert [item["agent_id"] for item in result["items"]] == [6]
    assert result["pagination"] == {
        "page": 2,
        "page_size": 6,
        "total": 7,
        "total_pages": 2,
    }
    mock_repo_list.assert_called_once()
    assert mock_repo_list.call_args.args[0] == [6]


@pytest.mark.asyncio
async def test_list_my_editable_agents_impl_zero_agents_with_new_agent_padding():
    with patch.object(
        ars, "list_all_agent_info_impl", new_callable=AsyncMock, return_value=[]
    ), patch.object(
        ars, "fetch_draft_agent_mine_metadata", return_value={}
    ), patch.object(
        ars, "list_agent_repository_by_agent_ids", return_value=[]
    ) as mock_repo_list:
        result = await ars.list_my_editable_agents_impl(
            tenant_id="tenant_a",
            user_id="user_a",
            ownership="all",
            page=1,
            page_size=6,
            new_agent_padding=True,
        )

    assert result["items"] == [{"new_agent_padding": True}]
    assert result["counts"] == {"all": 0, "created": 0, "others": 0}
    assert result["pagination"] == {
        "page": 1,
        "page_size": 6,
        "total": 1,
        "total_pages": 1,
    }
    mock_repo_list.assert_not_called()


@pytest.mark.asyncio
async def test_list_my_editable_agents_impl_ignores_padding_with_search():
    agents = [_list_all_agent_record(agent_id=1)]
    meta_by_id = {1: _mine_metadata_record(agent_id=1, created_by="user_a")}

    with patch.object(
        ars, "list_all_agent_info_impl", new_callable=AsyncMock, return_value=agents
    ), patch.object(
        ars, "fetch_draft_agent_mine_metadata", return_value=meta_by_id
    ), patch.object(
        ars, "list_agent_repository_by_agent_ids", return_value=[]
    ):
        result = await ars.list_my_editable_agents_impl(
            tenant_id="tenant_a",
            user_id="user_a",
            ownership="all",
            page=1,
            page_size=6,
            search="agent",
            new_agent_padding=True,
        )

    assert result["items"][0]["agent_id"] == 1
    assert result["pagination"]["total"] == 1


@pytest.mark.asyncio
async def test_list_my_editable_agents_impl_ignores_padding_with_created_ownership():
    agents = [_list_all_agent_record(agent_id=1)]
    meta_by_id = {1: _mine_metadata_record(agent_id=1, created_by="user_a")}

    with patch.object(
        ars, "list_all_agent_info_impl", new_callable=AsyncMock, return_value=agents
    ), patch.object(
        ars, "fetch_draft_agent_mine_metadata", return_value=meta_by_id
    ), patch.object(
        ars, "list_agent_repository_by_agent_ids", return_value=[]
    ):
        result = await ars.list_my_editable_agents_impl(
            tenant_id="tenant_a",
            user_id="user_a",
            ownership="created",
            page=1,
            page_size=6,
            new_agent_padding=True,
        )

    assert result["items"][0]["agent_id"] == 1
    assert result["pagination"]["total"] == 1


@pytest.mark.asyncio
async def test_list_my_editable_agents_impl_filters_by_search_before_pagination():
    agents = [
        _list_all_agent_record(agent_id=1, display_name="Alpha Agent"),
        _list_all_agent_record(agent_id=2, display_name="Beta Agent"),
        _list_all_agent_record(agent_id=3, display_name="Gamma Agent"),
    ]
    meta_by_id = {
        1: _mine_metadata_record(agent_id=1, created_by="user_a"),
        2: _mine_metadata_record(agent_id=2, created_by="user_a"),
        3: _mine_metadata_record(agent_id=3, created_by="user_a"),
    }

    with patch.object(
        ars, "list_all_agent_info_impl", new_callable=AsyncMock, return_value=agents
    ), patch.object(
        ars, "fetch_draft_agent_mine_metadata", return_value=meta_by_id
    ), patch.object(
        ars, "list_agent_repository_by_agent_ids", return_value=[]
    ):
        result = await ars.list_my_editable_agents_impl(
            tenant_id="tenant_a",
            user_id="user_a",
            ownership="all",
            page=1,
            page_size=10,
            search="beta",
        )

    assert [item["agent_id"] for item in result["items"]] == [2]
    assert result["pagination"]["total"] == 1


@pytest.mark.asyncio
async def test_list_my_editable_agents_impl_rejects_invalid_ownership():
    with patch.object(
        ars, "list_all_agent_info_impl", new_callable=AsyncMock
    ) as mock_list_all:
        with pytest.raises(ValueError, match="Invalid ownership filter"):
            await ars.list_my_editable_agents_impl(
                tenant_id="tenant_a",
                user_id="user_a",
                ownership="invalid",
            )

    mock_list_all.assert_not_called()


@pytest.fixture
def mock_status_update_deps():
    with patch.object(ars, "get_user_tenant_by_user_id") as mock_get_role, patch.object(
        ars, "get_agent_repository_by_id_and_publisher"
    ) as mock_get_by_id, patch.object(
        ars, "update_agent_repository_status_by_id"
    ) as mock_update_status, patch.object(
        ars, "reset_agent_repository_status"
    ) as mock_reset_status:
        yield {
            "get_user_role": mock_get_role,
            "get_by_id": mock_get_by_id,
            "update_status": mock_update_status,
            "reset_status": mock_reset_status,
        }


def test_reset_repository_peer_statuses_pending_review_also_clears_rejected():
    with patch.object(ars, "reset_agent_repository_status") as mock_reset:
        ars._reset_repository_peer_statuses(
            agent_repository_id=1,
            agent_id=10,
            status="pending_review",
            publisher_tenant_id="tenant_a",
        )

    mock_reset.assert_has_calls(_pending_review_reset_calls())


def test_reset_repository_peer_statuses_non_pending_single_reset():
    with patch.object(ars, "reset_agent_repository_status") as mock_reset:
        ars._reset_repository_peer_statuses(
            agent_repository_id=1,
            agent_id=10,
            status="shared",
            publisher_tenant_id="tenant_a",
        )

    mock_reset.assert_called_once_with(
        agent_repository_id=1,
        agent_id=10,
        status="shared",
        publisher_tenant_id="tenant_a",
    )


def test_update_status_su_pending_review_to_shared(mock_status_update_deps):
    deps = mock_status_update_deps
    deps["get_user_role"].return_value = {"user_role": "SU"}
    record = _repository_record(status="pending_review")
    deps["get_by_id"].side_effect = [record, {**record, "status": "shared"}]
    deps["update_status"].return_value = 1

    result = ars.update_agent_repository_status_impl(
        agent_repository_id=1,
        status="shared",
        user_id="su_user",
        tenant_id="tenant_a",
    )

    assert result["status"] == "shared"
    deps["update_status"].assert_called_once_with(
        repository_id=1,
        status="shared",
        user_id="su_user",
        filter_publisher_tenant_id="tenant_a",
        publisher_tenant_id=None,
        publisher_user_id=None,
        submitted_by=None,
    )
    deps["reset_status"].assert_called_once_with(
        agent_repository_id=1,
        agent_id=10,
        status="shared",
        publisher_tenant_id="tenant_a",
    )


def test_update_status_su_pending_review_to_rejected(mock_status_update_deps):
    deps = mock_status_update_deps
    deps["get_user_role"].return_value = {"user_role": "SU"}
    record = _repository_record(status="pending_review")
    deps["get_by_id"].side_effect = [record, {**record, "status": "rejected"}]
    deps["update_status"].return_value = 1

    result = ars.update_agent_repository_status_impl(
        agent_repository_id=1,
        status="rejected",
        user_id="su_user",
        tenant_id="tenant_a",
    )

    assert result["status"] == "rejected"


def test_update_status_su_shared_to_not_shared(mock_status_update_deps):
    deps = mock_status_update_deps
    deps["get_user_role"].return_value = {"user_role": "SU"}
    record = _repository_record(status="shared")
    deps["get_by_id"].side_effect = [record, {**record, "status": "not_shared"}]
    deps["update_status"].return_value = 1

    result = ars.update_agent_repository_status_impl(
        agent_repository_id=1,
        status="not_shared",
        user_id="su_user",
        tenant_id="tenant_a",
    )

    assert result["status"] == "not_shared"


def test_update_status_su_invalid_transition(mock_status_update_deps):
    deps = mock_status_update_deps
    deps["get_user_role"].return_value = {"user_role": "SU"}
    deps["get_by_id"].return_value = _repository_record(status="not_shared")

    with pytest.raises(ValueError, match="Invalid status transition"):
        ars.update_agent_repository_status_impl(
            agent_repository_id=1,
            status="shared",
            user_id="su_user",
            tenant_id="tenant_a",
        )


def test_update_status_admin_tenant_mismatch(mock_status_update_deps):
    deps = mock_status_update_deps
    deps["get_user_role"].return_value = {"user_role": "ADMIN"}
    deps["get_by_id"].return_value = _repository_record(
        status="not_shared",
        publisher_tenant_id="other_tenant",
    )

    with pytest.raises(UnauthorizedError, match="Not authorized"):
        ars.update_agent_repository_status_impl(
            agent_repository_id=1,
            status="pending_review",
            user_id="admin_user",
            tenant_id="tenant_a",
        )


def test_update_status_admin_not_shared_to_pending_review(mock_status_update_deps):
    deps = mock_status_update_deps
    deps["get_user_role"].return_value = {"user_role": "ADMIN"}
    record = _repository_record(status="not_shared")
    deps["get_by_id"].side_effect = [record, {**record, "status": "pending_review"}]
    deps["update_status"].return_value = 1

    with patch.object(ars, "_resolve_submitter_email", return_value="admin@example.com"):
        result = ars.update_agent_repository_status_impl(
            agent_repository_id=1,
            status="pending_review",
            user_id="admin_user",
            tenant_id="tenant_a",
        )

    assert result["status"] == "pending_review"
    deps["update_status"].assert_called_once_with(
        repository_id=1,
        status="pending_review",
        user_id="admin_user",
        filter_publisher_tenant_id="tenant_a",
        publisher_tenant_id="tenant_a",
        publisher_user_id="admin_user",
        submitted_by="admin@example.com",
    )
    deps["reset_status"].assert_has_calls(_pending_review_reset_calls())


def test_update_status_admin_rejected_to_pending_review(mock_status_update_deps):
    deps = mock_status_update_deps
    deps["get_user_role"].return_value = {"user_role": "ADMIN"}
    record = _repository_record(status="rejected")
    deps["get_by_id"].side_effect = [record, {**record, "status": "pending_review"}]
    deps["update_status"].return_value = 1

    with patch.object(ars, "_resolve_submitter_email", return_value="admin@example.com"):
        result = ars.update_agent_repository_status_impl(
            agent_repository_id=1,
            status="pending_review",
            user_id="admin_user",
            tenant_id="tenant_a",
        )

    assert result["status"] == "pending_review"
    deps["update_status"].assert_called_once_with(
        repository_id=1,
        status="pending_review",
        user_id="admin_user",
        filter_publisher_tenant_id="tenant_a",
        publisher_tenant_id="tenant_a",
        publisher_user_id="admin_user",
        submitted_by="admin@example.com",
    )
    deps["reset_status"].assert_has_calls(_pending_review_reset_calls())


def test_update_status_admin_pending_review_to_shared(mock_status_update_deps):
    deps = mock_status_update_deps
    deps["get_user_role"].return_value = {"user_role": "ADMIN"}
    record = _repository_record(
        status="pending_review",
        publisher_user_id="other_user",
    )
    deps["get_by_id"].side_effect = [record, {**record, "status": "shared"}]
    deps["update_status"].return_value = 1

    result = ars.update_agent_repository_status_impl(
        agent_repository_id=1,
        status="shared",
        user_id="admin_user",
        tenant_id="tenant_a",
    )

    assert result["status"] == "shared"
    deps["update_status"].assert_called_once_with(
        repository_id=1,
        status="shared",
        user_id="admin_user",
        filter_publisher_tenant_id="tenant_a",
        publisher_tenant_id=None,
        publisher_user_id=None,
        submitted_by=None,
    )


def test_update_status_admin_pending_review_to_rejected(mock_status_update_deps):
    deps = mock_status_update_deps
    deps["get_user_role"].return_value = {"user_role": "ADMIN"}
    record = _repository_record(
        status="pending_review",
        publisher_user_id="other_user",
    )
    deps["get_by_id"].side_effect = [record, {**record, "status": "rejected"}]
    deps["update_status"].return_value = 1

    result = ars.update_agent_repository_status_impl(
        agent_repository_id=1,
        status="rejected",
        user_id="admin_user",
        tenant_id="tenant_a",
    )

    assert result["status"] == "rejected"


def test_update_status_admin_review_tenant_mismatch(mock_status_update_deps):
    deps = mock_status_update_deps
    deps["get_user_role"].return_value = {"user_role": "ADMIN"}
    deps["get_by_id"].return_value = _repository_record(
        status="pending_review",
        publisher_tenant_id="other_tenant",
    )

    with pytest.raises(UnauthorizedError, match="Not authorized"):
        ars.update_agent_repository_status_impl(
            agent_repository_id=1,
            status="shared",
            user_id="admin_user",
            tenant_id="tenant_a",
        )


def test_update_status_admin_pending_review_to_not_shared(mock_status_update_deps):
    deps = mock_status_update_deps
    deps["get_user_role"].return_value = {"user_role": "ADMIN"}
    record = _repository_record(status="pending_review")
    deps["get_by_id"].side_effect = [record, {**record, "status": "not_shared"}]
    deps["update_status"].return_value = 1

    result = ars.update_agent_repository_status_impl(
        agent_repository_id=1,
        status="not_shared",
        user_id="admin_user",
        tenant_id="tenant_a",
    )

    assert result["status"] == "not_shared"
    deps["update_status"].assert_called_once_with(
        repository_id=1,
        status="not_shared",
        user_id="admin_user",
        filter_publisher_tenant_id="tenant_a",
        publisher_tenant_id=None,
        publisher_user_id=None,
        submitted_by=None,
    )


def test_update_status_dev_publisher_user_mismatch(mock_status_update_deps):
    deps = mock_status_update_deps
    deps["get_user_role"].return_value = {"user_role": "DEV"}
    deps["get_by_id"].return_value = _repository_record(
        status="not_shared",
        publisher_user_id="other_user",
    )

    with pytest.raises(UnauthorizedError, match="Not authorized"):
        ars.update_agent_repository_status_impl(
            agent_repository_id=1,
            status="pending_review",
            user_id="dev_user",
            tenant_id="tenant_a",
        )


def test_update_status_dev_valid_transition(mock_status_update_deps):
    deps = mock_status_update_deps
    deps["get_user_role"].return_value = {"user_role": "DEV"}
    record = _repository_record(
        status="rejected",
        publisher_user_id="dev_user",
    )
    deps["get_by_id"].side_effect = [record, {**record, "status": "not_shared"}]
    deps["update_status"].return_value = 1

    result = ars.update_agent_repository_status_impl(
        agent_repository_id=1,
        status="not_shared",
        user_id="dev_user",
        tenant_id="tenant_a",
    )

    assert result["status"] == "not_shared"


def test_update_status_user_role_rejected(mock_status_update_deps):
    deps = mock_status_update_deps
    deps["get_user_role"].return_value = {"user_role": "USER"}
    deps["get_by_id"].return_value = _repository_record(status="not_shared")

    with pytest.raises(UnauthorizedError, match="not authorized"):
        ars.update_agent_repository_status_impl(
            agent_repository_id=1,
            status="pending_review",
            user_id="regular_user",
            tenant_id="tenant_a",
        )


def test_update_status_same_status_noop(mock_status_update_deps):
    deps = mock_status_update_deps
    record = _repository_record(status="shared")
    deps["get_by_id"].side_effect = [record, record]
    deps["update_status"].return_value = 1

    result = ars.update_agent_repository_status_impl(
        agent_repository_id=1,
        status="shared",
        user_id="any_user",
        tenant_id="tenant_a",
    )

    assert result["status"] == "shared"
    deps["get_user_role"].assert_not_called()
    deps["update_status"].assert_called_once_with(
        repository_id=1,
        status="shared",
        user_id="any_user",
        filter_publisher_tenant_id="tenant_a",
        publisher_tenant_id=None,
        publisher_user_id=None,
        submitted_by=None,
    )
    deps["reset_status"].assert_called_once_with(
        agent_repository_id=1,
        agent_id=10,
        status="shared",
        publisher_tenant_id="tenant_a",
    )


def test_list_repository_listings_includes_submitted_by():
    records = [
        {
            **_repository_record(
                agent_repository_id=11,
                agent_id=30,
                status="pending_review",
            ),
            "submitted_by": "reviewer@example.com",
        }
    ]

    with patch.object(ars, "list_agent_repository_summaries", return_value=records):
        result = ars.list_agent_repository_listings_impl(
            "tenant_a",
            status="pending_review",
        )

    assert result["items"][0]["submitted_by"] == "reviewer@example.com"
    assert result["pagination"]["total"] == 1


def test_get_agent_repository_listing_detail_impl_scopes_by_tenant():
    record = {
        **_repository_record(agent_repository_id=42),
        "agent_info_json": {
            "agent_id": 10,
            "agent_info": {"10": {"model_name": "gpt", "duty_prompt": "help", "tools": []}},
            "mcp_info": [],
        },
        "icon": "🤖",
        "version_name": "v1",
        "downloads": 0,
        "create_time": None,
    }

    with patch.object(
        ars,
        "get_agent_repository_by_id_and_publisher",
        return_value=record,
    ) as mock_get:
        result = ars.get_agent_repository_listing_detail_impl(42, "tenant_a")

    mock_get.assert_called_once_with(42, "tenant_a")
    assert result["agent_repository_id"] == 42


def test_get_agent_repository_listing_detail_impl_not_found_for_other_tenant():
    with patch.object(
        ars,
        "get_agent_repository_by_id_and_publisher",
        return_value=None,
    ):
        with pytest.raises(ValueError, match="Repository listing not found"):
            ars.get_agent_repository_listing_detail_impl(42, "tenant_a")


def test_resolve_submitter_email_uses_user_tenant_email():
    with patch.object(
        ars,
        "get_user_tenant_by_user_id",
        return_value={"user_email": "  dev@example.com "},
    ):
        assert ars._resolve_submitter_email("user_a") == "dev@example.com"


def test_count_tools_in_snapshot_single_agent():
    snapshot = {
        "agent_id": 1,
        "agent_info": {
            "1": {
                "agent_id": 1,
                "tools": [{"name": "tool_a"}, {"name": "tool_b"}],
            }
        },
        "mcp_info": [],
    }
    assert ars._count_tools_in_snapshot(snapshot) == 2


def test_count_tools_in_snapshot_multi_agent_bundle():
    snapshot = {
        "agent_id": 1,
        "agent_info": {
            "1": {"agent_id": 1, "tools": [{"name": "tool_a"}]},
            "2": {"agent_id": 2, "tools": [{"name": "tool_b"}, {"name": "tool_c"}]},
        },
        "mcp_info": [],
    }
    assert ars._count_tools_in_snapshot(snapshot) == 3


@pytest.mark.parametrize(
    "snapshot",
    [
        None,
        "invalid",
        {},
        {"agent_info": None},
        {"agent_info": {"1": "not-a-dict"}},
        {"agent_info": {"1": {"tools": "not-a-list"}}},
    ],
)
def test_count_tools_in_snapshot_invalid_input(snapshot):
    assert ars._count_tools_in_snapshot(snapshot) == 0


@pytest.mark.asyncio
async def test_build_repository_data_from_agent_merges_card_fields():
    card_fields = {
        "icon": "📊",
        "category_id": 3,
        "tags": [" 数据 ", "数据", "自定义标签"],
        "downloads": 10,
    }
    with patch.object(
        ars, "search_agent_info_by_agent_id", return_value={"name": "agent_one", "author": "author@example.com"}
    ), patch.object(
        ars, "_validate_create_listing_permission"
    ), patch.object(
        ars, "_build_agent_info_json", new_callable=AsyncMock, return_value={
            "agent_id": 1,
            "agent_info": {"1": {"agent_id": 1}},
            "mcp_info": [],
        }
    ), patch.object(
        ars, "search_version_by_version_no", return_value={"version_name": "v1"}
    ), patch.object(
        ars, "_resolve_submitter_email", return_value="submitter@example.com"
    ):
        repository_data = await ars._build_repository_data_from_agent(
            agent_id=1,
            tenant_id="tenant_a",
            user_id="user_a",
            version_no=1,
            card_fields=card_fields,
        )

    assert repository_data["icon"] == "📊"
    assert repository_data["category_id"] == 3
    assert repository_data["tags"] == ["数据", "自定义标签"]
    assert repository_data["downloads"] == 10
    assert repository_data["tool_count"] == 0


@pytest.mark.asyncio
async def test_build_repository_data_from_agent_computes_tool_count():
    agent_info_json = {
        "agent_id": 1,
        "agent_info": {
            "1": {"agent_id": 1, "tools": [{"name": "tool_a"}, {"name": "tool_b"}]},
            "2": {"agent_id": 2, "tools": [{"name": "tool_c"}]},
        },
        "mcp_info": [],
    }
    with patch.object(
        ars, "search_agent_info_by_agent_id", return_value={"name": "agent_one", "author": "author@example.com"}
    ), patch.object(
        ars, "_validate_create_listing_permission"
    ), patch.object(
        ars, "_build_agent_info_json", new_callable=AsyncMock, return_value=agent_info_json
    ), patch.object(
        ars, "search_version_by_version_no", return_value={"version_name": "v1"}
    ), patch.object(
        ars, "_resolve_submitter_email", return_value="submitter@example.com"
    ):
        repository_data = await ars._build_repository_data_from_agent(
            agent_id=1,
            tenant_id="tenant_a",
            user_id="user_a",
            version_no=1,
        )

    assert repository_data["tool_count"] == 3


@pytest.mark.asyncio
async def test_build_repository_data_from_agent_card_fields_override_tool_count():
    agent_info_json = {
        "agent_id": 1,
        "agent_info": {"1": {"agent_id": 1, "tools": [{"name": "tool_a"}]}},
        "mcp_info": [],
    }
    with patch.object(
        ars, "search_agent_info_by_agent_id", return_value={"name": "agent_one", "author": "author@example.com"}
    ), patch.object(
        ars, "_validate_create_listing_permission"
    ), patch.object(
        ars, "_build_agent_info_json", new_callable=AsyncMock, return_value=agent_info_json
    ), patch.object(
        ars, "search_version_by_version_no", return_value={"version_name": "v1"}
    ), patch.object(
        ars, "_resolve_submitter_email", return_value="submitter@example.com"
    ):
        repository_data = await ars._build_repository_data_from_agent(
            agent_id=1,
            tenant_id="tenant_a",
            user_id="user_a",
            version_no=1,
            card_fields={"tool_count": 99},
        )

    assert repository_data["tool_count"] == 99


@pytest.mark.asyncio
async def test_build_repository_data_from_agent_sets_submitted_by():
    with patch.object(
        ars, "search_agent_info_by_agent_id", return_value={"name": "agent_one", "author": "author@example.com"}
    ), patch.object(
        ars, "_validate_create_listing_permission"
    ), patch.object(
        ars, "_build_agent_info_json", new_callable=AsyncMock, return_value={
            "agent_id": 1,
            "agent_info": {"1": {"agent_id": 1}},
            "mcp_info": [],
        }
    ), patch.object(
        ars, "search_version_by_version_no", return_value={"version_name": "v1"}
    ), patch.object(
        ars, "_resolve_submitter_email", return_value="submitter@example.com"
    ):
        repository_data = await ars._build_repository_data_from_agent(
            agent_id=1,
            tenant_id="tenant_a",
            user_id="user_a",
            version_no=1,
        )

    assert repository_data["submitted_by"] == "submitter@example.com"
    assert repository_data["status"] == "pending_review"


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
        ars, "get_agent_repository_by_id_and_publisher"
    ) as mock_get_by_id, patch.object(
        ars, "reset_agent_repository_status"
    ) as mock_reset_status:
        mock_build_data.return_value = {
            "agent_id": 1,
            "version_no": 1,
            "name": "agent_one",
            "agent_info_json": agent_info_json,
            "status": "pending_review",
            "icon": "🤖",
            "category_id": 1,
            "tags": ["营销"],
        }
        mock_get_by_agent_id.return_value = None
        mock_insert.return_value = 42
        mock_get_by_id.return_value = {
            "agent_repository_id": 42,
            "agent_id": 1,
            "name": "agent_one",
            "agent_info_json": agent_info_json,
            "version_no": 1,
            "status": "pending_review",
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
    mock_get_by_agent_id.assert_called_once_with(
        1,
        1,
        publisher_tenant_id="tenant_a",
    )
    mock_reset_status.assert_has_calls(
        _pending_review_reset_calls(agent_repository_id=42, agent_id=1)
    )


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
    ) as mock_update_by_id, patch.object(
        ars, "get_agent_repository_by_id_and_publisher"
    ) as mock_get_by_id, patch.object(
        ars, "reset_agent_repository_status"
    ) as mock_reset_status:
        mock_build_data.return_value = {
            "agent_id": 1,
            "version_no": 2,
            "name": "agent_one",
            "agent_info_json": agent_info_json,
            "status": "pending_review",
            "icon": "🤖",
            "category_id": 1,
            "tags": ["营销"],
            "tool_count": 3,
        }
        mock_get_by_agent_id.return_value = {"agent_repository_id": 42}
        mock_update_by_id.return_value = 1
        mock_get_by_id.return_value = {
            "agent_repository_id": 42,
            "agent_id": 1,
            "name": "agent_one",
            "agent_info_json": agent_info_json,
            "version_no": 2,
            "status": "pending_review",
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
    mock_get_by_agent_id.assert_called_once_with(
        1,
        2,
        publisher_tenant_id="tenant_a",
    )
    mock_update_by_id.assert_called_once_with(
        repository_id=42,
        publisher_tenant_id="tenant_a",
        user_id="user_a",
        updates={
            "status": "pending_review",
            "icon": "🤖",
            "tags": ["营销"],
            "category_id": 1,
            "tool_count": 3,
        },
    )
    mock_reset_status.assert_has_calls(
        _pending_review_reset_calls(agent_repository_id=42, agent_id=1)
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
        ars, "get_agent_repository_by_id_and_publisher"
    ) as mock_get_by_id, patch.object(
        ars, "reset_agent_repository_status"
    ) as mock_reset_status:
        mock_build_data.return_value = {
            "agent_id": 1,
            "version_no": 0,
            "name": "agent_one",
            "agent_info_json": agent_info_json,
            "status": "pending_review",
            "icon": "🤖",
            "category_id": 1,
            "tags": ["营销"],
        }
        mock_get_by_agent_id.return_value = None
        mock_insert.return_value = 42
        mock_get_by_id.return_value = {
            "agent_repository_id": 42,
            "agent_id": 1,
            "name": "agent_one",
            "agent_info_json": agent_info_json,
            "version_no": 0,
            "status": "pending_review",
            "tags": [],
        }

        result = await ars.create_agent_repository_listing_impl(
            agent_id=1,
            tenant_id="tenant_a",
            user_id="user_a",
            version_no=0,
        )

    assert result["agent_repository_id"] == 42
    assert result["version_no"] == 0
    mock_build_data.assert_awaited_once_with(1, "tenant_a", "user_a", 0, card_fields=None)
    mock_get_by_agent_id.assert_called_once_with(
        1,
        0,
        publisher_tenant_id="tenant_a",
    )
    mock_reset_status.assert_has_calls(
        _pending_review_reset_calls(agent_repository_id=42, agent_id=1)
    )


@pytest.mark.asyncio
async def test_create_agent_repository_listing_impl_rejects_negative_version():
    with pytest.raises(ValueError, match="version_no must be >= 0"):
        await ars.create_agent_repository_listing_impl(
            agent_id=1,
            tenant_id="tenant_a",
            user_id="user_a",
            version_no=-1,
        )


def test_validate_create_listing_permission_admin():
    with patch.object(
        ars,
        "get_user_tenant_by_user_id",
        return_value={"user_role": "ADMIN", "user_email": "admin@example.com"},
    ):
        ars._validate_create_listing_permission(
            user_id="admin_user",
            agent_info={"author": "other@example.com"},
        )


def test_validate_create_listing_permission_dev_matching_created_by():
    with patch.object(
        ars,
        "get_user_tenant_by_user_id",
        return_value={"user_role": "DEV"},
    ):
        ars._validate_create_listing_permission(
            user_id="dev_user",
            agent_info={"created_by": "dev_user", "author": "other@example.com"},
        )


def test_validate_create_listing_permission_dev_mismatch():
    with patch.object(
        ars,
        "get_user_tenant_by_user_id",
        return_value={"user_role": "DEV"},
    ):
        with pytest.raises(UnauthorizedError, match="Not authorized"):
            ars._validate_create_listing_permission(
                user_id="dev_user",
                agent_info={"created_by": "other_user", "author": "dev@example.com"},
            )


def test_validate_create_listing_permission_user_rejected():
    with patch.object(
        ars,
        "get_user_tenant_by_user_id",
        return_value={"user_role": "USER", "user_email": "user@example.com"},
    ):
        with pytest.raises(UnauthorizedError, match="not authorized"):
            ars._validate_create_listing_permission(
                user_id="regular_user",
                agent_info={"author": "user@example.com"},
            )


def test_validate_create_listing_permission_su_rejected():
    with patch.object(
        ars,
        "get_user_tenant_by_user_id",
        return_value={"user_role": "SU", "user_email": "su@example.com"},
    ):
        with pytest.raises(UnauthorizedError, match="not authorized"):
            ars._validate_create_listing_permission(
                user_id="su_user",
                agent_info={"author": "su@example.com"},
            )


@pytest.mark.asyncio
async def test_create_listing_impl_rejects_unauthorized_before_export():
    with patch.object(
        ars,
        "get_user_tenant_by_user_id",
        return_value={"user_role": "USER", "user_email": "user@example.com"},
    ), patch.object(
        ars,
        "search_agent_info_by_agent_id",
        return_value={
            "name": "agent_one",
            "author": "user@example.com",
        },
    ), patch.object(
        ars, "_build_agent_info_json", new_callable=AsyncMock
    ) as mock_build_json:
        with pytest.raises(UnauthorizedError, match="not authorized"):
            await ars.create_agent_repository_listing_impl(
                agent_id=1,
                tenant_id="tenant_a",
                user_id="regular_user",
                version_no=1,
            )
        mock_build_json.assert_not_awaited()


def test_validate_create_payload_requires_agent_info_json():
    base = {
        "agent_id": 1,
        "version_no": 1,
        "name": "agent_one",
        "icon": "🤖",
        "category_id": 1,
        "tags": ["营销"],
    }

    with pytest.raises(ValueError, match="agent_info_json"):
        ars._validate_create_payload(base)

    with pytest.raises(ValueError, match="agent_info_json must contain"):
        ars._validate_create_payload({
            **base,
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

    with patch.object(
        ars,
        "get_user_tenant_by_user_id",
        return_value={"user_role": "ADMIN", "user_email": "admin@example.com"},
    ):
        result = await ars._build_repository_data_from_agent(
            agent_id=1,
            tenant_id="tenant_a",
            user_id="user_a",
            version_no=1,
        )

    assert result["agent_info_json"]["agent_id"] == 1
    assert result["agent_info_json"]["skills"][0]["skill_name"] == "SkillA"
    assert result["version_name"] == "v1.0"


@pytest.mark.asyncio
async def test_build_repository_data_from_agent_allows_asset_owner_sub_agent():
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

    with patch.object(
        ars,
        "get_user_tenant_by_user_id",
        return_value={"user_role": "ADMIN", "user_email": "admin@example.com"},
    ):
        repository_data = await ars._build_repository_data_from_agent(
            agent_id=1,
            tenant_id="tenant_a",
            user_id="user_a",
            version_no=1,
        )

    assert repository_data["agent_id"] == 1
    assert repository_data["status"] == "pending_review"


def test_list_repository_listings_includes_tool_count():
    records = [
        {
            **_repository_record(agent_repository_id=1, agent_id=10, status="shared"),
            "tool_count": 2,
        }
    ]

    with patch.object(
        ars, "list_agent_repository_summaries", return_value=records
    ), patch.object(
        ars,
        "sum_agent_repository_downloads_by_agent_ids",
        return_value={10: 0},
    ):
        result = ars.list_agent_repository_listings_impl("tenant_a", status="shared")

    assert result["items"][0]["tool_count"] == 2


def test_list_repository_listings_defaults_null_tool_count_to_zero():
    records = [_repository_record(agent_repository_id=1, agent_id=10, status="shared")]

    with patch.object(
        ars, "list_agent_repository_summaries", return_value=records
    ), patch.object(
        ars,
        "sum_agent_repository_downloads_by_agent_ids",
        return_value={10: 0},
    ):
        result = ars.list_agent_repository_listings_impl("tenant_a", status="shared")

    assert result["items"][0]["tool_count"] == 0


def test_list_repository_listings_returns_agent_level_download_totals():
    records = [
        {
            **_repository_record(agent_repository_id=1, agent_id=10),
            "downloads": 2,
        }
    ]

    with patch.object(
        ars, "list_agent_repository_summaries", return_value=records
    ), patch.object(
        ars,
        "sum_agent_repository_downloads_by_agent_ids",
        return_value={10: 7},
    ) as mock_sum:
        result = ars.list_agent_repository_listings_impl("tenant_a", status="shared")

    mock_sum.assert_called_once_with([10])
    assert result["items"][0]["downloads"] == 7


def test_get_agent_repository_listing_detail_returns_agent_level_downloads():
    record = {
        **_repository_record(agent_repository_id=42, agent_id=10),
        "agent_info_json": {
            "agent_id": 10,
            "agent_info": {"10": {"model_name": "gpt", "duty_prompt": "help", "tools": []}},
            "mcp_info": [],
        },
        "icon": "🤖",
        "version_name": "v1",
        "downloads": 2,
        "create_time": None,
    }

    with patch.object(
        ars,
        "get_agent_repository_by_id_and_publisher",
        return_value=record,
    ), patch.object(
        ars,
        "sum_agent_repository_downloads_by_agent_ids",
        return_value={10: 9},
    ) as mock_sum:
        result = ars.get_agent_repository_listing_detail_impl(42, "tenant_a")

    mock_sum.assert_called_once_with([10])
    assert result["downloads"] == 9


@pytest.mark.asyncio
async def test_list_my_editable_agents_includes_agent_level_downloads():
    agents = [_list_all_agent_record(agent_id=1, permission="EDIT")]
    meta_by_id = {1: _mine_metadata_record(agent_id=1, created_by="user_a")}

    with patch.object(
        ars, "list_all_agent_info_impl", new_callable=AsyncMock, return_value=agents
    ), patch.object(
        ars, "fetch_draft_agent_mine_metadata", return_value=meta_by_id
    ), patch.object(
        ars, "list_agent_repository_by_agent_ids", return_value=[]
    ), patch.object(
        ars,
        "sum_agent_repository_downloads_by_agent_ids",
        return_value={1: 12},
    ) as mock_sum:
        result = await ars.list_my_editable_agents_impl(
            tenant_id="tenant_a",
            user_id="user_a",
            ownership="all",
        )

    mock_sum.assert_called_once_with([1])
    assert result["items"][0]["downloads"] == 12


@pytest.mark.asyncio
async def test_import_agent_from_repository_increments_downloads():
    record = {
        **_repository_record(agent_repository_id=42, agent_id=10, status="shared"),
        "agent_info_json": {
            "agent_id": 10,
            "agent_info": {"10": {"name": "agent_one"}},
            "mcp_info": [],
        },
    }

    with patch.object(
        ars,
        "get_agent_repository_by_id_and_publisher",
        return_value=record,
    ), patch.object(
        ars,
        "import_agent_impl",
        new_callable=AsyncMock,
        return_value={1: 100},
    ), patch.object(
        ars,
        "increment_agent_repository_downloads",
        return_value=1,
    ) as mock_increment:
        result = await ars.import_agent_from_repository_impl(
            agent_repository_id=42,
            tenant_id="tenant_a",
            authorization="Bearer token",
        )

    mock_increment.assert_called_once_with(42)
    assert result == {1: 100}


@pytest.mark.asyncio
async def test_import_agent_from_repository_skips_increment_on_import_failure():
    record = {
        **_repository_record(agent_repository_id=42, agent_id=10, status="shared"),
        "agent_info_json": {
            "agent_id": 10,
            "agent_info": {"10": {"name": "agent_one"}},
            "mcp_info": [],
        },
    }

    with patch.object(
        ars,
        "get_agent_repository_by_id_and_publisher",
        return_value=record,
    ), patch.object(
        ars,
        "import_agent_impl",
        new_callable=AsyncMock,
        side_effect=ValueError("import failed"),
    ), patch.object(
        ars,
        "increment_agent_repository_downloads",
    ) as mock_increment:
        with pytest.raises(ValueError, match="import failed"):
            await ars.import_agent_from_repository_impl(
                agent_repository_id=42,
                tenant_id="tenant_a",
                authorization="Bearer token",
            )

    mock_increment.assert_not_called()
