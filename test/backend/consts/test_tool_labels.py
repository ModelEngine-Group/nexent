"""Tests for the built-in tool labels constants module."""

import importlib
import sys

import pytest


def _load_builtin_label_map():
    """Load the real BUILTIN_LABEL_MAP even if consts has been mocked."""
    # Ensure the real consts.tool_labels module is loaded
    for key in list(sys.modules):
        if key.startswith('consts'):
            del sys.modules[key]
    from consts.tool_labels import BUILTIN_LABEL_MAP
    return BUILTIN_LABEL_MAP


class TestBuiltinLabelMap:
    """Verify the BUILTIN_LABEL_MAP integrity."""

    def test_builtin_label_map_is_dict(self):
        """BUILTIN_LABEL_MAP is a non-empty dict."""
        m = _load_builtin_label_map()
        assert isinstance(m, dict)
        assert len(m) > 0

    def test_builtin_label_map_has_expected_categories(self):
        """BUILTIN_LABEL_MAP contains expected tool categories."""
        m = _load_builtin_label_map()
        assert m["mysql_database"] == ["database"]
        assert m["read_file"] == ["file"]
        assert m["tavily_search"] == ["search"]
        assert m["send_email"] == ["email"]
        assert m["terminal"] == ["terminal"]

    def test_builtin_label_map_labels_are_lists(self):
        """Every value in BUILTIN_LABEL_MAP is a list of strings."""
        m = _load_builtin_label_map()
        for tool_name, labels in m.items():
            assert isinstance(tool_name, str)
            assert isinstance(labels, list)
            for label in labels:
                assert isinstance(label, str)

    def test_keep_in_sync_reference_in_docstring(self):
        """Docstring references the correct migration SQL path."""
        for key in list(sys.modules):
            if key.startswith('consts'):
                del sys.modules[key]
        import consts.tool_labels
        doc = consts.tool_labels.__doc__
        assert doc is not None
        assert "deploy/sql/migrations/v2.3.0_0624_add_labels_to_ag_tool_info.sql" in doc
