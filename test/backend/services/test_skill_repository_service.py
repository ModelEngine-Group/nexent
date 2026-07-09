"""Focused unit tests for skill repository service."""

import base64
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_BACKEND_ROOT = _REPO_ROOT / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

for module_name in [
    name for name in sys.modules
    if name == "consts" or name.startswith("consts.")
]:
    sys.modules.pop(module_name, None)

_skill_repo_db_mock = MagicMock()
_skill_repo_db_mock.get_skill_repository_by_id_and_publisher = MagicMock()
_skill_repo_db_mock.get_skill_repository_by_skill_id = MagicMock()
_skill_repo_db_mock.increment_skill_repository_downloads = MagicMock(return_value=1)
_skill_repo_db_mock.insert_skill_repository_record = MagicMock(return_value=1)
_skill_repo_db_mock.list_skill_repository_by_skill_ids = MagicMock(return_value=[])
_skill_repo_db_mock.list_skill_repository_summaries = MagicMock()
_skill_repo_db_mock.update_skill_repository_by_id = MagicMock(return_value=1)
_skill_repo_db_mock.update_skill_repository_status_by_id = MagicMock(return_value=1)
sys.modules["database.skill_repository_db"] = _skill_repo_db_mock

_skill_db_mock = MagicMock()
_skill_db_mock.get_skill_by_name = MagicMock(return_value=None)
sys.modules["database.skill_db"] = _skill_db_mock

_user_tenant_db_mock = MagicMock()
_user_tenant_db_mock.get_user_tenant_by_user_id = MagicMock()
sys.modules["database.user_tenant_db"] = _user_tenant_db_mock


class _SkillServiceMock:
    def __init__(self, tenant_id=None):
        self.tenant_id = tenant_id

    def get_skill_by_id(self, skill_id, tenant_id=None):
        return {
            "skill_id": skill_id,
            "name": "Skill A",
            "description": "desc",
            "tags": ["tag"],
            "content": "content",
            "source": "custom",
            "created_by": "user-1",
            "tool_ids": [],
        }

    def export_skills_by_names(self, skill_names, tenant_id=None):
        return [{"skill_name": skill_names[0], "skill_zip_base64": "emlw"}]

    def create_skill_from_zip_bytes(self, **kwargs):
        return {
            "skill_id": 99,
            "name": kwargs["skill_name"],
            "description": "copied",
            "source": kwargs["source"],
            "tags": [],
        }

    def list_skills(self, tenant_id=None):
        return []


_skill_service_module_mock = MagicMock()
_skill_service_module_mock.SkillService = _SkillServiceMock
sys.modules["services.skill_service"] = _skill_service_module_mock

import consts.exceptions as exceptions_module


def _ensure_exception(name):
    exception = getattr(exceptions_module, name, None)
    if exception is None:
        exception = type(name, (Exception,), {})
        setattr(exceptions_module, name, exception)
    return exception


ForbiddenError = _ensure_exception("ForbiddenError")
SkillDuplicateError = _ensure_exception("SkillDuplicateError")
SkillException = _ensure_exception("SkillException")

from backend.services import skill_repository_service as srs


def setup_function():
    _skill_repo_db_mock.reset_mock()
    _skill_repo_db_mock.get_skill_repository_by_id_and_publisher.side_effect = None
    _skill_repo_db_mock.get_skill_repository_by_id_and_publisher.return_value = None
    _skill_repo_db_mock.get_skill_repository_by_skill_id.side_effect = None
    _skill_repo_db_mock.get_skill_repository_by_skill_id.return_value = None
    _skill_repo_db_mock.increment_skill_repository_downloads.return_value = 1
    _skill_repo_db_mock.insert_skill_repository_record.return_value = 1
    _skill_repo_db_mock.list_skill_repository_by_skill_ids.return_value = []
    _skill_repo_db_mock.update_skill_repository_by_id.return_value = 1
    _skill_repo_db_mock.update_skill_repository_status_by_id.return_value = 1
    _skill_db_mock.reset_mock()
    _skill_db_mock.get_skill_by_name.return_value = None
    _user_tenant_db_mock.reset_mock()
    _user_tenant_db_mock.get_user_tenant_by_user_id.return_value = {
        "user_role": "DEV",
        "user_email": "dev@example.com",
    }


