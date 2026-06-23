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
_agent_repo_db_mock.STATUS_PENDING_REVIEW = "pending_review"
_agent_repo_db_mock.STATUS_NOT_SHARED = "not_shared"
_agent_repo_db_mock.STATUS_REJECTED = "rejected"
_agent_repo_db_mock.STATUS_SHARED = "shared"
_agent_repo_db_mock.VALID_REPOSITORY_STATUSES = frozenset({
    "not_shared",
    "pending_review",
    "rejected",
    "shared",
})
_agent_repo_db_mock.OWNERSHIP_ALL = "all"
_agent_repo_db_mock.VALID_OWNERSHIP_FILTERS = frozenset({
    "all",
    "created",
    "others",
})
_agent_repo_db_mock.get_agent_repository_by_id = MagicMock()
_agent_repo_db_mock.get_agent_repository_by_agent_id = MagicMock()
_agent_repo_db_mock.insert_agent_repository_record = MagicMock()
_agent_repo_db_mock.update_agent_repository_by_id = MagicMock()
_agent_repo_db_mock.update_agent_repository_status_by_id = MagicMock()
_agent_repo_db_mock.reset_agent_repository_status = MagicMock()
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
) -> list:
    return [
        call(
            agent_repository_id=agent_repository_id,
            agent_id=agent_id,
            status="pending_review",
        ),
        call(
            agent_repository_id=agent_repository_id,
            agent_id=agent_id,
            status="rejected",
        ),
    ]


def test_list_repository_listings_deduplicates_by_agent_id_by_default():
    records = [
        _repository_record(
            agent_repository_id=100,
            agent_id=10,
            status="not_shared",
        ),
        _repository_record(
            agent_repository_id=90,
            agent_id=10,
            status="shared",
        ),
        _repository_record(
            agent_repository_id=80,
            agent_id=20,
            status="rejected",
        ),
    ]

    with patch.object(ars, "list_agent_repository_summaries", return_value=records):
        result = ars.list_agent_repository_listings_impl()

    assert [item["agent_repository_id"] for item in result["items"]] == [90, 80]
    assert result["items"][0]["status"] == "shared"


def test_list_repository_listings_can_skip_agent_id_deduplication():
    records = [
        _repository_record(agent_repository_id=100, agent_id=10, status="not_shared"),
        _repository_record(agent_repository_id=90, agent_id=10, status="shared"),
        _repository_record(agent_repository_id=80, agent_id=20, status="rejected"),
    ]

    with patch.object(ars, "list_agent_repository_summaries", return_value=records):
        result = ars.list_agent_repository_listings_impl(
            deduplicate_by_agent_id=False,
        )

    assert [item["agent_repository_id"] for item in result["items"]] == [100, 90, 80]


def test_list_repository_listings_uses_newest_repository_for_status_tie():
    records = [
        _repository_record(
            agent_repository_id=10,
            agent_id=30,
            status="pending_review",
        ),
        _repository_record(
            agent_repository_id=11,
            agent_id=30,
            status="pending_review",
        ),
    ]

    with patch.object(ars, "list_agent_repository_summaries", return_value=records):
        result = ars.list_agent_repository_listings_impl()

    assert [item["agent_repository_id"] for item in result["items"]] == [11]


def test_list_repository_listings_passes_agent_id_to_db():
    with patch.object(
        ars,
        "list_agent_repository_summaries",
        return_value=[_repository_record(agent_repository_id=1, agent_id=123)],
    ) as mock_list:
        result = ars.list_agent_repository_listings_impl(
            status="shared",
            agent_id=123,
            deduplicate_by_agent_id=False,
        )

    mock_list.assert_called_once_with(status="shared", agent_id=123, category_id=None)
    assert [item["agent_repository_id"] for item in result["items"]] == [1]


def test_list_repository_listings_rejects_invalid_status_with_agent_id():
    with patch.object(ars, "list_agent_repository_summaries") as mock_list:
        with pytest.raises(ValueError, match="Invalid status"):
            ars.list_agent_repository_listings_impl(
                status="invalid",
                agent_id=123,
            )

    mock_list.assert_not_called()


def test_list_agent_repository_categories_impl_returns_hardcoded_categories():
    result = ars.list_agent_repository_categories_impl()

    assert len(result) == 7
    assert result[0] == {"id": 1, "name": "写作助手"}
    assert result[-1] == {"id": 0, "name": "其它"}
    assert [item["id"] for item in result] == [1, 2, 3, 4, 5, 6, 0]


