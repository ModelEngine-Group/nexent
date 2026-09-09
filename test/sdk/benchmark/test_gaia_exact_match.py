from sdk.benchmark.generic.evaluators.gaia_exact_match import (
    _compare,
    _extract_final_answer,
    _normalize_string,
    _numeric_match,
    _strip_markdown_formatting,
    _try_parse_number,
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


def test_extract_final_answer_handles_empty_and_unmarked_output() -> None:
    assert _extract_final_answer("") == ""
    assert _extract_final_answer("  plain answer  ") == "plain answer"


def test_number_parser_handles_units_fractions_and_invalid_values() -> None:
    assert _try_parse_number("") is None
    assert _try_parse_number("$1,250 kg") == 1250.0
    assert _try_parse_number("3/4") == 0.75
    assert _try_parse_number("1/0") is None
    assert _try_parse_number("not a number") is None


def test_numeric_match_covers_equality_zero_and_invalid_inputs() -> None:
    assert _numeric_match("89,706", "89706.00") is True
    assert _numeric_match("0.0000000001", "0") is True
    assert _numeric_match("not-a-number", "1") is False
    assert _numeric_match("1.1", "1") is False


def test_compare_handles_empty_numeric_and_list_answers() -> None:
    assert _compare("", "") is True
    assert _compare("", "answer") is False
    assert _compare("3/4", "0.75") is True
    assert _compare("1, 2", "1.0, 2.0") is True
    assert _compare("Red, BLUE", "red, blue") is True
    assert _compare("red", "red, blue") is False


def test_evaluator_accepts_output_and_expected_output_variants() -> None:
    assert gaia_exact_match_evaluator(
        input={},
        output={"answer": "FINAL ANSWER: blue"},
        expected_output=["red", "blue"],
    )["value"] == 1.0
    assert gaia_exact_match_evaluator(
        input={},
        output="FINAL ANSWER: 42",
        expected_output="42",
    )["value"] == 1.0
    assert gaia_exact_match_evaluator(
        input={},
        output=None,
        expected_output=None,
    )["value"] == 1.0
