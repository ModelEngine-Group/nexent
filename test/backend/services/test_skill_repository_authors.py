# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Skill author display metadata must never replace operational creator IDs."""

import pytest
from management.services.permission.identity import display
from services import skill_repository_service as service


@pytest.fixture
def identities(mocker):
    emails = mocker.patch.object(service, "get_user_email_map", return_value={})
    cas = mocker.patch.object(display, "load_cas_identities", return_value={})
    return emails, cas


def test_author_lookup_batches_duplicate_creators_and_preserves_identity(identities):
    emails, cas = identities
    emails.return_value = {"creator": " author@example.test "}
    cas.return_value = {"creator": {"email": "author@example.test", "cas_username": "Author"}}
    rows = [
        {"skill_id": 1, "created_by": "creator", "permission": "EDIT"},
        {"skill_id": 2, "created_by": "creator", "permission": "READ_ONLY"},
        {"new_skill_padding": True},
    ]
    service._enrich_mine_skill_authors(rows)
    emails.assert_called_once_with(["creator"])
    cas.assert_called_once()
    assert rows[0]["author"] == rows[1]["author"] == "author@example.test"
    assert rows[0]["author_cas_username"] == rows[1]["author_cas_username"] == "Author"
    assert [row["created_by"] for row in rows[:2]] == ["creator", "creator"]
    assert [row["permission"] for row in rows[:2]] == ["EDIT", "READ_ONLY"]
    assert rows[2] == {"new_skill_padding": True}


@pytest.mark.parametrize("email", [None, "", "   "])
def test_unavailable_account_never_falls_back_to_uuid(identities, email):
    emails, _ = identities
    emails.return_value = {"internal-uuid": email}
    rows = [{"created_by": "internal-uuid"}]
    service._enrich_mine_skill_authors(rows)
    assert rows == [{"created_by": "internal-uuid", "author": None}]


def test_optional_display_lookup_failure_keeps_record_usable(identities):
    emails, _ = identities
    emails.side_effect = RuntimeError("Display lookup unavailable")
    rows = [{"skill_id": 7, "created_by": "creator", "permission": "EDIT"}]
    service._enrich_mine_skill_authors(rows)
    assert rows[0] == {"skill_id": 7, "created_by": "creator", "permission": "EDIT", "author": None}


def test_empty_page_and_padding_do_not_query_accounts(identities):
    emails, cas = identities
    service._enrich_mine_skill_authors([])
    service._enrich_mine_skill_authors([{"new_skill_padding": True}])
    emails.assert_not_called()
    cas.assert_not_called()


def test_cas_username_requires_canonical_email_match(identities):
    emails, cas = identities
    emails.return_value = {"creator": "correct@example.test"}
    cas.return_value = {"creator": {"email": "other@example.test", "cas_username": "Wrong identity"}}
    rows = [{"created_by": "creator"}]
    service._enrich_mine_skill_authors(rows)
    assert rows[0]["author"] == "correct@example.test"
    assert "author_cas_username" not in rows[0]


def test_listing_enriches_only_current_page_without_changing_ownership(identities, mocker):
    emails, _ = identities
    emails.return_value = {"owner": "owner@example.test", "other": "other@example.test"}
    mocker.patch.object(service, "_get_user_role", return_value=("DEV",))
    skills = [
        {"skill_id": 1, "name": "mine", "created_by": "owner", "permission": "EDIT"},
        {"skill_id": 2, "name": "shared", "created_by": "other", "permission": "READ_ONLY"},
        {"skill_id": 3, "name": "next page", "created_by": "third", "permission": "READ_ONLY"},
    ]
    mocker.patch.object(service, "SkillService").return_value.list_visible_skills.return_value = skills
    mocker.patch.object(service, "_list_repository_info_by_skill_id", return_value={})
    mocker.patch.object(service.TagManagementDB, "list_resource_assignment_display_values_by_ids", return_value={})
    result = service.list_my_editable_skills_impl("tenant", "owner", page_size=2)
    emails.assert_called_once_with(["other", "owner"])
    assert [item["author"] for item in result["items"]] == ["owner@example.test", "other@example.test"]
    assert [item["created_by"] for item in result["items"]] == ["owner", "other"]
    assert result["counts"] == {"all": 3, "created": 1, "others": 2}
    assert result["items"][0]["can_publish"] is True
    assert result["items"][1]["permission"] == "READ_ONLY"
