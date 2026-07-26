"""Focused unit tests for skill repository service."""

import base64
import sys
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_BACKEND_ROOT = _REPO_ROOT / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

_MOCKED_MODULE_NAMES = [
    "database.skill_repository_db",
    "database.group_db",
    "database.skill_db",
    "database.user_tenant_db",
    "services.skill_service",
    "utils.str_utils",
]
_ORIGINAL_MODULES = {
    name: sys.modules.get(name)
    for name in _MOCKED_MODULE_NAMES
}

_consts_package = sys.modules.get("consts")
if _consts_package is not None and not hasattr(_consts_package, "__path__"):
    _consts_package.__path__ = []

if "consts.agent_repository" not in sys.modules:
    consts_agent_repository_mock = types.ModuleType("consts.agent_repository")
    consts_agent_repository_mock.OWNERSHIP_ALL = "all"
    consts_agent_repository_mock.OWNERSHIP_CREATED = "created"
    consts_agent_repository_mock.OWNERSHIP_OTHERS = "others"
    consts_agent_repository_mock.STATUS_NOT_SHARED = "not_shared"
    consts_agent_repository_mock.STATUS_PENDING_REVIEW = "pending_review"
    consts_agent_repository_mock.STATUS_REJECTED = "rejected"
    consts_agent_repository_mock.STATUS_SHARED = "shared"
    consts_agent_repository_mock.VALID_OWNERSHIP_FILTERS = {
        "all",
        "created",
        "others",
    }
    consts_agent_repository_mock.VALID_REPOSITORY_STATUSES = {
        "not_shared",
        "pending_review",
        "rejected",
        "shared",
    }
    sys.modules["consts.agent_repository"] = consts_agent_repository_mock

consts_const_module = sys.modules.get("consts.const")
if consts_const_module is not None:
    if not hasattr(consts_const_module, "CAN_EDIT_ALL_USER_ROLES"):
        consts_const_module.CAN_EDIT_ALL_USER_ROLES = {"ADMIN"}
    if not hasattr(consts_const_module, "PERMISSION_EDIT"):
        consts_const_module.PERMISSION_EDIT = "EDIT"
    if not hasattr(consts_const_module, "PERMISSION_READ"):
        consts_const_module.PERMISSION_READ = "READ_ONLY"
    if not hasattr(consts_const_module, "PERMISSION_PRIVATE"):
        consts_const_module.PERMISSION_PRIVATE = "PRIVATE"

_skill_repo_db_mock = MagicMock()
_skill_repo_db_mock.get_skill_repository_by_id_and_publisher = MagicMock()
_skill_repo_db_mock.get_skill_repository_by_skill_id = MagicMock()
_skill_repo_db_mock.increment_skill_repository_downloads = MagicMock(return_value=1)
_skill_repo_db_mock.insert_skill_repository_record = MagicMock(return_value=1)
_skill_repo_db_mock.list_skill_repository_by_skill_ids = MagicMock(return_value=[])
_skill_repo_db_mock.list_skill_repository_summaries = MagicMock()
_skill_repo_db_mock.reset_skill_repository_status = MagicMock(return_value=0)
_skill_repo_db_mock.update_skill_repository_by_id = MagicMock(return_value=1)
_skill_repo_db_mock.update_skill_repository_status_by_id = MagicMock(return_value=1)
sys.modules["database.skill_repository_db"] = _skill_repo_db_mock

_group_db_mock = MagicMock()
_group_db_mock.query_group_ids_by_user = MagicMock(return_value=[])
sys.modules["database.group_db"] = _group_db_mock