def _repository_record(status="not_shared", publisher_user_id="user-1"):
    return {
        "skill_repository_id": 1,
        "skill_id": 10,
        "name": "Skill A",
        "description": "desc",
        "source": "custom",
        "status": status,
        "publisher_tenant_id": "tenant-1",
        "publisher_user_id": publisher_user_id,
        "submitted_by": "dev@example.com",
        "tags": ["tag"],
        "downloads": 0,
        "skill_info_json": {"content": "content", "tags": ["tag"]},
        "create_time": None,
        "update_time": None,
    }


def test_create_skill_repository_listing_inserts_new_record():
    _skill_repo_db_mock.get_skill_repository_by_skill_id.return_value = None
    _skill_repo_db_mock.get_skill_repository_by_id_and_publisher.return_value = (
        _repository_record(status="pending_review")
    )

    result = srs.create_skill_repository_listing_impl(
        skill_id=10,
        tenant_id="tenant-1",
        user_id="user-1",
        card_fields={"icon": "skill", "tags": ["tag"]},
    )

    assert result["skill_repository_id"] == 1
    assert result["is_updated"] is False
    _skill_repo_db_mock.insert_skill_repository_record.assert_called_once()


def test_create_skill_repository_listing_updates_existing_record():
    _skill_repo_db_mock.get_skill_repository_by_skill_id.return_value = (
        _repository_record(status="rejected")
    )
    _skill_repo_db_mock.get_skill_repository_by_id_and_publisher.return_value = (
        _repository_record(status="pending_review")
    )

    result = srs.create_skill_repository_listing_impl(
        skill_id=10,
        tenant_id="tenant-1",
        user_id="user-1",
    )

    assert result["is_updated"] is True
    _skill_repo_db_mock.update_skill_repository_by_id.assert_called_once()


def test_create_skill_repository_listing_rejects_non_owner_dev():
    class SkillServiceNonOwner(_SkillServiceMock):
        def get_skill_by_id(self, skill_id, tenant_id=None):
            data = super().get_skill_by_id(skill_id, tenant_id)
            data["created_by"] = "someone-else"
            return data

    with patch.object(srs, "SkillService", SkillServiceNonOwner):
        with pytest.raises(ForbiddenError):
            srs.create_skill_repository_listing_impl(
                skill_id=10,
                tenant_id="tenant-1",
                user_id="user-1",
            )

    _skill_repo_db_mock.insert_skill_repository_record.assert_not_called()


def test_update_status_admin_approves_pending_review():
    _user_tenant_db_mock.get_user_tenant_by_user_id.return_value = {
        "user_role": "ADMIN",
        "user_email": "admin@example.com",
    }
    _skill_repo_db_mock.get_skill_repository_by_id_and_publisher.side_effect = [
        _repository_record(status="pending_review"),
        _repository_record(status="shared"),
    ]

    result = srs.update_skill_repository_status_impl(
        skill_repository_id=1,
        status="shared",
        user_id="admin-1",
        tenant_id="tenant-1",
    )

    assert result["status"] == "shared"
    _skill_repo_db_mock.update_skill_repository_status_by_id.assert_called_once()


def test_update_status_dev_cannot_approve_review():
    _skill_repo_db_mock.get_skill_repository_by_id_and_publisher.return_value = (
        _repository_record(status="pending_review")
    )

    with pytest.raises(ValueError):
        srs.update_skill_repository_status_impl(
            skill_repository_id=1,
            status="shared",
            user_id="user-1",
            tenant_id="tenant-1",
        )


def test_update_status_dev_cannot_update_other_users_listing():
    _skill_repo_db_mock.get_skill_repository_by_id_and_publisher.return_value = (
        _repository_record(status="shared", publisher_user_id="someone-else")
    )

    with pytest.raises(ForbiddenError):
        srs.update_skill_repository_status_impl(
            skill_repository_id=1,
            status="not_shared",
            user_id="user-1",
            tenant_id="tenant-1",
        )


