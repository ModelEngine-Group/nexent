
"""ACON-style evaluation utilities: exact match and F1 scoring.

Adapted from ACON's experiments/smolagents/eval_utils.py for use with
the nexent agent evaluation pipeline.
"""
import re
import string
from typing import Any


def _normalize_answer(s: str) -> str:
    """SQuAD-style answer normalization with plural handling."""
    def lower(text: str) -> str:
        return text.lower()

    def remove_punc(text: str) -> str:
        return text.translate(str.maketrans('', '', string.punctuation))

    def remove_articles(text: str) -> str:
        return re.sub(r"\b(a|an|the)\b", " ", text)

    def white_space_fix(text: str) -> str:
        return " ".join(text.split())

    def normalize_plurals(text: str) -> str:
        """Strip trailing 's' from words longer than 3 chars to unify singular/plural."""
        return " ".join(
            word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word
            for word in text.split()
        )

    return normalize_plurals(white_space_fix(remove_articles(remove_punc(lower(s)))))


def _f1_score(prediction: str, ground_truth: str) -> float:
    pred_tokens = _normalize_answer(prediction).split()
    gold_tokens = _normalize_answer(ground_truth).split()
    if len(pred_tokens) == 0 and len(gold_tokens) == 0:
        return 1.0
    if len(pred_tokens) == 0 or len(gold_tokens) == 0:
        return 0.0
    common: dict[str, int] = {}
    for t in pred_tokens:
        common[t] = common.get(t, 0) + 1
    overlap = 0
    for t in gold_tokens:
        if common.get(t, 0) > 0:
            overlap += 1
            common[t] -= 1
    if overlap == 0:
        return 0.0
    precision = overlap / len(pred_tokens)
    recall = overlap / len(gold_tokens)
    return 2 * precision * recall / (precision + recall)


def exact_match(pred: Any, gold: Any) -> bool:
    """SQuAD-style normalized exact match."""
    def norm_one(x: Any) -> str:
        if isinstance(x, (list, tuple)):
            x = x[0] if x else ""
        return _normalize_answer(str(x))

    p = norm_one(pred)
    if isinstance(gold, (list, tuple)):
        return max(p == norm_one(g) for g in gold)
    return p == norm_one(gold)


def f1_max(pred: Any, gold: Any) -> float:
    """Max F1 over gold answer variants."""
    p = str(pred) if pred is not None else ""
    if isinstance(gold, (list, tuple)):
        return max((_f1_score(p, str(g)) for g in gold), default=0.0)
    return _f1_score(p, str(gold))
