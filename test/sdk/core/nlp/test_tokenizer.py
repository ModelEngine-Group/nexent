import importlib.util
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
MODULE_PATH = REPO_ROOT / "sdk" / "nexent" / "core" / "nlp" / "tokenizer.py"


def _load_tokenizer_module():
    spec = importlib.util.spec_from_file_location("nexent_tokenizer", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the tokenizer module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tokenizer = _load_tokenizer_module()


def test_position_factor_uses_retained_token_positions(monkeypatch):
    retained_tokens = [(f"term{i}", "n") for i in range(10)]
    token_stream = [
        (" ", "x"),
        *retained_tokens[:5],
        ("stop", "x"),
        *retained_tokens[5:],
    ]
    monkeypatch.setattr(tokenizer.pseg, "cut", lambda _: iter(token_stream))
    monkeypatch.setattr(tokenizer.analyse.default_tfidf, "stop_words", {"stop"})

    weights = tokenizer.calculate_term_weights("a deliberately long raw input")

    assert weights["term0"] == pytest.approx(1.0)
    assert weights["term2"] == pytest.approx(1.0)
    assert weights["term3"] == pytest.approx(1 / 1.2)
    assert weights["term6"] == pytest.approx(1 / 1.2)
    assert weights["term7"] == pytest.approx(1.0)
    assert weights["term9"] == pytest.approx(1.0)
