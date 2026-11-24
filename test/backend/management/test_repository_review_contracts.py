# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Boundary tests for the new review contracts without database or provider I/O."""

import pytest
from pydantic import ValidationError

from contracts.review import ReviewDecisionRequest, ReviewListItem, ReviewListQuery, ReviewPagination


@pytest.mark.parametrize("decision", ["approve", "reject"])
@pytest.mark.parametrize("reason,expected", [(None, None), ("  ", None), (" 意见 ", "意见"), ("😀" * 1000, "😀" * 1000)])
def test_decision_preserves_optional_unicode_reason(decision, reason, expected):
    request = ReviewDecisionRequest(decision=decision, reason=reason)
    assert request.reason == expected


@pytest.mark.parametrize("updates", [
    {"reason": "中" * 1001}, {"reason": "😀" * 1001},
    {"decision": "delete"}, {"expected_revision": -1},
    {"expected_revision": True}, {"expected_revision": "1"},
    {"user_id": "other"}, {"tenant_id": "other"}, {"scope": "all"},
])
def test_decision_rejects_invalid_or_client_authority_fields(updates):
    with pytest.raises(ValidationError):
        ReviewDecisionRequest.model_validate({"decision": "approve", **updates})


def test_query_defaults_and_trimmed_search():
    query = ReviewListQuery.model_validate({"type": "skill", "search": " 测试 "})
    assert query.resource_type == "skill"
    assert query.search == "测试"
    assert (query.status, query.page, query.page_size) == ("all", 1, 10)
    assert ReviewListQuery(page_size=100).page_size == 100


@pytest.mark.parametrize("updates", [{"page": 0}, {"page_size": 0}, {"page_size": 101}, {"type": "unknown"}, {"status": "not_shared"}])
def test_query_rejects_unsupported_values(updates):
    with pytest.raises(ValidationError):
        ReviewListQuery.model_validate(updates)


def make_item(repository_id):
    return ReviewListItem(
        resource_type="agent", review_id=repository_id, source_resource_id="1", repository_id=None,
        tenant_id="tenant", name="Legacy submission", status="pending_review",
        submitter={},
    )


def test_legacy_unknown_identity_and_bigint_are_not_inferred():
    item = make_item("9223372036854775807")
    assert item.model_dump(mode="json")["review_id"] == "9223372036854775807"
    assert item.repository_id is None
    assert item.submitted_user_id is None
    assert item.submitted_at is None
    assert item.published_at is None
    assert item.submit_description is None
    assert item.review_comment is None
    assert item.allowed_actions == []


@pytest.mark.parametrize("repository_id", ["0", "01", "-1", "1.0", "1e3", "9223372036854775808", 9007199254740993])
def test_list_item_rejects_invalid_ids(repository_id):
    with pytest.raises(ValidationError):
        make_item(repository_id)


@pytest.mark.parametrize("total,expected", [(0, 0), (10, 1), (11, 2)])
def test_pagination_reports_total_pages_for_empty_and_partial_pages(total, expected):
    pagination = ReviewPagination(page=3, page_size=10, total=total)
    assert pagination.model_dump()["total_pages"] == expected