def _editable_agent_record(
    *,
    agent_id: int = 1,
    name: str = "agent_one",
    display_name: str = "Agent One",
) -> dict:
    return {
        "agent_id": agent_id,
        "name": name,
        "display_name": display_name,
        "description": "desc",
        "current_version_no": 0,
        "version_name": "v0",
        "version_create_time": None,
        "created_by": "user_a",
    }


def test_list_my_editable_agents_impl_returns_items_and_counts():
    agents = [
        _editable_agent_record(agent_id=1),
        _editable_agent_record(agent_id=2, name="agent_two", display_name="Agent Two"),
    ]
    counts = {"all": 2, "created": 1, "others": 1}

    with patch.object(ars, "get_user_tenant_by_user_id", return_value={"user_role": "USER"}), patch.object(
        ars, "count_editable_agents_by_ownership", return_value=counts
    ) as mock_counts, patch.object(
        ars, "list_editable_agents_for_user", return_value=agents
    ) as mock_list, patch.object(
        ars, "list_agent_repository_by_agent_ids", return_value=[]
    ) as mock_repo_list:
        result = ars.list_my_editable_agents_impl(
            tenant_id="tenant_a",
            user_id="user_a",
            ownership="created",
        )

    mock_counts.assert_called_once_with(
        "tenant_a",
        "user_a",
        user_role="USER",
    )
    mock_list.assert_called_once_with(
        "tenant_a",
        "user_a",
        user_role="USER",
        ownership_filter="created",
    )
    mock_repo_list.assert_called_once()
    assert "rejected" in mock_repo_list.call_args.kwargs["statuses"]
    assert result["counts"] == counts
    assert len(result["items"]) == 2
    assert result["items"][0]["agent_id"] == 1
    assert result["items"][0]["name"] == "Agent One"
    assert result["items"][0]["repository_info"] == []


def test_list_my_editable_agents_impl_includes_rejected_repository_info():
    agents = [_editable_agent_record(agent_id=1)]
    counts = {"all": 1, "created": 1, "others": 0}
    rejected_record = {
        "agent_repository_id": 99,
        "agent_id": 1,
        "status": "rejected",
        "version_no": 2,
        "version_name": "v2",
        "create_time": "2026-06-01T00:00:00",
    }

    with patch.object(ars, "get_user_tenant_by_user_id", return_value={"user_role": "USER"}), patch.object(
        ars, "count_editable_agents_by_ownership", return_value=counts
    ), patch.object(
        ars, "list_editable_agents_for_user", return_value=agents
    ), patch.object(
        ars, "list_agent_repository_by_agent_ids", return_value=[rejected_record]
    ):
        result = ars.list_my_editable_agents_impl(
            tenant_id="tenant_a",
            user_id="user_a",
            ownership="all",
        )

    repository_info = result["items"][0]["repository_info"]
    assert len(repository_info) == 1
    assert repository_info[0]["agent_repository_id"] == 99
    assert repository_info[0]["status"] == "rejected"
    assert repository_info[0]["version_no"] == 2


def test_list_my_editable_agents_impl_returns_empty_items_with_counts():
    counts = {"all": 0, "created": 0, "others": 0}

    with patch.object(ars, "get_user_tenant_by_user_id", return_value={"user_role": "USER"}), patch.object(
        ars, "count_editable_agents_by_ownership", return_value=counts
    ), patch.object(
        ars, "list_editable_agents_for_user", return_value=[]
    ), patch.object(
        ars, "list_agent_repository_by_agent_ids"
    ) as mock_repo_list:
        result = ars.list_my_editable_agents_impl(
            tenant_id="tenant_a",
            user_id="user_a",
            ownership="all",
        )

    mock_repo_list.assert_not_called()
    assert result == {"items": [], "counts": counts}


def test_list_my_editable_agents_impl_rejects_invalid_ownership():
    with patch.object(ars, "get_user_tenant_by_user_id") as mock_get_role, patch.object(
        ars, "count_editable_agents_by_ownership"
    ) as mock_counts, patch.object(
        ars, "list_editable_agents_for_user"
    ) as mock_list:
        with pytest.raises(ValueError, match="Invalid ownership filter"):
            ars.list_my_editable_agents_impl(
                tenant_id="tenant_a",
                user_id="user_a",
                ownership="invalid",
            )

    mock_get_role.assert_not_called()
    mock_counts.assert_not_called()
    mock_list.assert_not_called()


@pytest.fixture
def mock_status_update_deps():
    with patch.object(ars, "get_user_tenant_by_user_id") as mock_get_role, patch.object(
        ars, "get_agent_repository_by_id"
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
        )

    mock_reset.assert_has_calls(_pending_review_reset_calls())


