"""Tests for the centralized tool param value-range constraints.

Covered module: backend/services/tool_param_validation.py

These tests are pure logic — no DB or external service access — so they run
without any mocking.
"""

import pytest

from services.tool_param_validation import (
    CLASS_NAME_TO_TOOL_NAME,
    TOOL_PARAM_CONSTRAINTS,
    validate_tool_params,
)
from consts.exceptions import ValidationError


class TestValidateToolParams:
    """End-to-end constraint application by tool + param."""

    def test_valid_values_pass(self):
        validate_tool_params("dify_search", {
            "top_k": 3, "search_method": "semantic_search",
        })
        validate_tool_params("knowledge_base_search", {
            "top_k": 50, "search_mode": "hybrid",
        })
        validate_tool_params("datamate_search", {
            "top_k": 3, "threshold": 0.2,
            "kb_page": 1, "kb_page_size": 20,
        })

    def test_unknown_tool_skipped(self):
        # No constraint table entry -> any value accepted.
        validate_tool_params("unknown_tool", {"top_k": 999, "garbage": "x"})

    def test_unknown_param_skipped(self):
        # Param not in the table -> ignored.
        validate_tool_params("dify_search", {"unconstrained_param": -5})

    def test_class_name_normalized(self):
        validate_tool_params("KnowledgeBaseSearchTool", {"top_k": 10})

    def test_missing_keys_skipped(self):
        # Missing keys fall back to SDK defaults at construction time.
        validate_tool_params("dify_search", {})


class TestIntRange:
    def test_out_of_range_high(self):
        with pytest.raises(ValidationError, match="dify_search.top_k must be between 1 and 100"):
            validate_tool_params("dify_search", {"top_k": 101})

    def test_out_of_range_low(self):
        with pytest.raises(ValidationError, match="dify_search.top_k must be between 1 and 100"):
            validate_tool_params("dify_search", {"top_k": 0})

    def test_non_int_rejected(self):
        with pytest.raises(ValidationError, match="must be an integer"):
            validate_tool_params("dify_search", {"top_k": "many"})

    def test_bool_rejected(self):
        # bool is an int subclass but is not a valid integer param.
        with pytest.raises(ValidationError, match="must be an integer"):
            validate_tool_params("dify_search", {"top_k": True})

    def test_whole_float_accepted(self):
        # JSON-decoded 3.0 should not be rejected for an int param.
        validate_tool_params("tavily_search", {"max_results": 3.0})


class TestFloatRange:
    def test_out_of_range(self):
        with pytest.raises(ValidationError, match="datamate_search.threshold must be between 0.0 and 1.0"):
            validate_tool_params("datamate_search", {"threshold": 1.5})

    def test_boundary_ok(self):
        validate_tool_params("datamate_search", {"threshold": 0.0})
        validate_tool_params("datamate_search", {"threshold": 1.0})

    def test_negative_below_min(self):
        with pytest.raises(ValidationError, match="must be between 0.0 and 1.0"):
            validate_tool_params("ragflow_search", {"similarity_threshold": -0.1})

    def test_idata_sentinel_legal(self):
        # -10.0 is the SDK default sentinel for "threshold disabled".
        validate_tool_params("idata_search", {"similarity_threshold": -10.0})
        validate_tool_params("idata_search", {"similarity_threshold": 0.5})


class TestPortRange:
    def test_valid(self):
        validate_tool_params("terminal", {"ssh_port": 22})

    def test_out_of_range(self):
        with pytest.raises(ValidationError, match="terminal.ssh_port must be a port between 1 and 65535"):
            validate_tool_params("terminal", {"ssh_port": 70000})

    def test_zero_rejected(self):
        with pytest.raises(ValidationError, match="must be a port between 1 and 65535"):
            validate_tool_params("terminal", {"ssh_port": 0})


class TestEnumValues:
    def test_valid(self):
        validate_tool_params("knowledge_base_search", {"search_mode": "accurate"})

    def test_invalid(self):
        with pytest.raises(
            ValidationError,
            match="knowledge_base_search.search_mode is required; allowed values: hybrid, accurate, semantic",
        ):
            validate_tool_params("knowledge_base_search", {"search_mode": "bogus"})

    def test_dify_search_method(self):
        validate_tool_params("dify_search", {"search_method": "hybrid_search"})
        with pytest.raises(ValidationError, match="dify_search.search_method"):
            validate_tool_params("dify_search", {"search_method": "vector_search"})


class TestNonEmpty:
    def test_empty_string_array(self):
        with pytest.raises(ValidationError, match="ragflow_search.dataset_ids is required"):
            validate_tool_params("ragflow_search", {"dataset_ids": "[]"})

    def test_empty_list(self):
        with pytest.raises(ValidationError, match="ragflow_search.dataset_ids is required"):
            validate_tool_params("ragflow_search", {"dataset_ids": []})

    def test_empty_string(self):
        with pytest.raises(ValidationError, match="ragflow_search.dataset_ids is required"):
            validate_tool_params("ragflow_search", {"dataset_ids": ""})

    def test_whitespace(self):
        with pytest.raises(ValidationError, match="ragflow_search.dataset_ids is required"):
            validate_tool_params("ragflow_search", {"dataset_ids": "   "})

    def test_non_empty_ok(self):
        validate_tool_params("ragflow_search", {"dataset_ids": '["kb1"]'})
        validate_tool_params("ragflow_search", {"dataset_ids": ["kb1"]})

    def test_none_rejected(self):
        # A cleared value (None) on a constrained param is treated as required
        # and must be rejected so it is neither persisted nor passed to the
        # test-panel validation path.
        with pytest.raises(ValidationError, match="ragflow_search.dataset_ids is required"):
            validate_tool_params("ragflow_search", {"dataset_ids": None})
        with pytest.raises(ValidationError, match="dify_search.top_k is required"):
            validate_tool_params("dify_search", {"top_k": None})


class TestConstraintTable:
    def test_class_name_map_is_complete(self):
        # Every constraint table tool has a class-name entry so callers holding
        # only a class_name can still validate.
        for tool_name in TOOL_PARAM_CONSTRAINTS:
            assert tool_name in CLASS_NAME_TO_TOOL_NAME.values(), tool_name

    def test_all_tools_have_ranges(self):
        # Guard against a tool dropping out of the table silently.
        assert "knowledge_base_search" in TOOL_PARAM_CONSTRAINTS
        assert "dify_search" in TOOL_PARAM_CONSTRAINTS
        assert "datamate_search" in TOOL_PARAM_CONSTRAINTS
        assert "haotian_search" in TOOL_PARAM_CONSTRAINTS
        assert "ragflow_search" in TOOL_PARAM_CONSTRAINTS
        assert "idata_search" in TOOL_PARAM_CONSTRAINTS
