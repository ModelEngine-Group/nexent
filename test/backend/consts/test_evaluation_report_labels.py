# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Unit tests for ``contracts.constants.evaluation``."""

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND = str(_REPO_ROOT / "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


class TestGetReportLabels:
    @pytest.mark.parametrize("language,key", [("zh", "TITLE"), ("en", "TITLE")])
    def test_returns_labels_for_language(self, language, key):
        from contracts.constants.evaluation import get_report_labels

        labels = get_report_labels(language)
        assert labels[key]

    def test_falls_back_to_zh(self):
        from contracts.constants.evaluation import get_report_labels

        labels = get_report_labels("fr")
        assert labels["TITLE"] == "Agent 评测报告"

    def test_defaults_to_zh(self):
        from contracts.constants.evaluation import get_report_labels

        assert get_report_labels()["TITLE"] == "Agent 评测报告"
