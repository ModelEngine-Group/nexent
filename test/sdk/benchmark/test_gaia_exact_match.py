from sdk.benchmark.generic.evaluators.gaia_exact_match import (
    _extract_final_answer,
    _normalize_string,
    _strip_markdown_formatting,
    gaia_exact_match_evaluator,
)


def test_extract_final_answer_uses_last_marker() -> None:
    output = """Initial conclusion.

Final answer: green, red

After checking the opposite faces, that conclusion was wrong.

FINAL ANSWER: green, white
"""

    assert _extract_final_answer(output) == "green, white"


def test_evaluator_accepts_corrected_answer_after_earlier_marker() -> None:
    output = {
        "final_answer": """Step 8 - Final answer
Final answer: green, red

The remaining edge is actually the white-green edge.

```
FINAL ANSWER: green, white
```
"""
    }

    result = gaia_exact_match_evaluator(
        input={},
        output=output,
        expected_output={"answer": "green, white"},
    )

    assert result == {"name": "gaia_exact_match", "value": 1.0}


def test_extract_final_answer_preserves_single_marker_behavior() -> None:
    assert _extract_final_answer("Reasoning.\nFINAL ANSWER: **Right.**") == "Right."


def test_strip_markdown_formatting_preserves_mixed_markers() -> None:
    assert _strip_markdown_formatting("  *_ answer _*  ") == "answer"
    assert _strip_markdown_formatting("``` answer ```") == "answer"


def test_normalization_handles_long_trailing_whitespace_without_regex_backtracking() -> None:
    assert _normalize_string("Answer" + " " * 100_000 + ".") == "answer"


def test_extract_final_answer_uses_last_natural_language_marker() -> None:
    output = "The answer is red. After verification, the final answer is: blue."

    assert _extract_final_answer(output) == "blue."


def test_evaluator_ignores_sentence_final_period_symmetrically() -> None:
    output = {"final_answer": "FINAL ANSWER: THE SEAGULL GLIDED PEACEFULLY TO MY CHAIR"}

    result = gaia_exact_match_evaluator(
        input={},
        output=output,
        expected_output={"answer": "The seagull glided peacefully to my chair."},
    )

    assert result == {"name": "gaia_exact_match", "value": 1.0}


def test_evaluator_preserves_word_boundary_differences() -> None:
    output = {"final_answer": "FINAL ANSWER: The sea gull glided peacefully to my chair."}

    result = gaia_exact_match_evaluator(
        input={},
        output=output,
        expected_output={"answer": "The seagull glided peacefully to my chair."},
    )

    assert result == {"name": "gaia_exact_match", "value": 0.0}