def test_reset_repository_peer_statuses_non_pending_single_reset():
    with patch.object(ars, "reset_agent_repository_status") as mock_reset:
        ars._reset_repository_peer_statuses(
            agent_repository_id=1,
            agent_id=10,
            status="shared",
        )

    mock_reset.assert_called_once_with(
        agent_repository_id=1,
        agent_id=10,
        status="shared",
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
        tenant_id="any_tenant",
    )

    assert result["status"] == "shared"
    deps["update_status"].assert_called_once_with(
        repository_id=1,
        status="shared",
        user_id="su_user",
        publisher_tenant_id=None,
        publisher_user_id=None,
        submitted_by=None,
    )
    deps["reset_status"].assert_called_once_with(
        agent_repository_id=1,
        agent_id=10,
        status="shared",
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
        tenant_id="any_tenant",
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
        tenant_id="any_tenant",
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
            tenant_id="any_tenant",
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
        publisher_tenant_id=None,
        publisher_user_id=None,
        submitted_by=None,
    )
    deps["reset_status"].assert_called_once_with(
        agent_repository_id=1,
        agent_id=10,
        status="shared",
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
        result = ars.list_agent_repository_listings_impl(status="pending_review")

    assert result["items"][0]["submitted_by"] == "reviewer@example.com"


def test_resolve_submitter_email_uses_user_tenant_email():
    with patch.object(
        ars,
        "get_user_tenant_by_user_id",
        return_value={"user_email": "  dev@example.com "},
    ):
        assert ars._resolve_submitter_email("user_a") == "dev@example.com"


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
        ars, "get_agent_repository_by_id"
    ) as mock_get_by_id, patch.object(
        ars, "reset_agent_repository_status"
    ) as mock_reset_status:
        mock_build_data.return_value = {
            "agent_id": 1,
            "version_no": 1,
            "name": "agent_one",
            "agent_info_json": agent_info_json,
            "status": "pending_review",
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
    mock_get_by_agent_id.assert_called_once_with(1, 1)
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
    ) as mock_update, patch.object(
        ars, "get_agent_repository_by_id"
    ) as mock_get_by_id, patch.object(
        ars, "reset_agent_repository_status"
    ) as mock_reset_status:
        mock_build_data.return_value = {
            "agent_id": 1,
            "version_no": 2,
            "name": "agent_one",
            "agent_info_json": agent_info_json,
            "status": "pending_review",
        }
        mock_get_by_agent_id.return_value = {"agent_repository_id": 42}
        mock_update.return_value = 1
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
    mock_get_by_agent_id.assert_called_once_with(1, 2)
    mock_update.assert_called_once()
    mock_update.assert_called_with(
        repository_id=42,
        publisher_tenant_id="tenant_a",
        user_id="user_a",
        updates={
            "version_no": 2,
            "agent_info_json": agent_info_json,
            "status": "pending_review",
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
        ars, "get_agent_repository_by_id"
    ) as mock_get_by_id, patch.object(
        ars, "reset_agent_repository_status"
    ) as mock_reset_status:
        mock_build_data.return_value = {
            "agent_id": 1,
            "version_no": 0,
            "name": "agent_one",
            "agent_info_json": agent_info_json,
            "status": "pending_review",
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
    mock_get_by_agent_id.assert_called_once_with(1, 0)
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


def test_validate_create_listing_permission_dev_matching_email():
    with patch.object(
        ars,
        "get_user_tenant_by_user_id",
        return_value={"user_role": "DEV", "user_email": "Dev@Example.com"},
    ):
        ars._validate_create_listing_permission(
            user_id="dev_user",
            agent_info={"author": "dev@example.com"},
        )


def test_validate_create_listing_permission_dev_mismatch():
    with patch.object(
        ars,
        "get_user_tenant_by_user_id",
        return_value={"user_role": "DEV", "user_email": "dev@example.com"},
    ):
        with pytest.raises(UnauthorizedError, match="Not authorized"):
            ars._validate_create_listing_permission(
                user_id="dev_user",
                agent_info={"author": "other@example.com"},
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
    with pytest.raises(ValueError, match="agent_info_json"):
        ars._validate_create_payload({
            "agent_id": 1,
            "version_no": 1,
            "name": "agent_one",
        })

    with pytest.raises(ValueError, match="agent_info_json must contain"):
        ars._validate_create_payload({
            "agent_id": 1,
            "version_no": 1,
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
