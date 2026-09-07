"""Unit tests for conversation knowledge-scope models."""

import pytest
from pydantic import ValidationError

from consts.model import (
    AidpKnowledgeScopeRequest,
    ConversationKnowledgeScopeRequest,
    ConversationKnowledgeScopeUpdateRequest,
    LocalKnowledgeScopeRequest,
)


def test_local_defaults_to_inherit_with_no_ids():
    scope = LocalKnowledgeScopeRequest()
    assert scope.mode == "inherit"
    assert scope.knowledge_ids == []


def test_local_norm_indent_deduplicate_and_reject():
    assert LocalKnowledgeScopeRequest.parse_obj(
        {"mode": "override", "knowledge_ids": [" 1 ", "1", "2"]}
    ).knowledge_ids == ["1", "2"]

    with pytest.raises(ValidationError):
        LocalKnowledgeScopeRequest.parse_obj(
            {"mode": "override", "knowledge_ids": ["", "1"]}
        )
    with pytest.raises(ValidationError):
        LocalKnowledgeScopeRequest.parse_obj(
            {"mode": "override", "knowledge_ids": ["x" * 33]}
        )


def test_local_override_requires_at_least_one_id():
    with pytest.raises(ValidationError):
        LocalKnowledgeScopeRequest.parse_obj({"mode": "override"})

    scope = LocalKnowledgeScopeRequest.parse_obj(
        {"mode": "override", "knowledge_ids": ["kb-1"]}
    )
    assert scope.mode == "override"


def test_local_non_override_rejects_ids():
    with pytest.raises(ValidationError):
        LocalKnowledgeScopeRequest.parse_obj(
            {"mode": "inherit", "knowledge_ids": ["kb-1"]}
        )
    with pytest.raises(ValidationError):
        LocalKnowledgeScopeRequest.parse_obj(
            {"mode": "disabled", "knowledge_ids": ["kb-1"]}
        )


def test_aidp_scope_normalization_and_validation():
    assert AidpKnowledgeScopeRequest.parse_obj(
        {"mode": "override", "kds_ids": [" k1 ", "k1", "k2"]}
    ).kds_ids == ["k1", "k2"]

    with pytest.raises(ValidationError):
        AidpKnowledgeScopeRequest.parse_obj(
            {"mode": "override", "kds_ids": [""]}
        )
    with pytest.raises(ValidationError):
        AidpKnowledgeScopeRequest.parse_obj(
            {"mode": "override", "kds_ids": ["x" * 257]}
        )
    with pytest.raises(ValidationError):
        AidpKnowledgeScopeRequest.parse_obj({"mode": "override"})
    with pytest.raises(ValidationError):
        AidpKnowledgeScopeRequest.parse_obj(
            {"mode": "inherit", "kds_ids": ["k1"]}
        )

    scope = AidpKnowledgeScopeRequest.parse_obj(
        {"mode": "override", "kds_ids": ["k1"]}
    )
    assert scope.mode == "override"
    assert scope.kds_ids == ["k1"]


def test_conversation_scope_defaults_and_composition():
    scope = ConversationKnowledgeScopeRequest()
    assert scope.schema_version == 1
    assert scope.local.mode == "inherit"
    assert scope.aidp.mode == "inherit"

    scope = ConversationKnowledgeScopeRequest.parse_obj(
        {
            "local": {"mode": "override", "knowledge_ids": ["kb-1"]},
            "aidp": {"mode": "disabled"},
        }
    )
    assert scope.local.knowledge_ids == ["kb-1"]
    assert scope.aidp.mode == "disabled"


def test_update_request_accepts_null_scope():
    assert ConversationKnowledgeScopeUpdateRequest().scope is None
    scope = ConversationKnowledgeScopeUpdateRequest.parse_obj(
        {"scope": {"local": {"mode": "inherit"}, "aidp": {"mode": "inherit"}}}
    )
    assert scope.scope is not None
    assert scope.scope.local.mode == "inherit"

def test_local_disabled_mode_without_ids():
    scope = LocalKnowledgeScopeRequest.parse_obj({"mode": "disabled"})
    assert scope.mode == "disabled"
    assert scope.knowledge_ids == []


def test_aidp_disabled_mode_without_ids():
    scope = AidpKnowledgeScopeRequest.parse_obj({"mode": "disabled"})
    assert scope.mode == "disabled"
    assert scope.kds_ids == []


def test_conversation_scope_rejects_wrong_version():
    with pytest.raises(ValidationError):
        ConversationKnowledgeScopeRequest.parse_obj({"schema_version": 2})
