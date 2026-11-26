# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Unit tests for conversation knowledge-scope models."""

import pytest
from pydantic import ValidationError

from contracts.knowledge import AidpKnowledgeScopeRequest, AidpMetadataFilterRequest, ConversationKnowledgeScopeRequest, ConversationKnowledgeScopeUpdateRequest, LocalKnowledgeScopeRequest


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
        ConversationKnowledgeScopeRequest.parse_obj({"schema_version": 4})


def test_conversation_scope_accepts_metadata_filter():
    scope = ConversationKnowledgeScopeRequest.parse_obj(
        {
            "schema_version": 1,
            "aidp": {
                "mode": "inherit",
                "metadata_filter": {
                    "enabled": True,
                    "match": "any",
                    "conditions": [
                        {"operator": "contains", "value": "合同"},
                        {"operator": "is", "value": "预算.xlsx"},
                    ],
                },
            },
        }
    )

    assert scope.schema_version == 1
    assert scope.aidp.metadata_filter.enabled is True
    assert scope.aidp.metadata_filter.match == "any"
    assert [item.value for item in scope.aidp.metadata_filter.conditions] == [
        "合同",
        "预算.xlsx",
    ]


def test_metadata_filter_rejects_disabled_or_empty_mode():
    with pytest.raises(ValidationError):
        AidpKnowledgeScopeRequest.parse_obj(
            {
                "mode": "disabled",
                "metadata_filter": {
                    "enabled": True,
                    "conditions": [
                        {"operator": "contains", "value": "合同"}
                    ],
                },
            }
        )
    with pytest.raises(ValidationError):
        AidpKnowledgeScopeRequest.parse_obj(
            {"metadata_filter": {"enabled": True}}
        )


def test_metadata_filter_trims_conditions_and_deduplicates():
    filter_value = AidpMetadataFilterRequest.parse_obj(
        {
            "enabled": True,
            "conditions": [
                {"operator": "contains", "value": " 合同 "},
                {"operator": "contains", "value": "合同"},
                {"operator": "starts_with", "value": "预算"},
                {"operator": "ends_with", "value": "xlsx"},
            ],
        }
    )

    assert [item.value for item in filter_value.conditions] == [
        "合同",
        "预算",
        "xlsx",
    ]
    assert [item.operator for item in filter_value.conditions] == [
        "contains",
        "starts_with",
        "ends_with",
    ]


def test_metadata_filter_clears_conditions_when_disabled():
    filter_value = AidpMetadataFilterRequest.parse_obj(
        {
            "enabled": False,
            "conditions": [{"operator": "contains", "value": "合同"}],
        }
    )

    assert filter_value.conditions == []


def test_metadata_filter_rejects_too_many_conditions_or_long_values():
    with pytest.raises(ValidationError):
        AidpMetadataFilterRequest.parse_obj(
            {
                "enabled": True,
                "conditions": [
                    {"operator": "contains", "value": f"file-{index}"}
                    for index in range(21)
                ],
            }
        )
    with pytest.raises(ValidationError):
        AidpMetadataFilterRequest.parse_obj(
            {
                "enabled": True,
                "conditions": [{"operator": "contains", "value": "x" * 257}],
            }
        )


def test_metadata_filter_rejects_unknown_operator():
    with pytest.raises(ValidationError):
        AidpMetadataFilterRequest.parse_obj(
            {
                "enabled": True,
                "conditions": [{"operator": "matches", "value": "合同"}],
            }
        )
