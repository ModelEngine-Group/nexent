# -*- coding: utf-8 -*-
"""Numeric answer evaluator for math benchmarks like GSM8K.

Extracts the final numeric value from the agent's answer and compares
it against the expected numeric answer.
"""
import re


def _extract_final_number(text: str) -> float | None:
    """Extract the final numeric answer from agent output.

    Handles common patterns:
    - "The answer is 42"
    - "#### 42"
    - "Final answer: 42"
    - "42"
    - Numbers with commas: "1,234" -> 1234
    - Negative numbers: "-5"
    """
    if not text:
        return None

    # Try GSM8K-style "#### <number>" pattern first
    gsm_match = re.search(r"####\s*([\d,]+(?:\.\d+)?)", text)
    if gsm_match:
        return float(gsm_match.group(1).replace(",", ""))

    # Try "answer is X" / "answer: X" patterns
    answer_patterns = [
        r"(?:the\s+)?(?:final\s+)?answer\s*(?:is|=|:)\s*(-?[\d,]+(?:\.\d+)?)",
        r"(?:so|therefore|thus)\s*,?\s*(?:the\s+)?(?:final\s+)?answer\s*(?:is|=|:)?\s*(-?[\d,]+(?:\.\d+)?)",
    ]
    for pattern in answer_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return float(m.group(1).replace(",", ""))

    # Fallback: find the last number in the text
    numbers = re.findall(r"-?[\d,]+(?:\.\d+)?", text)
    if numbers:
        return float(numbers[-1].replace(",", ""))

    return None


def numeric_answer_evaluator(*, input, output, expected_output, metadata=None, **kwargs):
    if isinstance(output, dict):
        pred_text = output.get("final_answer", "") or output.get("answer", "") or str(output)
    else:
        pred_text = str(output) if output else ""

    if isinstance(expected_output, dict):
        gold_text = expected_output.get("answer", "")
    elif isinstance(expected_output, (int, float)):
        gold_text = str(expected_output)
    else:
        gold_text = str(expected_output) if expected_output else ""

    pred_num = _extract_final_number(pred_text)
    gold_num = _extract_final_number(gold_text)

    if gold_num is None or pred_num is None:
        return {"name": "numeric_answer", "value": 0.0}

    return {"name": "numeric_answer", "value": 1.0 if abs(pred_num - gold_num) < 1e-6 else 0.0}