_utils_str_utils_mock = types.ModuleType("utils.str_utils")
_utils_str_utils_mock.convert_string_to_list = MagicMock(
    side_effect=lambda value: [
        int(item)
        for item in str(value or "").split(",")
        if item.strip().isdigit()
    ]
)
sys.modules["utils.str_utils"] = _utils_str_utils_mock

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

    def list_visible_skills(self, *, tenant_id=None, user_id):
        user_tenant = _user_tenant_db_mock.get_user_tenant_by_user_id(user_id) or {}
        user_role = str(user_tenant.get("user_role") or "USER")
        user_group_ids = set(_group_db_mock.query_group_ids_by_user(user_id) or [])
        skills = [
            skill
            for skill in self.list_skills(tenant_id=tenant_id)
            if user_role in {"ADMIN", "SUPER_ADMIN"}
            or str(skill.get("created_by")) == str(user_id)
            or (
                skill.get("ingroup_permission") != "PRIVATE"
                and bool(user_group_ids.intersection(skill.get("group_ids") or []))
            )
        ]
        for skill in skills:
            skill["permission"] = (
                "EDIT"
                if user_role in {"ADMIN", "SUPER_ADMIN"}
                or str(skill.get("created_by")) == str(user_id)
                else skill.get("ingroup_permission") or "READ_ONLY"
            )
        return skills


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
SkillException = _ensure_exception("SkillException")
SkillDuplicateError = getattr(exceptions_module, "SkillDuplicateError", None)
try:
    _has_duplicate_names = hasattr(SkillDuplicateError(["Skill A"]), "duplicate_names")
except Exception:
    _has_duplicate_names = False
if not _has_duplicate_names:
    class SkillDuplicateError(Exception):
        def __init__(self, duplicate_names):
            self.duplicate_names = duplicate_names
            super().__init__(str(duplicate_names))

    exceptions_module.SkillDuplicateError = SkillDuplicateError

from backend.services import skill_repository_service as srs


def teardown_module():
    for name, original in _ORIGINAL_MODULES.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


def setup_function():
    _skill_repo_db_mock.reset_mock()
    _skill_repo_db_mock.get_skill_repository_by_id_and_publisher.side_effect = None
    _skill_repo_db_mock.get_skill_repository_by_id_and_publisher.return_value = None
    _skill_repo_db_mock.get_skill_repository_by_skill_id.side_effect = None
    _skill_repo_db_mock.get_skill_repository_by_skill_id.return_value = None
    _skill_repo_db_mock.increment_skill_repository_downloads.return_value = 1
    _skill_repo_db_mock.insert_skill_repository_record.return_value = 1
    _skill_repo_db_mock.list_skill_repository_by_skill_ids.return_value = []
    _skill_repo_db_mock.reset_skill_repository_status.return_value = 0
    _skill_repo_db_mock.update_skill_repository_by_id.return_value = 1
    _skill_repo_db_mock.update_skill_repository_status_by_id.return_value = 1
    _group_db_mock.reset_mock()
    _group_db_mock.query_group_ids_by_user.return_value = []
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
        "skill_info_json": {
            "content": "content",
            "tags": ["tag"],
            "created_by": "user-1",
        },
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


def test_create_skill_repository_listing_does_not_overwrite_shared_record():
    _skill_repo_db_mock.get_skill_repository_by_skill_id.side_effect = [None, None]
    _skill_repo_db_mock.get_skill_repository_by_id_and_publisher.return_value = (
        _repository_record(status="pending_review")
    )

    result = srs.create_skill_repository_listing_impl(
        skill_id=10,
        tenant_id="tenant-1",
        user_id="user-1",
    )

    assert result["is_updated"] is False
    _skill_repo_db_mock.insert_skill_repository_record.assert_called_once()
    _skill_repo_db_mock.update_skill_repository_by_id.assert_not_called()
    requested_statuses = [
        call.kwargs["statuses"]
        for call in _skill_repo_db_mock.get_skill_repository_by_skill_id.call_args_list
    ]
    assert requested_statuses == [["pending_review"], ["rejected"]]


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
    _skill_repo_db_mock.reset_skill_repository_status.assert_called_once_with(
        repository_id=1,
        skill_id=10,
        status="shared",
        publisher_tenant_id="tenant-1",
    )


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
    create_kwargs = {}

    class CapturingSkillService(_SkillServiceMock):
        def create_skill_from_zip_bytes(self, **kwargs):
            create_kwargs.update(kwargs)
            return super().create_skill_from_zip_bytes(**kwargs)

    encoded_zip = base64.b64encode(b"zip").decode("ascii")
    _skill_repo_db_mock.get_skill_repository_by_id_and_publisher.return_value = {
        **_repository_record(status="shared"),
        "skill_zip_base64": encoded_zip,
    }

    with patch.object(srs, "SkillService", CapturingSkillService):
        result = srs.install_skill_from_repository_impl(
            skill_repository_id=1,
            tenant_id="tenant-1",
            user_id="user-1",
            target_name="Skill A Copy",
        )

    assert result["name"] == "Skill A Copy"
    assert result["source"] == "repository"
    assert create_kwargs["ingroup_permission"] == "READ_ONLY"
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


