# -*- coding: utf-8 -*-
"""EM and F1 evaluators using SQuAD-style scoring."""
import re
import string


def _normalize_answer(s: str) -> str:
    """SQuAD-style answer normalization with plural handling."""
    def lower(text: str) -> str:
        return text.lower()

    def remove_punc(text: str) -> str:
        return text.translate(str.maketrans("", "", string.punctuation))

    def remove_articles(text: str) -> str:
        return re.sub(r"\b(a|an|the)\b", " ", text)

    def white_space_fix(text: str) -> str:
        return " ".join(text.split())

    def normalize_plurals(text: str) -> str:
        return " ".join(
            word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word
            for word in text.split()
        )

    return normalize_plurals(white_space_fix(remove_articles(remove_punc(str(s)))))


def _f1_score(prediction: str, ground_truth: str) -> float:
    """Token-level F1 score."""
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


def _extract_prediction(output) -> str:
    """Extract prediction string from agent output."""
    if isinstance(output, dict):
        return (
            output.get("final_answer", "")
            or output.get("answer", "")
            or str(output)
        )
    return str(output) if output else ""


def _extract_gold(expected_output) -> list[str]:
    """Extract gold answer(s) from expected_output."""
    if isinstance(expected_output, dict):
        gold = expected_output.get("answer", "")
    elif isinstance(expected_output, list):
        gold = expected_output
    else:
        gold = str(expected_output) if expected_output else ""

    if isinstance(gold, list):
        return [str(g) for g in gold]
    return [str(gold)]


def em_evaluator(*, input, output, expected_output, metadata=None, **kwargs):
    pred = _extract_prediction(output)
    golds = _extract_gold(expected_output)
    norm_pred = _normalize_answer(pred)
    is_match = any(norm_pred == _normalize_answer(g) for g in golds)
    return {"name": "em", "value": 1.0 if is_match else 0.0}


def f1_evaluator(*, input, output, expected_output, metadata=None, **kwargs):
    pred = _extract_prediction(output)
    golds = _extract_gold(expected_output)
    f1 = max((_f1_score(pred, g) for g in golds), default=0.0)
    return {"name": "f1", "value": round(f1, 4)}