def test_install_skill_from_repository_success_increments_downloads():
    encoded_zip = base64.b64encode(b"zip").decode("ascii")
    _skill_repo_db_mock.get_skill_repository_by_id_and_publisher.return_value = {
        **_repository_record(status="shared"),
        "skill_zip_base64": encoded_zip,
    }

    result = srs.install_skill_from_repository_impl(
        skill_repository_id=1,
        tenant_id="tenant-1",
        user_id="user-1",
        target_name="Skill A Copy",
    )

    assert result["name"] == "Skill A Copy"
    assert result["source"] == "repository"
    _skill_repo_db_mock.increment_skill_repository_downloads.assert_called_once_with(
        repository_id=1,
        user_id="user-1",
    )


def test_install_skill_from_repository_duplicate_is_mapped():
    class DuplicateSkillService(_SkillServiceMock):
        def create_skill_from_zip_bytes(self, **kwargs):
            raise SkillException("Skill 'Skill A' already exists")

    encoded_zip = base64.b64encode(b"zip").decode("ascii")
    _skill_repo_db_mock.get_skill_repository_by_id_and_publisher.return_value = {
        **_repository_record(status="shared"),
        "skill_zip_base64": encoded_zip,
    }

    with patch.object(srs, "SkillService", DuplicateSkillService):
        with pytest.raises(SkillDuplicateError) as exc_info:
            srs.install_skill_from_repository_impl(
                skill_repository_id=1,
                tenant_id="tenant-1",
                user_id="user-1",
                target_name="Skill A",
            )

    assert exc_info.value.duplicate_names == ["Skill A"]


def test_list_my_editable_skills_filters_to_current_user_and_search():
    class ListSkillService(_SkillServiceMock):
        def list_skills(self, tenant_id=None):
            return [
                {
                    "skill_id": 1,
                    "name": "Excel Report",
                    "description": "build reports",
                    "source": "custom",
                    "tags": ["excel"],
                    "created_by": "user-1",
                },
                {
                    "skill_id": 2,
                    "name": "Other Skill",
                    "description": "other",
                    "source": "custom",
                    "tags": [],
                    "created_by": "user-2",
                },
            ]

    with patch.object(srs, "SkillService", ListSkillService):
        result = srs.list_my_editable_skills_impl(
            tenant_id="tenant-1",
            user_id="user-1",
            search="excel",
        )

    assert result["counts"] == {"all": 1, "created": 1, "others": 0}
    assert [item["name"] for item in result["items"]] == ["Excel Report"]


def test_list_repository_listings_validates_status():
    with pytest.raises(ValueError):
        srs.list_skill_repository_listings_impl(
            "tenant-1",
            status="bad_status",
        )


def test_listing_tag_and_card_validation():
    assert srs._normalize_listing_tags([" tag ", "tag", "", "second"]) == [
        "tag",
        "second",
    ]
    with pytest.raises(ValueError, match="list of strings"):
        srs._normalize_listing_tags("tag")
    with pytest.raises(ValueError, match="list of strings"):
        srs._normalize_listing_tags([1])
    with pytest.raises(ValueError, match="at most 20"):
        srs._normalize_listing_tags(["x" * 21])
    with pytest.raises(ValueError, match="at most 5"):
        srs._normalize_listing_tags([str(index) for index in range(6)])
    with pytest.raises(ValueError, match="icon must be at most"):
        srs._validate_card_fields({"icon": "x" * 33})
    with pytest.raises(ValueError, match="category_id"):
        srs._validate_card_fields({"icon": "skill", "category_id": "bad"})


def test_create_payload_validation_rejects_invalid_snapshot_fields():
    with pytest.raises(ValueError, match="Missing required"):
        srs._validate_create_payload({})
    with pytest.raises(ValueError, match="non-empty"):
        srs._validate_create_payload({
            "skill_id": 1,
            "name": "",
            "skill_info_json": {},
            "skill_zip_base64": "zip",
        })
    with pytest.raises(ValueError, match="JSON object"):
        srs._validate_create_payload({
            "skill_id": 1,
            "name": "Skill",
            "skill_info_json": [],
            "skill_zip_base64": "zip",
        })
    with pytest.raises(ValueError, match="must be a string"):
        srs._validate_create_payload({
            "skill_id": 1,
            "name": "Skill",
            "skill_info_json": {},
            "skill_zip_base64": 1,
        })


