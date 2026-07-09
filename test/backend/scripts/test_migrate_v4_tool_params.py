"""
Unit tests for V4 tool params migration and rollback scripts.

Tests the pure migrate_params() and rollback_params() functions
without requiring database access.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make scripts importable
_scripts_dir = Path(__file__).resolve().parents[3] / "scripts"
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from migrate_v4_tool_params import migrate_params
from rollback_v4_tool_params import rollback_params


# ---------------------------------------------------------------------------
# migrate_params tests
# ---------------------------------------------------------------------------


class TestMigrateKbIdToKnowledgeBaseId:
    """kb_refs[].kb_id -> kb_refs[].knowledge_base_id"""

    def test_migrate_kb_id_to_knowledge_base_id(self):
        legacy = json.dumps({
            "kb_refs": [
                {"adapter_id": 1, "kb_id": "kb-123", "display_name": "Test KB"},
            ],
            "other": "value",
        })

        result_str, modified = migrate_params(legacy)
        result = json.loads(result_str)

        assert modified is True
        assert "knowledge_base_id" in result["kb_refs"][0]
        assert result["kb_refs"][0]["knowledge_base_id"] == "kb-123"
        assert "kb_id" not in result["kb_refs"][0]
        assert result["kb_refs"][0]["adapter_id"] == 1
        assert result["kb_refs"][0]["display_name"] == "Test KB"
        assert result["other"] == "value"


class TestMigrateSearchModeToRetrievalModel:
    """Flat search_mode keys -> nested retrieval_model"""

    def test_migrate_search_mode_to_retrieval_model(self):
        legacy = json.dumps({
            "search_mode": "hybrid",
            "search_mode_enabled": True,
            "top_k": 5,
            "score_threshold": 0.3,
            "reranking_enable": True,
            "other": "value",
        })

        result_str, modified = migrate_params(legacy)
        result = json.loads(result_str)

        assert modified is True
        assert "retrieval_model" in result
        rm = result["retrieval_model"]
        assert rm["search_method"] == "hybrid"
        assert rm["search_method_enabled"] is True
        assert rm["top_k"] == 5
        assert rm["score_threshold"] == 0.3
        assert rm["reranking_enable"] is True

        # Flat keys removed
        assert "search_mode" not in result
        assert "search_mode_enabled" not in result
        assert "top_k" not in result
        assert "score_threshold" not in result
        assert "reranking_enable" not in result

        # Other fields preserved
        assert result["other"] == "value"


class TestMigrateBothFields:
    """Both kb_refs and search_mode migration in one params"""

    def test_migrate_both_fields(self):
        legacy = json.dumps({
            "kb_refs": [
                {"adapter_id": 1, "kb_id": "kb-123", "display_name": "Test KB"},
            ],
            "search_mode": "hybrid",
            "search_mode_enabled": True,
            "top_k": 5,
            "score_threshold": 0.3,
            "reranking_enable": True,
        })

        result_str, modified = migrate_params(legacy)
        result = json.loads(result_str)

        assert modified is True
        # kb_refs migrated
        assert "knowledge_base_id" in result["kb_refs"][0]
        assert "kb_id" not in result["kb_refs"][0]
        # retrieval_model created
        assert "retrieval_model" in result
        assert result["retrieval_model"]["search_method"] == "hybrid"
        # No legacy flat keys
        assert "search_mode" not in result


class TestMigratePreservesOtherFields:
    """Unrelated fields are not touched"""

    def test_migrate_preserves_other_fields(self):
        legacy = json.dumps({
            "kb_refs": [
                {"adapter_id": 1, "kb_id": "kb-123", "display_name": "Test KB"},
            ],
            "custom_setting": "keep_me",
            "nested_obj": {"inner": "value"},
            "number_field": 42,
        })

        result_str, modified = migrate_params(legacy)
        result = json.loads(result_str)

        assert modified is True
        assert result["custom_setting"] == "keep_me"
        assert result["nested_obj"] == {"inner": "value"}
        assert result["number_field"] == 42


class TestMigrateIdempotency:
    """Running migrate twice produces the same result"""

    def test_migrate_idempotency(self):
        legacy = json.dumps({
            "kb_refs": [
                {"adapter_id": 1, "kb_id": "kb-123", "display_name": "Test KB"},
            ],
            "search_mode": "hybrid",
            "search_mode_enabled": True,
            "top_k": 5,
            "score_threshold": 0.3,
            "reranking_enable": True,
        })

        first_str, first_modified = migrate_params(legacy)
        second_str, second_modified = migrate_params(first_str)

        assert first_modified is True
        assert second_modified is False
        assert first_str == second_str


class TestNoKbRefsNoSearchMode:
    """Params without these fields are unchanged"""

    def test_no_kb_refs_no_search_mode(self):
        params = json.dumps({
            "tool_name": "some_tool",
            "max_retries": 3,
        })

        result_str, modified = migrate_params(params)
        result = json.loads(result_str)

        assert modified is False
        assert result == {"tool_name": "some_tool", "max_retries": 3}


class TestEmptyKbRefs:
    """Empty kb_refs array handled correctly"""

    def test_empty_kb_refs(self):
        params = json.dumps({
            "kb_refs": [],
            "search_mode": "vector",
            "top_k": 10,
        })

        result_str, modified = migrate_params(params)
        result = json.loads(result_str)

        assert modified is True
        assert result["kb_refs"] == []
        assert "retrieval_model" in result
        assert result["retrieval_model"]["search_method"] == "vector"
        assert result["retrieval_model"]["top_k"] == 10


class TestMigrateEmptyString:
    """Empty JSON object"""

    def test_migrate_empty_string(self):
        params = json.dumps({})

        result_str, modified = migrate_params(params)
        result = json.loads(result_str)

        assert modified is False
        assert result == {}


class TestMigrateInvalidJson:
    """Invalid JSON returns unchanged with was_modified=False"""

    def test_migrate_invalid_json(self):
        result_str, modified = migrate_params("not valid json {{{")

        assert modified is False
        assert result_str == "not valid json {{{"


class TestMultipleKbRefs:
    """Multiple entries in kb_refs array"""

    def test_multiple_kb_refs(self):
        legacy = json.dumps({
            "kb_refs": [
                {"adapter_id": 1, "kb_id": "kb-001", "display_name": "KB One"},
                {"adapter_id": 1, "kb_id": "kb-002", "display_name": "KB Two"},
                {"adapter_id": 2, "kb_id": "kb-003", "display_name": "KB Three"},
            ],
        })

        result_str, modified = migrate_params(legacy)
        result = json.loads(result_str)

        assert modified is True
        assert len(result["kb_refs"]) == 3
        for ref in result["kb_refs"]:
            assert "knowledge_base_id" in ref
            assert "kb_id" not in ref
        assert result["kb_refs"][0]["knowledge_base_id"] == "kb-001"
        assert result["kb_refs"][1]["knowledge_base_id"] == "kb-002"
        assert result["kb_refs"][2]["knowledge_base_id"] == "kb-003"


class TestMigratePartialSearchKeys:
    """Only some flat search keys present"""

    def test_migrate_partial_search_keys(self):
        params = json.dumps({
            "search_mode": "keyword",
            "top_k": 20,
        })

        result_str, modified = migrate_params(params)
        result = json.loads(result_str)

        assert modified is True
        rm = result["retrieval_model"]
        assert rm["search_method"] == "keyword"
        assert rm["top_k"] == 20
        assert "search_method_enabled" not in rm
        assert "score_threshold" not in rm
        assert "reranking_enable" not in rm


class TestMigrateAlreadyHasRetrievalModel:
    """If retrieval_model already exists, do not overwrite"""

    def test_migrate_already_has_retrieval_model(self):
        params = json.dumps({
            "search_mode": "hybrid",
            "retrieval_model": {"search_method": "vector", "top_k": 10},
        })

        result_str, modified = migrate_params(params)
        result = json.loads(result_str)

        # search_mode is present but retrieval_model already exists,
        # so the migration should NOT touch retrieval_model
        assert modified is False
        assert result["retrieval_model"] == {"search_method": "vector", "top_k": 10}
        assert result["search_mode"] == "hybrid"


# ---------------------------------------------------------------------------
# rollback_params tests
# ---------------------------------------------------------------------------


class TestRollbackBasic:
    """Basic rollback from V4 to legacy"""

    def test_rollback_basic(self):
        v4 = json.dumps({
            "kb_refs": [
                {"adapter_id": 1, "knowledge_base_id": "kb-123", "display_name": "Test KB"},
            ],
            "retrieval_model": {
                "search_method": "hybrid",
                "search_method_enabled": True,
                "top_k": 5,
                "score_threshold": 0.3,
                "reranking_enable": True,
            },
            "other": "value",
        })

        result_str, modified = rollback_params(v4)
        result = json.loads(result_str)

        assert modified is True
        # kb_refs rolled back
        assert "kb_id" in result["kb_refs"][0]
        assert result["kb_refs"][0]["kb_id"] == "kb-123"
        assert "knowledge_base_id" not in result["kb_refs"][0]
        # Flat keys restored
        assert result["search_mode"] == "hybrid"
        assert result["search_mode_enabled"] is True
        assert result["top_k"] == 5
        assert result["score_threshold"] == 0.3
        assert result["reranking_enable"] is True
        # retrieval_model removed
        assert "retrieval_model" not in result
        # Other preserved
        assert result["other"] == "value"


class TestRollbackIdempotency:
    """Running rollback twice produces the same result"""

    def test_rollback_idempotency(self):
        v4 = json.dumps({
            "kb_refs": [
                {"adapter_id": 1, "knowledge_base_id": "kb-123", "display_name": "Test KB"},
            ],
            "retrieval_model": {
                "search_method": "hybrid",
                "top_k": 5,
            },
        })

        first_str, first_modified = rollback_params(v4)
        second_str, second_modified = rollback_params(first_str)

        assert first_modified is True
        assert second_modified is False
        assert first_str == second_str


class TestRollbackEmptyRetrievalModel:
    """Empty retrieval_model dict is removed"""

    def test_rollback_empty_retrieval_model(self):
        v4 = json.dumps({
            "retrieval_model": {},
            "other": "data",
        })

        result_str, modified = rollback_params(v4)
        result = json.loads(result_str)

        # Empty dict is falsy, so the condition `if isinstance(...) and retrieval_model`
        # evaluates to False -> not modified
        assert modified is False


class TestRollbackNoMatchingFields:
    """Params without V4 fields are unchanged"""

    def test_rollback_no_matching_fields(self):
        params = json.dumps({
            "tool_name": "some_tool",
            "kb_refs": [
                {"adapter_id": 1, "kb_id": "kb-123"},
            ],
        })

        result_str, modified = rollback_params(params)
        result = json.loads(result_str)

        assert modified is False
        assert result["kb_refs"][0]["kb_id"] == "kb-123"


# ---------------------------------------------------------------------------
# Roundtrip tests
# ---------------------------------------------------------------------------


class TestRoundtrip:
    """migrate then rollback returns original"""

    def test_roundtrip(self):
        original_dict = {
            "kb_refs": [
                {"adapter_id": 1, "kb_id": "kb-123", "display_name": "Test KB"},
                {"adapter_id": 2, "kb_id": "kb-456", "display_name": "KB Two"},
            ],
            "search_mode": "hybrid",
            "search_mode_enabled": True,
            "top_k": 5,
            "score_threshold": 0.3,
            "reranking_enable": True,
            "other_field": "untouched",
        }
        original_str = json.dumps(original_dict, ensure_ascii=False)

        # Migrate
        v4_str, mig_modified = migrate_params(original_str)
        assert mig_modified is True

        # Rollback
        legacy_str, rb_modified = rollback_params(v4_str)
        assert rb_modified is True

        result = json.loads(legacy_str)

        # Verify roundtrip
        assert result["kb_refs"] == original_dict["kb_refs"]
        assert result["search_mode"] == original_dict["search_mode"]
        assert result["search_mode_enabled"] == original_dict["search_mode_enabled"]
        assert result["top_k"] == original_dict["top_k"]
        assert result["score_threshold"] == original_dict["score_threshold"]
        assert result["reranking_enable"] == original_dict["reranking_enable"]
        assert result["other_field"] == original_dict["other_field"]
        assert "retrieval_model" not in result
        assert "knowledge_base_id" not in result["kb_refs"][0]
