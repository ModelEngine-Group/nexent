# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Formal D1 coverage for the conversation AIDP metadata-filter contract."""

import pytest
from contracts.knowledge import ConversationKnowledgeScopeRequest
from pydantic import ValidationError

pytestmark = [pytest.mark.case_id("AIDP-FILE-SCOPE-D1-001"), pytest.mark.stage("D1")]


def _filtered_scope(
    conditions=None,
    *,
    match="all",
    enabled=True,
    schema_version=3,
    aidp_mode="override",
    kds_ids=None,
):
    if conditions is None:
        conditions = [{"operator": "contains", "value": "合同"}]
    aidp = {
        "mode": aidp_mode,
        "kds_ids": ["kb-1"] if kds_ids is None and aidp_mode == "override" else (kds_ids or []),
        "metadata_filter": {
            "enabled": enabled,
            "match": match,
            **({"conditions": conditions} if enabled else {}),
        },
    }
    return {
        "schema_version": schema_version,
        "local": {"mode": "inherit", "knowledge_ids": []},
        "aidp": aidp,
    }


def test_v1_scope_defaults_to_no_filter():
    scope = ConversationKnowledgeScopeRequest.model_validate(
        {
            "schema_version": 1,
            "local": {"mode": "inherit", "knowledge_ids": []},
            "aidp": {"mode": "override", "kds_ids": ["kb-1"]},
        }
    )

    assert scope.aidp.metadata_filter.enabled is False
    assert scope.aidp.metadata_filter.conditions == []


def test_v2_file_scope_is_ignored_on_read():
    scope = ConversationKnowledgeScopeRequest.model_validate(
        {
            "schema_version": 2,
            "aidp": {
                "mode": "inherit",
                "file_scope": {
                    "mode": "selected",
                    "files": [{"kds_id": "kb-1", "file_uuid": "file-a"}],
                },
            },
        }
    )

    assert scope.aidp.metadata_filter.enabled is False


def test_v3_filter_normalizes_conditions_and_match():
    scope = ConversationKnowledgeScopeRequest.model_validate(
        _filtered_scope(
            [
                {"operator": "starts_with", "value": "  年度报告  "},
                {"operator": "is", "value": "预算.xlsx"},
            ],
            match="any",
        )
    )

    assert scope.schema_version == 3
    assert scope.aidp.metadata_filter.enabled is True
    assert scope.aidp.metadata_filter.match == "any"
    assert [(item.operator, item.value) for item in scope.aidp.metadata_filter.conditions] == [
        ("starts_with", "年度报告"),
        ("is", "预算.xlsx"),
    ]


def test_v3_duplicate_conditions_are_removed():
    scope = ConversationKnowledgeScopeRequest.model_validate(
        _filtered_scope(
            [
                {"operator": "contains", "value": "合同"},
                {"operator": "contains", "value": "合同"},
                {"operator": "contains", "value": "预算"},
            ]
        )
    )

    assert [item.value for item in scope.aidp.metadata_filter.conditions] == [
        "合同",
        "预算",
    ]


def test_legacy_single_file_name_is_folded_into_conditions():
    scope = ConversationKnowledgeScopeRequest.model_validate(
        {
            "schema_version": 3,
            "aidp": {
                "mode": "inherit",
                "metadata_filter": {
                    "enabled": True,
                    "file_name": {"operator": "contains", "value": "合同"},
                },
            },
        }
    )

    assert [
        (item.operator, item.value)
        for item in scope.aidp.metadata_filter.conditions
    ] == [("contains", "合同")]


def test_v3_disabled_filter_carries_no_condition():
    scope = ConversationKnowledgeScopeRequest.model_validate(
        _filtered_scope(enabled=False, schema_version=3)
    )

    assert scope.aidp.metadata_filter.enabled is False
    assert scope.aidp.metadata_filter.conditions == []


@pytest.mark.parametrize(
    "payload",
    [
        # enabled filter requires schema v3
        _filtered_scope(schema_version=2),
        # enabled filter requires at least one condition
        _filtered_scope([], enabled=True),
        # disabled filter must not carry conditions
        {
            "schema_version": 3,
            "aidp": {
                "mode": "inherit",
                "metadata_filter": {
                    "enabled": False,
                    "match": "all",
                    "conditions": [{"operator": "contains", "value": "合同"}],
                },
            },
        },
        # disabled mode cannot carry a filter
        _filtered_scope(aidp_mode="disabled", kds_ids=[]),
        # unknown operator
        _filtered_scope([{"operator": "equals", "value": "合同"}]),
        # blank / oversized value
        _filtered_scope([{"operator": "contains", "value": "   "}]),
        _filtered_scope([{"operator": "contains", "value": "x" * 257}]),
        # invalid match policy
        _filtered_scope(match="either"),
        # more than 20 conditions
        _filtered_scope(
            [{"operator": "contains", "value": f"f{index}"} for index in range(21)]
        ),
    ],
)
def test_filter_rejects_invalid_combinations(payload):
    with pytest.raises(ValidationError):
        ConversationKnowledgeScopeRequest.model_validate(payload)


def test_unknown_schema_version_is_rejected():
    with pytest.raises(ValidationError):
        ConversationKnowledgeScopeRequest.model_validate(
            {
                "schema_version": 4,
                "aidp": {"mode": "inherit"},
            }
        )