def test_update_status_validates_input_and_missing_records():
    with pytest.raises(ValueError, match="Invalid status"):
        srs.update_skill_repository_status_impl(
            skill_repository_id=1,
            status="invalid",
            user_id="user-1",
            tenant_id="tenant-1",
        )
    with pytest.raises(ValueError, match="not found"):
        srs.update_skill_repository_status_impl(
            skill_repository_id=1,
            status="shared",
            user_id="user-1",
            tenant_id="tenant-1",
        )


def test_update_status_rejects_unknown_role_and_invalid_su_transition():
    _user_tenant_db_mock.get_user_tenant_by_user_id.return_value = {
        "user_role": "USER",
    }
    _skill_repo_db_mock.get_skill_repository_by_id_and_publisher.return_value = (
        _repository_record(status="not_shared")
    )
    with pytest.raises(ForbiddenError):
        srs.update_skill_repository_status_impl(
            skill_repository_id=1,
            status="pending_review",
            user_id="user-1",
            tenant_id="tenant-1",
        )

    _user_tenant_db_mock.get_user_tenant_by_user_id.return_value = {
        "user_role": "SU",
    }
    with pytest.raises(ValueError, match="Invalid status transition"):
        srs.update_skill_repository_status_impl(
            skill_repository_id=1,
            status="pending_review",
            user_id="su-1",
            tenant_id="tenant-1",
        )


@pytest.mark.parametrize(
    ("record", "message"),
    [
        (None, "not found"),
        (_repository_record(status="pending_review"), "not available"),
        ({**_repository_record(status="shared"), "skill_zip_base64": ""}, "no skill ZIP"),
        ({**_repository_record(status="shared"), "skill_zip_base64": "%%%"}, "invalid skill ZIP"),
    ],
)
def test_install_rejects_unavailable_payloads(record, message):
    _skill_repo_db_mock.get_skill_repository_by_id_and_publisher.return_value = record

    with pytest.raises(ValueError, match=message):
        srs.install_skill_from_repository_impl(
            skill_repository_id=1,
            tenant_id="tenant-1",
            user_id="user-1",
        )


def test_install_generates_copy_name_and_tolerates_download_count_failure():
    encoded_zip = base64.b64encode(b"zip").decode("ascii")
    _skill_repo_db_mock.get_skill_repository_by_id_and_publisher.return_value = {
        **_repository_record(status="shared"),
        "skill_zip_base64": encoded_zip,
    }
    _skill_db_mock.get_skill_by_name.side_effect = [
        {"skill_id": 1},
        None,
    ]
    _skill_repo_db_mock.increment_skill_repository_downloads.return_value = 0

    result = srs.install_skill_from_repository_impl(
        skill_repository_id=1,
        tenant_id="tenant-1",
        user_id="user-1",
    )

    assert result["name"] != "Skill A"
    assert _skill_db_mock.get_skill_by_name.call_count == 2


def test_mine_list_validates_ownership_and_supports_padding():
    with pytest.raises(ValueError, match="Invalid ownership"):
        srs.list_my_editable_skills_impl(
            tenant_id="tenant-1",
            user_id="user-1",
            ownership="invalid",
        )

    result = srs.list_my_editable_skills_impl(
        tenant_id="tenant-1",
        user_id="user-1",
        new_skill_padding=True,
    )
    assert result["items"] == [{"new_skill_padding": True}]
    assert result["pagination"]["total"] == 1


def test_repository_list_and_detail_success():
    _skill_repo_db_mock.list_skill_repository_summaries.return_value = {
        "items": [_repository_record(status="shared")],
        "pagination": {"total": 1},
    }
    result = srs.list_skill_repository_listings_impl(
        "tenant-1",
        status="shared",
    )
    assert result["items"][0]["status"] == "shared"

    _skill_repo_db_mock.get_skill_repository_by_id_and_publisher.return_value = (
        _repository_record(status="shared")
    )
    detail = srs.get_skill_repository_listing_detail_impl(1, "tenant-1")
    assert detail["skill_repository_id"] == 1
