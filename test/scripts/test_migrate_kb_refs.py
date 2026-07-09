"""
Unit tests for scripts/migrate_kb_refs.py.

Focus: the pure conversion function ``convert_params_to_kb_refs`` — the logic
that maps legacy ``index_names`` or ``adapter_id+kb_ids`` parameter shapes
to the unified ``kb_refs`` schema.

Database-touching behavior (the ``run_migration`` loop) is not exercised
here; it is validated manually via --dry-run in staging.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

# Make the script importable without running the `if __name__ == "__main__"` block
_tests_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_scripts_dir = os.path.join(_tests_root, "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from migrate_kb_refs import convert_params_to_kb_refs  # noqa: E402


# ---------------------------------------------------------------------------
# Already-migrated short-circuit
# ---------------------------------------------------------------------------

class TestAlreadyMigrated:

    def test_with_kb_refs_present_returns_none(self):
        params = {
            "kb_refs": [{"adapter_id": 1, "kb_id": "kb-a", "display_name": "A"}],
            "extra_kept": True,
        }
        kb_refs, reason = convert_params_to_kb_refs(params, local_adapter_id=7)
        assert kb_refs is None
        assert reason == "already_migrated"

    def test_non_dict_params_skipped(self):
        assert convert_params_to_kb_refs("not a dict", 1) == (None, "skipped_empty")
        assert convert_params_to_kb_refs(None, 1) == (None, "skipped_empty")
        assert convert_params_to_kb_refs([], 1) == (None, "skipped_empty")


# ---------------------------------------------------------------------------
# Legacy shape #2: adapter_id + kb_ids (+ optional display names)
# ---------------------------------------------------------------------------

class TestLegacyShape2Conversion:

    def test_adapter_plus_kb_ids_with_display_names(self):
        params = {
            "adapter_id": 42,
            "kb_ids": ["kb-1", "kb-2"],
            "kb_display_names": ["One", "Two"],
        }
        kb_refs, reason = convert_params_to_kb_refs(params, local_adapter_id=99)
        assert reason == "converted_legacy_2"
        assert kb_refs == [
            {"adapter_id": 42, "kb_id": "kb-1", "display_name": "One"},
            {"adapter_id": 42, "kb_id": "kb-2", "display_name": "Two"},
        ]

    def test_adapter_plus_kb_ids_fallback_display_to_kb_id(self):
        params = {"adapter_id": 1, "kb_ids": ["kb-1", "kb-2"]}
        kb_refs, reason = convert_params_to_kb_refs(params, local_adapter_id=7)
        assert reason == "converted_legacy_2"
        assert kb_refs[0]["display_name"] == "kb-1"
        assert kb_refs[1]["display_name"] == "kb-2"

    def test_adapter_plus_kb_ids_partial_display_names(self):
        params = {
            "adapter_id": 1,
            "kb_ids": ["a", "b", "c"],
            "kb_display_names": ["Alpha"],  # only one display name
        }
        kb_refs, _ = convert_params_to_kb_refs(params, None)
        assert kb_refs[0]["display_name"] == "Alpha"
        assert kb_refs[1]["display_name"] == "b"
        assert kb_refs[2]["display_name"] == "c"

    def test_json_encoded_kb_ids_are_parsed(self):
        params = {
            "adapter_id": 1,
            "kb_ids": json.dumps(["kb-x"]),
            "kb_display_names": json.dumps(["KB X"]),
        }
        kb_refs, reason = convert_params_to_kb_refs(params, None)
        assert reason == "converted_legacy_2"
        assert kb_refs == [
            {"adapter_id": 1, "kb_id": "kb-x", "display_name": "KB X"},
        ]

    def test_json_decode_failure_treated_as_empty(self):
        params = {
            "adapter_id": 1,
            "kb_ids": "not-json",
        }
        kb_refs, reason = convert_params_to_kb_refs(params, None)
        assert reason == "skipped_empty"
        assert kb_refs is None

    def test_adapter_plus_empty_kb_ids_returns_skipped(self):
        params = {"adapter_id": 1, "kb_ids": []}
        kb_refs, reason = convert_params_to_kb_refs(params, None)
        assert reason == "skipped_empty"
        assert kb_refs is None

    def test_adapter_with_string_kb_ids_list_input(self):
        # Some legacy rows store kb_ids as a plain list (already a list, not JSON)
        params = {"adapter_id": 7, "kb_ids": ["kb-a"]}
        kb_refs, reason = convert_params_to_kb_refs(params, None)
        assert reason == "converted_legacy_2"
        assert kb_refs[0]["adapter_id"] == 7


# ---------------------------------------------------------------------------
# Legacy shape #1: index_names (requires local adapter id)
# ---------------------------------------------------------------------------

class TestLegacyShape1Conversion:

    def test_index_names_with_local_adapter_resolved(self):
        params = {"index_names": ["idx-1", "idx-2"]}
        kb_refs, reason = convert_params_to_kb_refs(params, local_adapter_id=5)
        assert reason == "converted_legacy_1"
        assert kb_refs == [
            {"adapter_id": 5, "kb_id": "idx-1", "display_name": "idx-1"},
            {"adapter_id": 5, "kb_id": "idx-2", "display_name": "idx-2"},
        ]

    def test_index_names_without_local_adapter_returns_local_no_adapter(self):
        params = {"index_names": ["idx-1"]}
        kb_refs, reason = convert_params_to_kb_refs(params, local_adapter_id=None)
        assert reason == "local_no_adapter"
        assert kb_refs is None

    def test_json_encoded_index_names_are_parsed(self):
        params = {"index_names": json.dumps(["idx-x"])}
        kb_refs, reason = convert_params_to_kb_refs(params, local_adapter_id=3)
        assert reason == "converted_legacy_1"
        assert kb_refs[0]["kb_id"] == "idx-x"

    def test_empty_index_names_skipped(self):
        params = {"index_names": []}
        kb_refs, reason = convert_params_to_kb_refs(params, local_adapter_id=3)
        assert reason == "skipped_empty"
        assert kb_refs is None

    def test_index_names_with_falsy_entries_filtered(self):
        params = {"index_names": ["", None, "valid"]}
        kb_refs, reason = convert_params_to_kb_refs(params, local_adapter_id=1)
        # Falsy entries should be filtered out
        assert reason == "converted_legacy_1"
        assert len(kb_refs) == 1
        assert kb_refs[0]["kb_id"] == "valid"


# ---------------------------------------------------------------------------
# Priority: legacy #2 wins over legacy #1 when both present
# ---------------------------------------------------------------------------

class TestPriorityBetweenShapes:

    def test_adapter_plus_kb_ids_wins_over_index_names(self):
        """If both shapes are present, the explicit adapter_id+kb_ids wins."""
        params = {
            "adapter_id": 99,
            "kb_ids": ["kb-from-legacy-2"],
            "index_names": ["idx-from-legacy-1"],
        }
        kb_refs, reason = convert_params_to_kb_refs(params, local_adapter_id=5)
        assert reason == "converted_legacy_2"
        assert kb_refs[0]["adapter_id"] == 99
        assert kb_refs[0]["kb_id"] == "kb-from-legacy-2"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:

    def test_empty_dict_returns_skipped(self):
        kb_refs, reason = convert_params_to_kb_refs({}, local_adapter_id=1)
        assert reason == "skipped_empty"
        assert kb_refs is None

    def test_unrelated_params_kept_untouched(self):
        """Extra params don't trigger a conversion."""
        params = {
            "top_k": 10,
            "search_mode": "hybrid",
        }
        kb_refs, reason = convert_params_to_kb_refs(params, local_adapter_id=1)
        assert reason == "skipped_empty"

    def test_adapter_id_string_parsed_to_int(self):
        """adapter_id stored as a JSON string should still produce an int in kb_refs."""
        params = {"adapter_id": "7", "kb_ids": ["kb-a"]}
        kb_refs, _ = convert_params_to_kb_refs(params, None)
        assert kb_refs[0]["adapter_id"] == 7
        assert isinstance(kb_refs[0]["adapter_id"], int)
