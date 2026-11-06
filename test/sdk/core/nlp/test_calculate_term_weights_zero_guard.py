# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Guards calculate_term_weights against a zero total_weight (#3813)."""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]  # nexent repo root
TOKENIZER = ROOT / "sdk" / "nexent" / "core" / "nlp" / "tokenizer.py"


def _load_tokenizer():
    for name in (
        "nexent",
        "nexent.core",
        "nexent.core.nlp",
    ):
        if name not in sys.modules:
            mod = types.ModuleType(name)
            mod.__path__ = []
            sys.modules[name] = mod

    spec = importlib.util.spec_from_file_location("nexent.core.nlp.tokenizer", TOKENIZER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["nexent.core.nlp.tokenizer"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def tokenizer():
    return _load_tokenizer()


def test_all_stop_words_returns_empty_without_division_error(tokenizer, mocker):
    analyse = mocker.patch.object(tokenizer, "analyse")
    pseg = mocker.patch.object(tokenizer, "pseg")
    analyse.default_tfidf.stop_words = {"的", "是", "在"}
    pseg.cut.return_value = [("的", "u"), ("是", "v"), ("在", "p")]
    assert tokenizer.calculate_term_weights("的 是 在") == {}


def test_empty_tokens_returns_empty(tokenizer, mocker):
    analyse = mocker.patch.object(tokenizer, "analyse")
    pseg = mocker.patch.object(tokenizer, "pseg")
    analyse.default_tfidf.stop_words = set()
    pseg.cut.return_value = [("   ", "x"), ("\t", "x")]
    assert tokenizer.calculate_term_weights("   \t") == {}


def test_whitespace_only_returns_empty(tokenizer, mocker):
    analyse = mocker.patch.object(tokenizer, "analyse")
    pseg = mocker.patch.object(tokenizer, "pseg")
    analyse.default_tfidf.stop_words = set()
    pseg.cut.return_value = []
    assert tokenizer.calculate_term_weights("") == {}


def test_zero_pos_weight_noun_returns_empty_without_division_error(tokenizer, mocker):
    """Regression: a kept token whose POS weight is 0 still yields total_weight==0."""
    analyse = mocker.patch.object(tokenizer, "analyse")
    pseg = mocker.patch.object(tokenizer, "pseg")
    analyse.default_tfidf.stop_words = set()
    pseg.cut.return_value = [("widget", "n")]
    mocker.patch.object(tokenizer, "POS_WEIGHTS", {"n": 0.0})
    assert tokenizer.calculate_term_weights("widget") == {}
