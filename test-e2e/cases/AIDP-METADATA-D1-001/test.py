# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AIDP-METADATA-D1-001: Metadata value validation and batch-result normalization."""
from __future__ import annotations

import pytest

from aidp_ontology_support import ensure_backend_imports

ensure_backend_imports()

pytestmark = [
    pytest.mark.case_id("AIDP-METADATA-D1-001"),
    pytest.mark.stage("D1"),
    pytest.mark.p0,
    pytest.mark.be_ut,
]

from ext_components.aidp.services.aidp_ontology_service import (  # noqa: E402
    METADATA_VALUE_MAX_BYTES,
    metadata_value_error,
    normalize_batch_metadata_result,
)


def test_string_field_accepts_text_and_rejects_other_types():
    assert metadata_value_error("doc_type", "string", "FAQ") is None
    assert metadata_value_error("doc_type", "string", 1) is not None
    assert metadata_value_error("doc_type", "string", True) is not None
    assert metadata_value_error("doc_type", "string", None) is not None
    assert metadata_value_error("doc_type", "string", "x" * 256) is None
    assert metadata_value_error("doc_type", "string", "x" * 257) is not None
    assert metadata_value_error("doc_type", "string", "中" * 86) is not None


def test_number_field_accepts_numbers_only():
    assert metadata_value_error("publish_year", "number", 2026) is None
    assert metadata_value_error("publish_year", "number", 2026.5) is None
    assert metadata_value_error("publish_year", "number", "2026") is not None
    assert metadata_value_error("publish_year", "number", True) is not None
    assert metadata_value_error("publish_year", "number", None) is not None


def test_time_field_is_text_without_format_guessing():
    assert metadata_value_error("effective_date", "time", "2026-01-01") is None
    assert metadata_value_error("effective_date", "time", "unknown format") is None
    assert metadata_value_error("effective_date", "time", "   ") is not None
    assert metadata_value_error("effective_date", "time", 20260101) is not None


def test_unknown_field_type_is_rejected():
    assert metadata_value_error("legacy", "list", ["a"]) is not None


def test_batch_result_normalization_keeps_per_chunk_outcomes():
    normalized = normalize_batch_metadata_result(
        {
            "summary": {"total": 3, "success": 2, "failed": 1},
            "success_list": [{"chunk_id": 1}, {"chunk_id": 2}],
            "failed_list": [{"chunk_id": 3, "message_zh": "模拟失败"}],
        }
    )
    assert normalized == {
        "total": 3,
        "success_count": 2,
        "failed_count": 1,
        "success_list": [{"chunk_id": 1}, {"chunk_id": 2}],
        "failed_list": [{"chunk_id": 3, "message": "模拟失败"}],
    }

    without_summary = normalize_batch_metadata_result(
        {"success_list": [{"chunk_id": 1}], "failed_list": [{"chunk_id": 2, "reason": "bad"}]}
    )
    assert without_summary["total"] == 2
    assert without_summary["failed_list"][0]["message"] == "bad"


def test_batch_result_accepts_results_shape():
    normalized = normalize_batch_metadata_result(
        {
            "data": {
                "results": [
                    {"chunk_id": 1, "success": True},
                    {"chunk_id": 2, "success": False, "message": "bad"},
                    {"chunk_id": 3, "status": "success"},
                    {"chunk_id": 4, "status": "failed", "reason": "nope"},
                ]
            }
        }
    )
    assert normalized["success_list"] == [{"chunk_id": 1}, {"chunk_id": 3}]
    assert normalized["failed_list"] == [
        {"chunk_id": 2, "message": "bad"},
        {"chunk_id": 4, "message": "nope"},
    ]
    assert normalized["total"] == 4


def test_batch_result_accepts_wrapped_and_scalar_failures():
    wrapped = normalize_batch_metadata_result(
        {
            "data": {
                "success_list": [{"chunk_id": "a"}],
                "failed_list": ["b"],
            }
        }
    )
    assert wrapped["success_count"] == 1
    assert wrapped["failed_list"][0] == {"chunk_id": "b", "message": "标注失败"}
    assert METADATA_VALUE_MAX_BYTES == 256
