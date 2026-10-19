# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Unit regressions for optional CAS presentation metadata."""

from copy import deepcopy
from unittest.mock import Mock

import pytest

from services import user_identity_service as identity


def test_batch_metadata_preserves_raw_values_and_duplicate_names(monkeypatch):
    lookup = Mock(return_value={
        "a": {"cas_username": " 同名 ", "email": "a@test"},
        "b": {"cas_username": "同名", "email": "b@test"},
    })
    monkeypatch.setattr(identity, "get_cas_identities", lookup)
    records = [{"id": "a", "username": "a@test"}, {"id": "b", "username": "b@test"}]
    originals = deepcopy(records)
    identity.enrich_cas_usernames(records, {"cas_username": "id"})
    assert lookup.call_args.args[0] == {"a", "b"}
    assert lookup.call_count == 1
    assert [row["cas_username"] for row in records] == ["同名", "同名"]
    assert [{k: v for k, v in row.items() if k != "cas_username"} for row in records] == originals


@pytest.mark.parametrize("name", [None, "", " \t "])
def test_missing_or_blank_name_keeps_legacy_fallback(monkeypatch, name):
    monkeypatch.setattr(identity, "get_cas_identities", Mock(return_value={"a": {"cas_username": name}}))
    rows = [{"id": "a", "username": "a@test"}, {"username": "unknown"}]
    original = deepcopy(rows)
    assert identity.enrich_cas_usernames(rows, {"cas_username": "id"}) == original


def test_optional_lookup_failure_does_not_break_response(monkeypatch):
    monkeypatch.setattr(identity, "get_cas_identities", Mock(side_effect=RuntimeError("unavailable")))
    rows = [{"id": "a", "username": "a@test"}]
    assert identity.enrich_cas_usernames(rows, {"cas_username": "id"}) == [{"id": "a", "username": "a@test"}]


def test_empty_records_never_query_database(monkeypatch):
    lookup = Mock()
    monkeypatch.setattr(identity, "get_cas_identities", lookup)
    assert identity.enrich_cas_usernames([], {"cas_username": "id"}) == []
    lookup.assert_not_called()


@pytest.mark.parametrize("kind", ["agent", "skill"])
@pytest.mark.parametrize("author,linked,expected", [
    ("a@test", "a", True),
    ("External Author", "a", False),
    ("external@test", "a", False),
    ("a@test", None, False),
])
def test_repository_authors_require_explicit_id_and_matching_platform_email(monkeypatch, kind, author, linked, expected):
    monkeypatch.setattr(identity, "get_cas_identities", Mock(return_value={
        "a": {"cas_username": "作者", "email": "a@test"},
        "b": {"cas_username": "提交人", "email": "b@test"},
    }))
    snapshot = {"created_by": linked}
    if kind == "agent":
        snapshot = {"agent_id": 42, "agent_info": {"42": snapshot}}
    monkeypatch.setattr(identity, "get_repository_agent_identity_ids", Mock(return_value={9: {"author_id": linked}}))
    row = {"agent_repository_id": 9, f"{kind}_info_json": snapshot, "author": author,
           "publisher_user_id": "b", "submitted_by": "b@test"}
    identity.enrich_repository_identities([row], kind)
    assert (row.get("author_cas_username") == "作者") is expected
    assert row["author"] == author
    assert row["submitted_by"] == "b@test"
    assert row["submitted_by_cas_username"] == "提交人"


def test_repository_summary_resolves_versioned_creator_and_publisher_in_batches(monkeypatch):
    associations = Mock(return_value={9: {"author_id": "a", "submitter_id": "b"}})
    monkeypatch.setattr(identity, "get_repository_agent_identity_ids", associations)
    lookup = Mock(return_value={
        "a": {"cas_username": "作者", "email": "a@test"},
        "b": {"cas_username": "提交人", "email": "b@test"},
    })
    monkeypatch.setattr(identity, "get_cas_identities", lookup)
    row = {"agent_repository_id": 9, "author": "a@test", "submitted_by": "b@test"}
    identity.enrich_repository_identities([row], "agent")
    assert identity.repository_identity_fields(row) == {
        "author_cas_username": "作者", "submitted_by_cas_username": "提交人",
    }
    associations.assert_called_once_with({9})
    lookup.assert_called_once_with({"a", "b"})
    assert row["author"] == "a@test"


def test_repository_association_failure_preserves_unverified_author(monkeypatch):
    monkeypatch.setattr(identity, "get_repository_agent_identity_ids", Mock(side_effect=RuntimeError("unavailable")))
    lookup = Mock()
    monkeypatch.setattr(identity, "get_cas_identities", lookup)
    row = {"agent_repository_id": 9, "author": "a@test", "submitted_by": "b@test"}
    original = deepcopy(row)
    identity.enrich_repository_identities([row], "agent")
    assert row == original
    lookup.assert_not_called()


def test_agent_imported_snapshot_cannot_claim_platform_author_identity(monkeypatch):
    monkeypatch.setattr(identity, "get_repository_agent_identity_ids", Mock(return_value={}))
    lookup = Mock()
    monkeypatch.setattr(identity, "get_cas_identities", lookup)
    row = {"agent_repository_id": 9, "author": "a@test", "agent_info_json": {
        "agent_id": 42, "agent_info": {"42": {"created_by": "a"}},
    }}
    identity.enrich_repository_identities([row], "agent")
    assert "author_cas_username" not in row
    assert row["author"] == "a@test"
    lookup.assert_not_called()


def test_unavailable_lookup_discards_cached_optional_name(monkeypatch):
    monkeypatch.setattr(identity, "get_cas_identities", Mock(side_effect=RuntimeError("unavailable")))
    row = {"id": "a", "username": "a@test", "cas_username": "stale username"}
    identity.enrich_cas_usernames([row], {"cas_username": "id"})
    assert row == {"id": "a", "username": "a@test"}


@pytest.mark.parametrize("submitted_by", [None, "", "old-email@test"])
def test_platform_submitter_uses_publisher_id_without_changing_original_text(monkeypatch, submitted_by):
    monkeypatch.setattr(identity, "get_cas_identities", Mock(return_value={
        "publisher": {"cas_username": "提交人", "email": "current-email@test"},
    }))
    row = {"publisher_user_id": "publisher", "submitted_by": submitted_by}
    identity.enrich_repository_identities([row], "skill")
    assert row["submitted_by"] == submitted_by
    assert row["submitted_by_cas_username"] == "提交人"
