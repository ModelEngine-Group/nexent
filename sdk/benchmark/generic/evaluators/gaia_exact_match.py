# -*- coding: utf-8 -*-
"""GAIA-specific exact match evaluator.

Handles GAIA answer normalization requirements:
- Extracts answer from "FINAL ANSWER: ..." agent output
- Numeric comparison: strips commas/currency/units, compares as floats
- Comma-separated lists: element-wise comparison (order-sensitive)
- String comparison: case-insensitive, whitespace-normalized

Reference: GAIA official evaluation uses exact string match after normalization.
This evaluator is more robust than the generic SQuAD exact_match for GAIA
because SQuAD normalization strips ALL punctuation (including decimal points),
which breaks numeric answers like "89706.00".
"""
import re


# ---------------------------------------------------------------------------
# Answer extraction
# ---------------------------------------------------------------------------

def _strip_markdown_formatting(s: str) -> str:
    """Strip markdown emphasis or code markers from an extracted answer.

    Agents sometimes wrap the FINAL ANSWER marker or the answer itself in
    markdown formatting (e.g. "**FINAL ANSWER:** answer" or "FINAL ANSWER: **answer**").
    The regex captures the trailing markers as part of the answer - strip them here.
    """
    value = s.strip()

    marker_length = 0
    if value.startswith("`"):
        marker_length = min(3, len(value) - len(value.lstrip("`")))
    elif value.startswith(("_", "*")):
        marker_length = min(3, len(value) - len(value.lstrip("_*")))
    if marker_length:
        value = value[marker_length:].lstrip()

    value = value.rstrip()
    marker_length = 0
    if value.endswith("`"):
        marker_length = min(3, len(value) - len(value.rstrip("`")))
    elif value.endswith(("_", "*")):
        marker_length = min(3, len(value) - len(value.rstrip("_*")))
    if marker_length:
        value = value[:-marker_length].rstrip()

    return value


def _extract_final_answer(text: str) -> str:
    """Extract the answer from agent output containing 'FINAL ANSWER: ...'.

    Tries multiple patterns in priority order. Falls back to raw text
    stripping if no pattern matches.
    """
    if not text:
        return ""

    # Priority 1: "FINAL ANSWER: <answer>" (case-insensitive).
    # The GAIA constraint prompt requires this exact format. Agents may mention
    # the marker more than once while self-correcting, so extract the text after
    # the last occurrence instead of letting a DOTALL capture start at the first.
    patterns = [
        r"FINAL\s*ANSWER\s*:\s*",
        r"The\s*(?:final\s*)?answer\s+is\s*:?\s*",
    ]
    for pat in patterns:
        matches = list(re.finditer(pat, text.strip(), re.IGNORECASE))
        if matches:
            answer = text.strip()[matches[-1].end():].strip()
            # Strip markdown bold/italic markers captured by the regex
            answer = _strip_markdown_formatting(answer)
            return answer

    return text.strip()


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------

_CURRENCY_RE = re.compile(r"^[\$€£¥₹]")
_UNIT_RE = re.compile(
    r"\b\s*(km|mi|miles?|hours?|hrs?|minutes?|mins?|seconds?|secs?|"
    r"kg|lbs?|pounds?|grams?|g|mg|ml|oz|liters?|L|gal|"
    r"km/h|mph|m/s|ft|cm|mm|m|°[CF]|%|percent)\s*[.,]?\s*$",
    re.IGNORECASE,
)


def _try_parse_number(s: str) -> float | None:
    """Try to parse a string as a number. Returns None on failure."""
    s = s.strip()
    if not s:
        return None

    # Strip currency prefix
    s = _CURRENCY_RE.sub("", s)
    # Strip trailing units
    s = _UNIT_RE.sub("", s)
    s = s.strip()

    # Remove thousand-separator commas: "89,706" -> "89706"
    # Only strip commas that look like thousand separators (digit,digit{3})
    s = re.sub(r"(\d),(\d{3})", r"\1\2", s)

    # Handle fraction notation "3/4" -> evaluate
    if re.fullmatch(r"\d+\s*/\s*\d+", s):
        num, den = s.split("/")
        den_val = float(den.strip())
        if den_val == 0:
            return None
        return float(num.strip()) / den_val

    try:
        return float(s)
    except ValueError:
        return None


