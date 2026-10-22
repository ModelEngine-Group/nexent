# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Tests for the built-in tool labels constants module."""

import importlib
from pathlib import Path
import sys

import pytest


def _load_builtin_label_map():
    """Load the real BUILTIN_LABEL_MAP even if consts has been mocked."""
    # Ensure the real contracts.constants.constants module is loaded
    for key in list(sys.modules):
        if key.startswith('consts'):
            del sys.modules[key]
    from contracts.constants.constants import BUILTIN_LABEL_MAP
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

    def test_keep_in_sync_reference_in_comments(self):
        """The consolidated comments retain the correct migration SQL path."""
        for key in list(sys.modules):
            if key.startswith('consts'):
                del sys.modules[key]
        import contracts.constants.constants
        doc = Path(contracts.constants.constants.__file__).read_text(encoding="utf-8")
        assert doc is not None
        assert "deploy/sql/migrations/v2.3_merged_migrations.sql" in doc
