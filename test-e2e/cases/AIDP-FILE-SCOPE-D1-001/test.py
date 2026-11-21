# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Formal D1 coverage for the conversation AIDP metadata-filter contract."""

import pytest
from contracts.knowledge import ConversationKnowledgeScopeRequest
from pydantic import ValidationError

pytestmark = [pytest.mark.case_id("AIDP-FILE-SCOPE-D1-001"), pytest.mark.stage("D1")]


def _filtered_scope(
    *,
    operator="contains",
    value="合同",
    enabled=True,
    schema_version=3,
    aidp_mode="override",
    kds_ids=None,
):
    aidp = {
        "mode": aidp_mode,
        "kds_ids": ["kb-1"] if kds_ids is None and aidp_mode == "override" else (kds_ids or []),
        "metadata_filter": {
            "enabled": enabled,
            **(
                {"file_name": {"operator": operator, "value": value}}
                if enabled
                else {}
            ),
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
    assert scope.aidp.metadata_filter.file_name is None


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


def test_v3_filter_normalizes_operator_and_value():
    scope = ConversationKnowledgeScopeRequest.model_validate(
        _filtered_scope(operator="starts_with", value="  年度报告  ")
    )

    assert scope.schema_version == 3
    assert scope.aidp.metadata_filter.enabled is True
    assert scope.aidp.metadata_filter.file_name.operator == "starts_with"
    assert scope.aidp.metadata_filter.file_name.value == "年度报告"


def test_v3_disabled_filter_carries_no_condition():
    scope = ConversationKnowledgeScopeRequest.model_validate(
        _filtered_scope(enabled=False, schema_version=3)
    )

    assert scope.aidp.metadata_filter.enabled is False
    assert scope.aidp.metadata_filter.file_name is None


@pytest.mark.parametrize(
    "payload",
    [
        # enabled filter requires schema v3
        _filtered_scope(schema_version=2),
        # enabled filter requires a file-name condition
        {
            "schema_version": 3,
            "aidp": {"mode": "inherit", "metadata_filter": {"enabled": True}},
        },
        # disabled filter must not carry a condition
        {
            "schema_version": 3,
            "aidp": {
                "mode": "inherit",
                "metadata_filter": {
                    "enabled": False,
                    "file_name": {"operator": "contains", "value": "合同"},
                },
            },
        },
        # disabled mode cannot carry a filter
        _filtered_scope(aidp_mode="disabled", kds_ids=[]),
        # unknown operator
        _filtered_scope(operator="equals", value="合同"),
        # blank / oversized value
        _filtered_scope(value="   "),
        _filtered_scope(value="x" * 257),
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
