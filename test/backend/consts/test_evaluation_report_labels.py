"""Unit tests for ``backend.consts.evaluation_report_labels``."""

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
        from backend.consts.evaluation_report_labels import get_report_labels

        labels = get_report_labels(language)
        assert labels[key]

    def test_falls_back_to_zh(self):
        from backend.consts.evaluation_report_labels import get_report_labels

        labels = get_report_labels("fr")
        assert labels["TITLE"] == "Agent 评测报告"

    def test_defaults_to_zh(self):
        from backend.consts.evaluation_report_labels import get_report_labels

        assert get_report_labels()["TITLE"] == "Agent 评测报告"
