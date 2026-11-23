# -*- coding: utf-8 -*-
"""Exact match evaluator with SQuAD-style normalization."""
import re
import string


def _normalize_answer(s: str) -> str:
    """SQuAD-style answer normalization."""
    def lower(text: str) -> str:
        return text.lower()

    def remove_punc(text: str) -> str:
        return text.translate(str.maketrans("", "", string.punctuation))

    def remove_articles(text: str) -> str:
        return re.sub(r"\b(a|an|the)\b", " ", text)

    def white_space_fix(text: str) -> str:
        return " ".join(text.split())

    return white_space_fix(remove_articles(remove_punc(lower(str(s)))))


def exact_match_evaluator(*, input, output, expected_output, metadata=None, **kwargs):
    if isinstance(output, dict):
        pred = output.get("final_answer", "") or output.get("answer", "")
    else:
        pred = str(output) if output else ""

    if isinstance(expected_output, dict):
        gold = expected_output.get("answer", "")
    elif isinstance(expected_output, list):
        gold = expected_output
    else:
        gold = str(expected_output) if expected_output else ""

    norm_pred = _normalize_answer(pred)

    if isinstance(gold, list):
        is_match = any(norm_pred == _normalize_answer(g) for g in gold)
    else:
        is_match = norm_pred == _normalize_answer(gold)

    return {
        "name": "exact_match",
        "value": 1.0 if is_match else 0.0,
    }