def test_mine_ownership_uses_creator_not_edit_permission():
    class ListSkillService(_SkillServiceMock):
        def list_skills(self, tenant_id=None):
            return [
                {
                    "skill_id": 1,
                    "name": "Created Skill",
                    "created_by": 100,
                    "group_ids": [1],
                    "ingroup_permission": "EDIT",
                },
                {
                    "skill_id": 2,
                    "name": "Editable Skill",
                    "created_by": 200,
                    "group_ids": [1],
                    "ingroup_permission": "EDIT",
                },
            ]

    with (
        patch.object(srs, "SkillService", ListSkillService),
        patch.object(
            srs,
            "get_user_tenant_by_user_id",
            return_value={"user_role": "DEV"},
        ),
        patch.object(_group_db_mock, "query_group_ids_by_user", return_value=[1]),
    ):
        created_result = srs.list_my_editable_skills_impl(
            tenant_id="tenant-1",
            user_id="100",
            ownership="created",
        )
        others_result = srs.list_my_editable_skills_impl(
            tenant_id="tenant-1",
            user_id="100",
            ownership="others",
        )

    assert created_result["counts"] == {"all": 2, "created": 1, "others": 1}
    assert [item["name"] for item in created_result["items"]] == ["Created Skill"]
    assert [item["name"] for item in others_result["items"]] == ["Editable Skill"]
    assert others_result["items"][0]["permission"] == "EDIT"
    assert created_result["items"][0]["can_publish"] is True
    assert others_result["items"][0]["can_publish"] is False


def test_list_repository_listings_validates_status():
    with pytest.raises(ValueError):
        srs.list_skill_repository_listings_impl(
            "tenant-1",
            user_id="user-1",
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
        user_id="user-1",
        status="shared",
    )
    assert result["items"][0]["status"] == "shared"
    assert result["items"][0]["can_take_down"] is True

    result = srs.list_skill_repository_listings_impl(
        "tenant-1",
        user_id="user-2",
        status="shared",
    )
    assert result["items"][0]["can_take_down"] is False

    _skill_repo_db_mock.get_skill_repository_by_id_and_publisher.return_value = (
        _repository_record(status="shared")
    )
    detail = srs.get_skill_repository_listing_detail_impl(1, "tenant-1")
    assert detail["skill_repository_id"] == 1
    assert detail["author"] == "dev@example.com"

    _user_tenant_db_mock.get_user_tenant_by_user_id.return_value = None
    detail = srs.get_skill_repository_listing_detail_impl(1, "tenant-1")
    assert detail["author"] is None

    record_without_creator = _repository_record(status="shared")
    record_without_creator["skill_info_json"]["created_by"] = None
    _skill_repo_db_mock.get_skill_repository_by_id_and_publisher.return_value = record_without_creator
    _user_tenant_db_mock.get_user_tenant_by_user_id.reset_mock()
    detail = srs.get_skill_repository_listing_detail_impl(1, "tenant-1")
    assert detail["author"] is None
    _user_tenant_db_mock.get_user_tenant_by_user_id.assert_not_called()


def test_repository_list_does_not_grant_take_down_to_regular_user():
    _skill_repo_db_mock.list_skill_repository_summaries.return_value = {
        "items": [_repository_record(status="shared")],
        "pagination": {"total": 1},
    }
    _user_tenant_db_mock.get_user_tenant_by_user_id.return_value = {
        "user_role": "USER"
    }

    result = srs.list_skill_repository_listings_impl(
        "tenant-1",
        user_id="user-1",
        status="shared",
    )

    assert result["items"][0]["can_take_down"] is False


