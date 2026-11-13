# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""A chat body reference tracks the current target message through final checks."""

from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
from ops.services.trajectory.access import Actor
from ops.services.trajectory.primitives import QueryError, ReferenceStore
from ops.services.trajectory.service import TrajectoryService

ACTOR = Actor("admin", "tenant", "ADMIN")


@pytest.fixture
def service():
    catalog = Mock()
    catalog.tenants.return_value = ["tenant"]
    catalog.actor_active.return_value = True
    catalog.resolve.return_value = {
        "tenant_id": "tenant",
        "user_id": "owner",
        "conversation_id": "1",
        "conversation_title": "Title",
        "user_name": "owner",
    }
    catalog.message_content.return_value = (b"answer", "initial-hash", 6, 6)
    result = TrajectoryService(Mock(), catalog, ReferenceStore())
    result.archive = SimpleNamespace(manifest=Mock(return_value=None))
    return result


def content_id(service, expected_hash="initial-hash"):
    return service.references.issue(
        "content",
        {
            "actor": ACTOR.binding,
            "tenant": "tenant",
            "owner": "owner",
            "conversation": "1",
            "cleanup": 0,
            "field": "chat",
            "message_id": "11",
            "message_hash": expected_hash,
        },
    )


def read(service, **kwargs):
    return service.content(ACTOR, "1", content_id(service), **kwargs)


def test_unchanged_message_rechecks_only_metadata_after_authorization(service):
    result = read(service)
    assert result["text"] == "answer" and result["next_offset"] == 6
    assert result["complete"] and result["byte_count"] == 6
    assert service.catalog.message_content.call_args_list == [
        call("1", "11", 0, 1048576),
        call("1", "11", 0, 0),
    ]
    assert service.catalog.resolve.call_count == 2


@pytest.mark.parametrize("change", [None, (b"", "edited-hash", 6, 6)])
def test_target_changed_during_final_authorization_invalidates_block(service, change):
    original = service.catalog.resolve.return_value

    def resolve(*args, **kwargs):
        if service.catalog.resolve.call_count == 2:
            service.catalog.message_content.return_value = change
        return original

    service.catalog.resolve.side_effect = resolve
    with pytest.raises(QueryError, match="snapshot_reset") as raised:
        read(service)
    assert raised.value.status == 409
    service.catalog.message_content.assert_called_with("1", "11", 0, 0)


def test_other_message_change_does_not_invalidate_target_reference(service):
    original = service.catalog.message_content.return_value

    def message(conversation, identity, offset, count):
        return original if identity == "11" else (b"changed", "other-hash", 7, 7)

    service.catalog.message_content.side_effect = message
    assert read(service)["text"] == "answer"
    assert all(
        args.args[1] == "11" for args in service.catalog.message_content.call_args_list
    )


def test_empty_block_at_end_still_rechecks_target_version(service):
    service.catalog.message_content.return_value = (b"", "initial-hash", 6, 6)
    result = read(service, offset=6)
    assert result["text"] == "" and result["complete"]
    assert result["offset"] == result["next_offset"] == 6
    service.catalog.message_content.assert_called_with("1", "11", 0, 0)


@pytest.mark.parametrize("value", [(None, None, None, None), (b"", "empty-hash", 0, 0)])
def test_existing_null_and_empty_messages_return_empty_verified_content(service, value):
    service.catalog.message_content.return_value = value
    result = service.content(ACTOR, "1", content_id(service, expected_hash=value[1]))
    assert result["text"] == "" and result["complete"]
    assert result["byte_count"] == result["char_count"] == 0
    assert result["offset"] == result["next_offset"] == 0
    service.catalog.message_content.assert_called_with("1", "11", 0, 0)


def test_version_lookup_failure_does_not_return_a_stale_block(service):
    error = ConnectionError("controlled version lookup failure")
    service.catalog.message_content.side_effect = [
        (b"answer", "initial-hash", 6, 6),
        error,
    ]
    with pytest.raises(ConnectionError) as raised:
        read(service)
    assert raised.value is error


def test_final_revocation_prevents_both_body_return_and_version_query(service):
    original = service.catalog.resolve.return_value
    service.catalog.resolve.side_effect = [
        original,
        QueryError("trajectory_not_found", 404),
    ]
    with pytest.raises(QueryError, match="trajectory_not_found") as raised:
        read(service)
    assert raised.value.status == 404
    service.catalog.message_content.assert_called_once_with("1", "11", 0, 1048576)


def test_cleanup_change_precedes_final_message_version_query(service):
    service.archive.manifest.side_effect = [None, {"cleanup_version": 1}]
    with pytest.raises(QueryError, match="snapshot_reset"):
        read(service)
    service.catalog.message_content.assert_called_once_with("1", "11", 0, 1048576)
