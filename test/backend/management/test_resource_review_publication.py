# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Frozen publication and legacy mapping regressions with isolated persistence."""

from contextlib import nullcontext
from unittest.mock import AsyncMock, MagicMock

import pytest
from contracts.errors.exceptions import ReviewConflictError
from contracts.review import ReviewSubmissionRequest
from management.services.repository import reviews
from sqlalchemy.dialects import postgresql

from test.backend.management.test_resource_review_submissions import application


@pytest.fixture
def session(mocker):
    value = MagicMock()
    mocker.patch.object(reviews, "repository_unit_of_work", return_value=nullcontext(value))
    mocker.patch.object(reviews, "check_role_permission", return_value=True)
    mocker.patch.object(reviews, "lock_repository_source")
    mocker.patch.object(reviews, "_names", return_value={})
    mocker.patch.object(reviews, "create_repository_pending_review_notification")
    return value


def test_new_submission_freezes_payload_and_notifies_with_review_identity(session):
    session.scalar.return_value = None
    session.flush.side_effect = lambda: setattr(session.add.call_args.args[0], "review_id", 55)
    payload = {"name": "frozen", "content": " note ", "tags": ["first"]}
    result = reviews.save_submission("agent", 3, "tenant", "submitter", "ADMIN", payload, version_no=1)
    record = session.add.call_args.args[0]
    payload["tags"].append("later")
    assert record.resource_snapshot["payload"]["tags"] == ["first"]
    assert record.submit_description == "note"
    assert record.repository_id is None
    assert record.review_status == "pending_review"
    assert result["review_id"] == "55"
    notification = reviews.create_repository_pending_review_notification.call_args.kwargs
    assert notification["unique_id"] == 55
    assert notification["details"] == {"review_id": "55", "resource_type": "agent", "name": "frozen"}


def test_oversized_publication_field_rejected_before_transaction(session):
    with pytest.raises(ValueError, match="field length"):
        reviews.save_submission("agent", 3, "tenant", "u", "DEV", {"name": "x" * 101})
    session.scalar.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,version", [("agent", 1), ("skill", None), ("mcp", None)])
async def test_submit_dispatches_validated_fields_and_authenticated_identity(session, mocker, kind, version):
    agent = mocker.patch(
        "management.services.repository.agent.publishing.create_agent_repository_listing_impl",
        new_callable=AsyncMock,
        return_value={"review_id": "1"},
    )
    skill = mocker.patch(
        "services.skill_repository_service.create_skill_repository_listing_impl", return_value={"review_id": "2"}
    )
    mcp = mocker.patch(
        "management.services.repository.mcp.service.publish_community_mcp_service",
        new_callable=AsyncMock,
        return_value={"review_id": "3"},
    )
    request = ReviewSubmissionRequest(
        resource_type=kind,
        source_resource_id="3",
        version_no=version,
        submit_description="note",
        listing_fields={"tags": ["one"]},
    )
    result = await reviews.submit_repository_review("user", "tenant", "DEV", request)
    assert result == {"review_id": str(["agent", "skill", "mcp"].index(kind) + 1)}
    fields = {"tags": ["one"], "content": "note"}
    if kind == "agent":
        agent.assert_awaited_once_with(3, "tenant", "user", 1, card_fields=fields)
    elif kind == "skill":
        skill.assert_called_once_with(3, "tenant", "user", card_fields=fields)
    else:
        mcp.assert_awaited_once_with(tenant_id="tenant", user_id="user", mcp_id=3, **fields)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,version,fields", [("agent", None, {}), ("skill", 1, {}), ("mcp", None, {"user_id": "spoof"})]
)
async def test_submit_rejects_invalid_version_or_privileged_fields(session, kind, version, fields):
    request = ReviewSubmissionRequest(
        resource_type=kind, source_resource_id="3", version_no=version, listing_fields=fields
    )
    with pytest.raises(ValueError):
        await reviews.submit_repository_review("user", "tenant", "DEV", request)
    session.add.assert_not_called()


@pytest.mark.parametrize("kind", ["agent", "skill", "mcp"])
@pytest.mark.parametrize("existing", [False, True])
def test_publish_preserves_owner_and_counters_and_uses_frozen_source(session, kind, existing):
    model, key, tenant_field, status_field, source_field = reviews.REVIEW_MODELS[kind]
    target = model(**{key: 19, tenant_field: "tenant", "created_by": "original"}) if existing else None
    payload = {
        "description": "frozen",
        "created_by": "spoof",
        "downloads": 999,
        "download_count": 999,
        tenant_field: "other",
        "user_id": "spoof",
        "publisher_user_id": "spoof",
        "unknown": "ignored",
    }
    record = application(
        resource_type=kind, repository_id=19 if existing else None, resource_snapshot={"payload": payload}
    )
    session.scalar.side_effect = [object(), target]
    if not existing:
        session.flush.side_effect = lambda: setattr(session.add.call_args.args[0], key, 19)
    reviews._publish(session, record, "reviewer")
    published = target if existing else session.add.call_args.args[0]
    assert published.description == "frozen"
    assert getattr(published, tenant_field) == "tenant"
    assert published.created_by == ("original" if existing else "submitter")
    assert getattr(published, source_field) == 3
    assert getattr(published, status_field) == "shared"
    assert published.updated_by == "reviewer"
    assert not hasattr(published, "unknown")
    assert getattr(published, "download_count" if kind == "mcp" else "downloads") != 999
    assert record.repository_id == 19
    statements = [str(call.args[0].compile(dialect=postgresql.dialect())) for call in session.execute.call_args_list]
    assert len(statements) == (2 if kind == "mcp" else 1)
    if kind == "mcp":
        assert "market_id" in statements[-1]
    if existing:
        session.add.assert_not_called()


@pytest.mark.parametrize(
    "source,target,repository_id,message",
    [(None, None, None, "SOURCE_UNAVAILABLE"), (object(), None, 9, "REVIEW_MAPPING_CONFLICT")],
)
def test_publish_conflict_performs_no_writes(session, source, target, repository_id, message):
    session.scalar.side_effect = [source, target]
    with pytest.raises(ReviewConflictError, match=message):
        reviews._publish(session, application(repository_id=repository_id), "reviewer")
    session.execute.assert_not_called()
    session.add.assert_not_called()


@pytest.mark.parametrize("rows", [[], [application(), application(review_id=12)]])
def test_legacy_decision_rejects_missing_or_ambiguous_mapping(session, rows):
    session.scalars.return_value.all.return_value = rows
    with pytest.raises(ReviewConflictError, match="REVIEW_MAPPING_CONFLICT"):
        reviews.decide_legacy_review("agent", 9, "u", "tenant", "ADMIN", "shared")


@pytest.mark.parametrize("status,decision", [("shared", "approve"), ("rejected", "reject")])
def test_legacy_decision_maps_repository_identity_to_review(session, mocker, status, decision):
    session.scalars.return_value.all.return_value = [application()]
    operation = mocker.patch.object(reviews, "decide_repository_review", return_value={"status": status})
    assert reviews.decide_legacy_review("agent", 9, "u", "tenant", "ADMIN", status, "reason") == {"status": status}
    args = operation.call_args.args
    assert args[:4] == (11, "u", "tenant", "ADMIN")
    assert (args[4].decision, args[4].reason) == (decision, "reason")