def test_mapping_and_filter_helpers_cover_edge_branches():
    created_at = datetime(2026, 1, 1, 12, 0, 0)
    assert srs._serialize_created_at(created_at) == created_at.isoformat()
    assert srs._serialize_created_at("already serialized") == "already serialized"
    assert srs._to_repository_info_item({
        "skill_repository_id": 9,
        "status": "shared",
        "create_time": created_at,
    }) == {
        "skill_repository_id": 9,
        "status": "shared",
        "create_time": created_at.isoformat(),
    }
    assert srs._matches_ownership(
        {"created_by": "user-1"}, "user-1", srs.OWNERSHIP_OTHERS
    ) is False
    assert srs._matches_search({"name": "Any"}, None) is True
    assert srs._paginate_mine_skills_with_optional_padding([], 1, 10, False) == ([], 0)
    _user_tenant_db_mock.get_user_tenant_by_user_id.return_value = None
    assert srs._get_user_role("missing-user") == "USER"
    assert srs._normalize_listing_tags(None) == []
    with pytest.raises(ValueError, match="icon is required"):
        srs._validate_card_fields({"icon": 123})


def test_build_repository_payload_rejects_missing_skill_and_blank_name():
    class MissingSkillService(_SkillServiceMock):
        def get_skill_by_id(self, skill_id, tenant_id=None):
            return None

    with patch.object(srs, "SkillService", MissingSkillService):
        with pytest.raises(ValueError, match="Skill not found"):
            srs._build_repository_data_from_skill(10, "tenant-1", "user-1")

    class BlankNameSkillService(_SkillServiceMock):
        def get_skill_by_id(self, skill_id, tenant_id=None):
            data = super().get_skill_by_id(skill_id, tenant_id)
            data["name"] = "  "
            return data

    with patch.object(srs, "SkillService", BlankNameSkillService):
        with pytest.raises(ValueError, match="Skill name is required"):
            srs._build_repository_data_from_skill(10, "tenant-1", "user-1")


def test_export_skill_zip_and_repository_write_failures():
    class ExportMissingSkillService(_SkillServiceMock):
        def export_skills_by_names(self, skill_names, tenant_id=None):
            return [{"skill_name": skill_names[0], "skill_zip_base64": ""}]

    with patch.object(srs, "SkillService", ExportMissingSkillService):
        with pytest.raises(ValueError, match="Failed to export skill ZIP"):
            srs._export_skill_zip_base64(skill_name="Skill A", tenant_id="tenant-1")

    _skill_repo_db_mock.get_skill_repository_by_skill_id.return_value = (
        _repository_record(status="rejected")
    )
    _skill_repo_db_mock.update_skill_repository_by_id.return_value = 0
    with pytest.raises(ValueError, match="Failed to update repository listing"):
        srs.create_skill_repository_listing_impl(
            skill_id=10,
            tenant_id="tenant-1",
            user_id="user-1",
        )

    _skill_repo_db_mock.get_skill_repository_by_skill_id.return_value = None
    _skill_repo_db_mock.get_skill_repository_by_id_and_publisher.return_value = None
    with pytest.raises(ValueError, match="Failed to load repository listing"):
        srs.create_skill_repository_listing_impl(
            skill_id=10,
            tenant_id="tenant-1",
            user_id="user-1",
        )


