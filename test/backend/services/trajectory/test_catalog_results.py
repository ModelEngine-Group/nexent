# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Catalog results preserve ownership, bounded previews and unknown values."""

import pytest
import test_catalog as fixtures

catalog = fixtures.catalog


def test_catalog_rows_keep_category_and_fallback_labels(catalog, mocker):
    from types import SimpleNamespace

    service, _ = catalog
    conversation = SimpleNamespace(
        created_by="u", conversation_id=12, conversation_title="Query", agent_id=None
    )
    rows = [(conversation, "t", None, True)]
    mocker.patch("sqlalchemy.orm.Query.all", return_value=rows)
    expected = {
        "tenant_id": "t",
        "user_id": "u",
        "user_name": "u",
        "conversation_id": "12",
        "conversation_title": "Query",
        "agent_id": None,
        "category": "workbench",
    }
    assert service.candidates(["t"]) == [expected]
    assert service.resolve(["t"], "12") == expected
    assert service.cleanup_candidates("t", 0, limit=10) == [expected]
    conversation.agent_id = 7
    rows[:] = [(conversation, "t", "owner@example.com", False)]
    item = service.candidates(["t"])[0]
    assert (
        item["agent_id"] == "7"
        and item["user_name"] == "owner@example.com"
        and item["category"] == "agent_chat"
    )
    from ops.services.trajectory.primitives import QueryError

    with pytest.raises(QueryError, match="candidate_budget_exceeded"):
        service.candidates(["t"], limit=0)
    for invalid in ([], rows * 2):
        mocker.patch("sqlalchemy.orm.Query.all", return_value=invalid)
        with pytest.raises(QueryError, match="trajectory_not_found"):
            service.resolve(["t"], "12")


def test_catalog_scalar_boundaries_and_name_budget(catalog, mocker):
    from ops.services.trajectory.primitives import QueryError

    service, _ = catalog
    mocker.patch("sqlalchemy.orm.Query.scalar", return_value=None)
    assert service.message_upper("12") == 0
    mocker.patch("sqlalchemy.orm.Query.scalar", return_value=20)
    assert service.message_upper("12") == 20
    mocker.patch("sqlalchemy.orm.Query.first", return_value=None)
    assert not service.user_active("t", "u") and service.conversation_deleted("12", "u")
    mocker.patch("sqlalchemy.orm.Query.first", return_value=("u",))
    assert service.user_active("t", "u") and not service.conversation_deleted("12", "u")
    assert service.agent_names(["t"], set()) == {}
    mocker.patch("sqlalchemy.orm.Query.all", return_value=[("t", 7, "name")] * 10001)
    with pytest.raises(QueryError, match="agent_budget_exceeded"):
        service.agent_names(["t"], {"7"})
    for limit in (0, 10001):
        with pytest.raises(ValueError, match="source limit"):
            service.source_messages("t", "u", "12", limit=limit)


def test_catalog_message_and_user_previews_are_bounded_without_splitting_unicode(
    catalog, mocker
):
    service, _ = catalog
    mocker.patch(
        "sqlalchemy.orm.Query.all", return_value=[("t", "u", None), ("t", "v", "Name")]
    )
    assert service.user_page(["t"], "", None, 20) == [
        {"id": "u", "name": "u", "tenant_id": "t"},
        {"id": "v", "name": "Name", "tenant_id": "t"},
    ]
    mocker.patch("sqlalchemy.orm.Query.all", return_value=[("t", "Name")])
    assert service.names(["t"]) == {"t": "Name"}
    mocker.patch(
        "sqlalchemy.orm.Query.all",
        return_value=[
            (11, "user", "中" * 4096, 4096, 12288, "hash", "success"),
            (12, "assistant", None, None, None, None, "success"),
        ],
    )
    result = service.messages("12", 20, 0, 10)
    assert result[0]["preview"] == "中" * 1365
    assert result[0]["byte_count"] == 12288 and result[0]["char_count"] == 4096
    assert (
        result[1]["preview"] == ""
        and result[1]["byte_count"] == result[1]["char_count"] == 0
    )


def test_catalog_session_sets_statement_timeout(mocker):
    from contextlib import nullcontext
    from unittest.mock import Mock

    from ops.db.trajectory.catalog import _session

    session = Mock()
    mocker.patch(
        "ops.db.trajectory.catalog.get_db_session", return_value=nullcontext(session)
    )
    with _session() as actual:
        assert actual is session
    assert (
        str(session.execute.call_args.args[0])
        == "SET LOCAL statement_timeout = '2000ms'"
    )