def _is_numeric(s: str) -> bool:
    return _try_parse_number(s) is not None


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def _normalize_whitespace(s: str) -> str:
    """Collapse whitespace, strip leading/trailing."""
    return " ".join(s.split())


def _normalize_string(s: str) -> str:
    """Normalize a non-numeric answer for comparison."""
    s = s.strip()
    s = _normalize_whitespace(s)
    s = s.lower()
    # Normalize smart quotes and dashes
    s = s.replace("\u2018", "'").replace("\u2019", "'")
    s = s.replace("\u201c", '"').replace("\u201d", '"')
    s = s.replace("\u2013", "-").replace("\u2014", "-")
    # GAIA answers may include or omit a sentence-final period. Normalize it
    # symmetrically for predictions and gold answers without changing internal
    # whitespace or word boundaries (for example, "seagull" != "sea gull").
    if s.endswith("."):
        s = s[:-1].rstrip()
    return s


def _split_comma_list(s: str) -> list[str]:
    """Split a comma-separated string into trimmed elements."""
    return [elem.strip() for elem in s.split(",") if elem.strip()]


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def _numeric_match(pred: str, gold: str) -> bool:
    """Compare two numeric strings with tolerance."""
    p = _try_parse_number(pred)
    g = _try_parse_number(gold)
    if p is None or g is None:
        return False
    # Exact float equality first (handles "89706" == "89706.00")
    if p == g:
        return True
    # Small tolerance for floating-point rounding only (1e-9 relative)
    if g == 0:
        return abs(p) < 1e-9
    return abs(p - g) / max(abs(g), 1e-9) < 1e-9


def _compare(pred_raw: str, gold_raw: str) -> bool:
    """Multi-strategy comparison: numeric > list > string."""
    pred = pred_raw.strip()
    gold = gold_raw.strip()

    if not pred or not gold:
        return pred == gold

    # Strategy 1: Both are single numbers
    if _is_numeric(pred) and _is_numeric(gold):
        return _numeric_match(pred, gold)

    # Strategy 2: Both look like comma-separated lists
    if "," in gold:
        gold_parts = _split_comma_list(gold)
        pred_parts = _split_comma_list(pred)

        if len(pred_parts) == len(gold_parts):
            # 2a: All gold elements are numeric -> numeric element-wise
            if all(_is_numeric(g) for g in gold_parts):
                return all(
                    _numeric_match(p, g)
                    for p, g in zip(pred_parts, gold_parts)
                )
            # 2b: String element-wise (order-sensitive, case-insensitive)
            return all(
                _normalize_string(p) == _normalize_string(g)
                for p, g in zip(pred_parts, gold_parts)
            )

    # Strategy 3: Normalized string comparison
    return _normalize_string(pred) == _normalize_string(gold)


# ---------------------------------------------------------------------------
# Evaluator entry point
# ---------------------------------------------------------------------------

def gaia_exact_match_evaluator(*, input, output, expected_output, metadata=None, **kwargs):
    """GAIA exact match evaluator.

    Extracts the agent's final answer, then compares against the gold answer
    using the most appropriate strategy (numeric, list, or string).

    Returns:
        dict with name="gaia_exact_match", value=1.0 or 0.0
    """
    # --- Extract prediction ---
    if isinstance(output, dict):
        raw_pred = output.get("final_answer", "") or output.get("answer", "")
    else:
        raw_pred = str(output) if output else ""

    pred = _extract_final_answer(raw_pred)

    # --- Extract gold ---
    if isinstance(expected_output, dict):
        gold = expected_output.get("answer", "")
    elif isinstance(expected_output, list):
        # Multiple acceptable answers: match any
        gold_list = [str(g) for g in expected_output]
        is_match = any(_compare(pred, g) for g in gold_list)
        return {"name": "gaia_exact_match", "value": 1.0 if is_match else 0.0}
    else:
        gold = str(expected_output) if expected_output else ""

    is_match = _compare(pred, gold)
    return {"name": "gaia_exact_match", "value": 1.0 if is_match else 0.0}
