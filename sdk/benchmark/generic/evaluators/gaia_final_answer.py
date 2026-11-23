"""Diagnostic evaluator for GAIA final-answer submission behavior."""

from __future__ import annotations

import re
from typing import Any

from .gaia_exact_match import _compare, _extract_final_answer, _normalize_string


_FINAL_MARKER_RE = re.compile(r"FINAL\s*ANSWER\s*:\s*", re.IGNORECASE)


def gaia_final_answer_evaluator(
    *,
    input,
    output,
    expected_output,
    metadata=None,
    **kwargs,
):
    """Report format and submission-loss diagnostics without changing runtime.

    ``gaia_exact_match`` remains the official primary correctness evaluator.
    Add this evaluator after it to distinguish malformed/missing submissions
    from cases where the model considered the gold candidate but submitted a
    different final answer.
    """
    raw_final = _raw_final_answer(output)
    extracted = _extract_final_answer(raw_final)
    marker_count = len(_FINAL_MARKER_RE.findall(raw_final))
    present = bool(extracted and extracted != "(No response received)")
    concise = bool(
        present
        and "\n" not in extracted.strip()
        and len(extracted.strip()) <= 300
    )
    contract_valid = bool(marker_count == 1 and concise)

    gold_answers = _gold_answers(expected_output)
    final_correct = any(_compare(extracted, gold) for gold in gold_answers)
    model_text = _model_generated_text(output)
    candidate_seen = any(
        _contains_candidate(model_text, gold)
        for gold in gold_answers
        if gold.strip()
    )
    submission_loss = bool(candidate_seen and not final_correct)

    return [
        {"name": "gaia_final_answer_present", "value": float(present)},
        {"name": "gaia_final_answer_contract", "value": float(contract_valid)},
        {"name": "gaia_gold_candidate_seen", "value": float(candidate_seen)},
        {"name": "gaia_submission_loss", "value": float(submission_loss)},
    ]


def _raw_final_answer(output: Any) -> str:
    if isinstance(output, dict):
        return str(output.get("final_answer", "") or output.get("answer", "") or "")
    return str(output or "")


def _gold_answers(expected_output: Any) -> list[str]:
    if isinstance(expected_output, dict):
        value = expected_output.get("answer", "")
        return [str(item) for item in value] if isinstance(value, list) else [str(value)]
    if isinstance(expected_output, list):
        return [str(item) for item in expected_output]
    return [str(expected_output or "")]


def _model_generated_text(output: Any) -> str:
    if not isinstance(output, dict):
        return str(output or "")
    parts: list[str] = []
    for step in output.get("steps", []) or []:
        if step.get("step_number") == "final_answer":
            continue
        for field in ("thinking", "deep_thinking", "main_output"):
            value = step.get(field)
            if value:
                parts.append(str(value))
    return "\n".join(parts)


def _contains_candidate(text: str, candidate: str) -> bool:
    haystack = _normalize_string(text)
    needle = _normalize_string(candidate)
    if not needle:
        return False
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", needle):
        haystack = re.sub(r"(?<=\d),(?=\d{3}\b)", "", haystack)
        return re.search(
            rf"(?<![\d.]){re.escape(needle)}(?![\d.])",
            haystack,
        ) is not None
    return needle in haystack