def test_status_transition_edges_and_update_failures():
    su_record = _repository_record(status="pending_review")
    assert srs._validate_repository_status_transition(
        user_role="SU",
        current_status="pending_review",
        new_status="shared",
        record=su_record,
        user_id="su-1",
        tenant_id="tenant-1",
    ) is None

    with pytest.raises(ForbiddenError):
        srs._validate_repository_status_transition(
            user_role="ADMIN",
            current_status="pending_review",
            new_status="shared",
            record={**su_record, "publisher_tenant_id": "tenant-2"},
            user_id="admin-1",
            tenant_id="tenant-1",
        )

    publisher_updates = srs._validate_repository_status_transition(
        user_role="DEV",
        current_status="rejected",
        new_status="pending_review",
        record=_repository_record(status="rejected"),
        user_id="user-1",
        tenant_id="tenant-1",
    )
    assert publisher_updates == {
        "publisher_tenant_id": "tenant-1",
        "publisher_user_id": "user-1",
    }

    _skill_repo_db_mock.get_skill_repository_by_id_and_publisher.return_value = (
        _repository_record(status="rejected")
    )
    _skill_repo_db_mock.update_skill_repository_status_by_id.return_value = 0
    with pytest.raises(ValueError, match="Repository listing not found"):
        srs.update_skill_repository_status_impl(
            skill_repository_id=1,
            status="pending_review",
            user_id="user-1",
            tenant_id="tenant-1",
        )

    _skill_repo_db_mock.update_skill_repository_status_by_id.return_value = 1
    _skill_repo_db_mock.get_skill_repository_by_id_and_publisher.side_effect = [
        _repository_record(status="rejected"),
        None,
    ]
    with pytest.raises(ValueError, match="Failed to load repository listing"):
        srs.update_skill_repository_status_impl(
            skill_repository_id=1,
            status="pending_review",
            user_id="user-1",
            tenant_id="tenant-1",
        )


def test_copy_name_and_install_error_edges():
    assert srs._extract_duplicate_skill_name("plain failure") is None
    assert srs._truncate_copy_base_name("A" * 120, " suffix") == "A" * 93

    _skill_db_mock.get_skill_by_name.side_effect = None
    _skill_db_mock.get_skill_by_name.return_value = None
    assert srs._generate_available_copy_skill_name(
        base_name="Skill A",
        tenant_id="tenant-1",
    ) == "Skill A"

    _skill_db_mock.get_skill_by_name.side_effect = [
        {"skill_id": 1},
        {"skill_id": 2},
        None,
    ]
    assert srs._generate_available_copy_skill_name(
        base_name="Skill A",
        tenant_id="tenant-1",
    )

    encoded_zip = base64.b64encode(b"zip").decode("ascii")
    _skill_repo_db_mock.get_skill_repository_by_id_and_publisher.return_value = {
        **_repository_record(status="shared"),
        "skill_zip_base64": encoded_zip,
    }

    with patch.object(srs, "_generate_available_copy_skill_name", return_value=""):
        with pytest.raises(ValueError, match="Skill name is required"):
            srs.install_skill_from_repository_impl(
                skill_repository_id=1,
                tenant_id="tenant-1",
                user_id="user-1",
            )

    class FailingSkillService(_SkillServiceMock):
        def create_skill_from_zip_bytes(self, **kwargs):
            raise SkillException("boom")

    with patch.object(srs, "SkillService", FailingSkillService):
        with pytest.raises(SkillException, match="boom"):
            srs.install_skill_from_repository_impl(
                skill_repository_id=1,
                tenant_id="tenant-1",
                user_id="user-1",
                target_name="Skill Copy",
            )


def test_mine_list_attaches_repository_info_and_skips_empty_repository_rows():
    class ListSkillService(_SkillServiceMock):
        def list_skills(self, tenant_id=None):
            return [{
                "skill_id": 1,
                "name": "Skill A",
                "description": "desc",
                "source": "custom",
                "tags": ["tag"],
                "created_by": "user-1",
            }]

    _skill_repo_db_mock.list_skill_repository_by_skill_ids.return_value = [
        {"skill_id": None, "skill_repository_id": 99, "status": "shared"},
        {"skill_id": 1, "skill_repository_id": 1, "status": "shared"},
    ]
    with patch.object(srs, "SkillService", ListSkillService):
        result = srs.list_my_editable_skills_impl(
            tenant_id="tenant-1",
            user_id="user-1",
        )

    assert result["items"][0]["repository_info"] == [{
        "skill_repository_id": 1,
        "status": "shared",
        "create_time": None,
    }]


def test_repository_detail_not_found():
    _skill_repo_db_mock.get_skill_repository_by_id_and_publisher.return_value = None

    with pytest.raises(ValueError, match="Repository listing not found"):
        srs.get_skill_repository_listing_detail_impl(1, "tenant-1")
