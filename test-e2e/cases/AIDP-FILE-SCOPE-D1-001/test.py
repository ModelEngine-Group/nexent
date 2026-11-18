# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Formal D1 coverage for the conversation AIDP file-scope contract."""

import pytest
from pydantic import ValidationError

from contracts.knowledge import ConversationKnowledgeScopeRequest

pytestmark = [pytest.mark.case_id("AIDP-FILE-SCOPE-D1-001"), pytest.mark.stage("D1")]


def _selected_scope(files, *, schema_version=2, aidp_mode="override", kds_ids=None):
    return {
        "schema_version": schema_version,
        "local": {"mode": "inherit", "knowledge_ids": []},
        "aidp": {
            "mode": aidp_mode,
            "kds_ids": ["kb-1", "kb-2"] if kds_ids is None and aidp_mode == "override" else (kds_ids or []),
            "file_scope": {"mode": "selected", "files": files},
        },
    }


def test_v1_scope_defaults_to_all_files():
    scope = ConversationKnowledgeScopeRequest.model_validate(
        {
            "schema_version": 1,
            "local": {"mode": "inherit", "knowledge_ids": []},
            "aidp": {"mode": "override", "kds_ids": ["kb-1"]},
        }
    )

    assert scope.aidp.file_scope.mode == "all"
    assert scope.aidp.file_scope.files == []


def test_v2_all_mode_has_no_files():
    scope = ConversationKnowledgeScopeRequest.model_validate(
        {
            "schema_version": 2,
            "local": {"mode": "inherit", "knowledge_ids": []},
            "aidp": {
                "mode": "override",
                "kds_ids": ["kb-1"],
                "file_scope": {"mode": "all", "files": []},
            },
        }
    )

    assert scope.aidp.file_scope.mode == "all"
    assert scope.aidp.file_scope.files == []


def test_v2_selected_normalizes_and_deduplicates():
    scope = ConversationKnowledgeScopeRequest.model_validate(
        _selected_scope(
            [
                {"kds_id": " kb-1 ", "file_uuid": " file-a ", "file_name": " 手册.pdf "},
                {"kds_id": "kb-1", "file_uuid": "file-a", "file_name": "手册.pdf"},
                {"kds_id": "kb-2", "file_uuid": "file-b"},
            ]
        )
    )

    files = scope.aidp.file_scope.files
    assert [(item.kds_id, item.file_uuid) for item in files] == [
        ("kb-1", "file-a"),
        ("kb-2", "file-b"),
    ]
    assert files[0].file_name == "手册.pdf"
    assert scope.schema_version == 2
    assert scope.aidp.mode == "override"
    assert scope.aidp.kds_ids == ["kb-1", "kb-2"]


def test_v2_selected_derives_kds_ids_when_omitted():
    scope = ConversationKnowledgeScopeRequest.model_validate(
        {
            "schema_version": 2,
            "aidp": {
                "mode": "inherit",
                "file_scope": {
                    "mode": "selected",
                    "files": [
                        {"kds_id": "kb-2", "file_uuid": "file-b", "file_name": "b.txt"},
                        {"kds_id": "kb-2", "file_uuid": "file-c", "file_name": "c.txt"},
                    ],
                },
            },
        }
    )

    assert scope.aidp.mode == "override"
    assert scope.aidp.kds_ids == ["kb-2"]


@pytest.mark.parametrize(
    "payload",
    [
        _selected_scope([{"kds_id": "kb-1", "file_uuid": "file-a"}], schema_version=1),
        _selected_scope([]),
        {
            "schema_version": 2,
            "aidp": {"mode": "inherit", "file_scope": {"mode": "all", "files": [{"kds_id": "kb-1", "file_uuid": "f"}]}},
        },
        _selected_scope(
            [{"kds_id": "kb-1", "file_uuid": "file-a"}],
            aidp_mode="disabled",
            kds_ids=[],
        ),
        _selected_scope(
            [
                {"kds_id": f"kb-{index}", "file_uuid": "file-a", "file_name": "a.txt"}
                for index in range(11)
            ]
        ),
        _selected_scope(
            [{"kds_id": "kb-1", "file_uuid": f"file-{index}"} for index in range(21)]
        ),
    ],
)
def test_v2_rejects_invalid_combinations(payload):
    with pytest.raises(ValidationError):
        ConversationKnowledgeScopeRequest.model_validate(payload)


def test_unknown_schema_version_is_rejected():
    with pytest.raises(ValidationError):
        ConversationKnowledgeScopeRequest.model_validate(
            {
                "schema_version": 3,
                "aidp": {"mode": "inherit", "file_scope": {"mode": "all", "files": []}},
            }
        )
