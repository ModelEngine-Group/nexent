# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Submission immutability and publication orchestration without external I/O."""

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from contracts.errors.exceptions import ReviewConflictError, UnauthorizedError
from contracts.review import ReviewDecisionRequest, ReviewListQuery
from management.db.agent.models import AgentRepository
from management.db.mcp.models import McpMarketRecord
from management.db.skill.models import SkillRepository
from management.db.repository_reviews import scope_conditions
from management.services.repository import reviews


def application(**updates):
    values = dict(
        review_id=11,
        tenant_id="tenant",
        resource_type="agent",
        source_resource_id=3,
        version_no=1,
        repository_id=None,
        submitted_user_id="submitter",
        submitted_at=datetime.now(timezone.utc),
        submit_description="note",
        resource_snapshot={
            "schema_version": 1,
            "payload": {"name": "frozen", "content": "note"},
        },
        review_status="pending_review",
        review_comment=None,
        reviewed_by=None,
        reviewed_at=None,
    )
    return SimpleNamespace(**{**values, **updates})


@pytest.fixture
def isolated(mocker):
    session = MagicMock()

    @contextmanager
    def transaction():
        yield session

    mocker.patch.object(reviews, "repository_unit_of_work", transaction)
    mocker.patch.object(reviews, "require_repository_access")
    mocker.patch.object(reviews, "lock_repository_source")
    mocker.patch.object(reviews, "_names", return_value={})
    mocker.patch.object(reviews, "create_repository_pending_review_notification")
    mocker.patch.object(reviews, "create_repository_review_notification")
    mocker.patch("management.services.notification.service.deactivate_notifications")
    return session


def test_same_pending_submission_returns_original_without_rewriting(isolated):
    record = application()
    isolated.scalar.return_value = record
    result = reviews.save_submission(
        "agent",
        3,
        "tenant",
        "submitter",
        "ADMIN",
        {"name": "frozen", "content": "note"},
        version_no=1,
    )
    assert result["review_id"] == "11"
    assert result["repository_id"] is None
    isolated.add.assert_not_called()
    reviews.create_repository_pending_review_notification.assert_not_called()


@pytest.mark.parametrize(
    "user,payload",
    [
        ("other", {"name": "frozen", "content": "note"}),
        ("submitter", {"name": "changed", "content": "note"}),
    ],
)
def test_pending_conflict_never_replaces_snapshot(isolated, user, payload):
    record = application()
    isolated.scalar.return_value = record
    with pytest.raises(ReviewConflictError, match="PENDING_REVIEW_EXISTS"):
        reviews.save_submission(
            "agent", 3, "tenant", user, "ADMIN", payload, version_no=1
        )
    assert record.resource_snapshot["payload"]["name"] == "frozen"
    isolated.add.assert_not_called()


def test_rejection_preserves_repository_and_records_final_opinion(isolated, mocker):
    record = application(repository_id=9)
    mocker.patch.object(reviews, "get_review", return_value=record)
    publish = mocker.patch.object(reviews, "_publish")
    result = reviews.decide_repository_review(
        11,
        "reviewer",
        "tenant",
        "ADMIN",
        ReviewDecisionRequest(decision="reject", reason="reason"),
    )
    publish.assert_not_called()
    assert result["status"] == "rejected"
    assert record.repository_id == 9
    assert record.review_comment == "reason"
    assert record.reviewed_by == "reviewer"


def test_approval_publishes_frozen_record_before_completing(isolated, mocker):
    record = application()
    mocker.patch.object(reviews, "get_review", return_value=record)

    def publish(session, pending, user):
        assert pending.review_status == "pending_review"
        assert pending.resource_snapshot["payload"]["name"] == "frozen"
        pending.repository_id = 27

    mocker.patch.object(reviews, "_publish", side_effect=publish)
    result = reviews.decide_repository_review(
        11, "reviewer", "tenant", "ADMIN", ReviewDecisionRequest(decision="approve")
    )
    assert result["repository_id"] == "27"
    assert result["status"] == "approved"


def test_publish_failure_does_not_complete_or_notify(isolated, mocker):
    record = application()
    mocker.patch.object(reviews, "get_review", return_value=record)
    mocker.patch.object(
        reviews, "_publish", side_effect=RuntimeError("publication failed")
    )
    with pytest.raises(RuntimeError, match="publication failed"):
        reviews.decide_repository_review(
            11, "reviewer", "tenant", "ADMIN", ReviewDecisionRequest(decision="approve")
        )
    assert record.review_status == "pending_review"
    assert record.reviewed_at is None
    reviews.create_repository_review_notification.assert_not_called()


def test_completed_review_cannot_be_overwritten(isolated, mocker):
    record = application(review_status="approved", review_comment="original")
    mocker.patch.object(reviews, "get_review", return_value=record)
    with pytest.raises(ReviewConflictError, match="REVIEW_ALREADY_PROCESSED"):
        reviews.decide_repository_review(
            11,
            "reviewer",
            "tenant",
            "ADMIN",
            ReviewDecisionRequest(decision="reject", reason="replacement"),
        )
    assert record.review_comment == "original"


def test_non_reviewer_cannot_decide_own_application(isolated, mocker):
    mocker.patch.object(reviews, "get_review", return_value=application())
    with pytest.raises(UnauthorizedError):
        reviews.decide_repository_review(
            11, "submitter", "tenant", "DEV", ReviewDecisionRequest(decision="approve")
        )


def test_authorized_scope_preserves_existing_role_boundaries():
    compile_sql = lambda conditions: str(
        conditions[-1].compile(dialect=postgresql.dialect())
    )
    assert "submitted_user_id" in compile_sql(
        scope_conditions("agent", "u", "t", "DEV")
    )
    assert len(scope_conditions("agent", "u", "t", "ADMIN")) == 3
    assert len(scope_conditions("mcp", "u", "t", "SU")) == 2
    assert (
        ReviewListQuery(resource_type="agent", status="approved").resource_type
        == "agent"
    )


@pytest.mark.parametrize("model", [AgentRepository, SkillRepository, McpMarketRecord])
def test_repository_tables_have_no_added_review_columns(model):
    assert not (
        {
            "submitted_at",
            "submitted_user_id",
            "submit_description",
            "review_comment",
            "submission_revision",
            "published_at",
        }
        & set(model.__table__.columns.keys())
    )


def test_latest_review_summary_is_batched_and_does_not_replace_repository_state(
    isolated, mocker
):
    from contextlib import nullcontext

    record = application()
    isolated.scalars.return_value.all.return_value = [record]
    mocker.patch.object(reviews, "get_db_session", return_value=nullcontext(isolated))
    mocker.patch(
        "management.db.identity.user_tenant.get_user_tenant_by_user_id",
        return_value={"user_role": "DEV"},
    )
    items = [
        {"agent_id": 3, "repository_info": [{"status": "shared"}]},
        {"agent_id": 4},
    ]
    reviews.attach_latest_reviews(items, "agent", "agent_id", "submitter", "tenant")
    isolated.scalars.assert_called_once()
    assert items[0]["latest_review"]["review_id"] == "11"
    assert items[0]["latest_review"]["status"] == "pending_review"
    assert items[0]["repository_info"] == [{"status": "shared"}]
    assert items[1]["latest_review"] is None


def test_invalid_publication_field_is_rejected_before_creating_pending_application(
    isolated,
):
    with pytest.raises(ValueError, match="name exceeds"):
        reviews.save_submission(
            "agent",
            3,
            "tenant",
            "submitter",
            "ADMIN",
            {"name": "x" * 101},
            version_no=1,
        )
    isolated.add.assert_not_called()
