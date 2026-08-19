import pytest

from sdk.benchmark.generic.evaluators import list_evaluators, resolve_evaluators
from sdk.benchmark.generic.evaluators.em_f1 import em_evaluator, f1_evaluator
from sdk.benchmark.generic.evaluators.exact_match import exact_match_evaluator
from sdk.benchmark.generic.evaluators.keyword_match import keyword_match_evaluator
from sdk.benchmark.generic.evaluators.numeric_answer import (
    _extract_final_number,
    numeric_answer_evaluator,
)


def test_evaluator_registry_resolves_known_names_in_requested_order():
    assert resolve_evaluators(["f1", "exact_match"]) == [
        f1_evaluator,
        exact_match_evaluator,
    ]
    assert list_evaluators() == sorted(list_evaluators())


def test_evaluator_registry_rejects_unknown_name():
    with pytest.raises(ValueError, match="Unknown evaluator 'missing'"):
        resolve_evaluators(["missing"])


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("#### 1,234.5", 1234.5),
        ("Therefore, the final answer is: -5", -5.0),
        ("work: 10, result 42", 42.0),
        ("no number", None),
        ("", None),
    ],
)
def test_extract_final_number_supports_benchmark_answer_formats(text, expected):
    assert _extract_final_number(text) == expected


@pytest.mark.parametrize(
    ("output", "expected_output", "expected_score"),
    [
        ({"final_answer": "The answer is 42"}, {"answer": "#### 42"}, 1.0),
        ({"answer": "1,000"}, 1000, 1.0),
        ("The answer is 41", "42", 0.0),
        (None, None, 0.0),
    ],
)
def test_numeric_answer_evaluator_compares_extracted_values(
    output,
    expected_output,
    expected_score,
):
    assert numeric_answer_evaluator(
        input={},
        output=output,
        expected_output=expected_output,
    ) == {"name": "numeric_answer", "value": expected_score}


@pytest.mark.parametrize(
    ("output", "expected_output", "expected_score"),
    [
        ({"final_answer": "The Cat!"}, {"answer": "cat"}, 1.0),
        ({"answer": "Paris"}, ["London", "Paris"], 1.0),
        ("Paris", "London", 0.0),
        (None, None, 1.0),
    ],
)
def test_exact_match_evaluator_normalizes_answers(output, expected_output, expected_score):
    assert exact_match_evaluator(
        input={},
        output=output,
        expected_output=expected_output,
    ) == {"name": "exact_match", "value": expected_score}


def test_em_and_f1_evaluators_handle_multiple_gold_answers_and_partial_overlap():
    assert em_evaluator(
        input={},
        output={"answer": "the cats"},
        expected_output=["dog", "cat"],
    ) == {"name": "em", "value": 1.0}
    assert f1_evaluator(
        input={},
        output={"final_answer": "red blue"},
        expected_output={"answer": ["red green", "yellow"]},
    ) == {"name": "f1", "value": 0.5}


@pytest.mark.parametrize(
    ("output", "expected_output", "expected_score"),
    [
        ({"final_answer": "Alpha and beta"}, {"keywords": ["alpha", "gamma"]}, 0.5),
        ({"answer": "Alpha"}, {"keywords": "alpha"}, 1.0),
        ("Alpha beta", ["alpha", "beta"], 1.0),
        ("anything", {"keywords": []}, 0.0),
    ],
)
def test_keyword_match_evaluator_reports_fractional_coverage(
    output,
    expected_output,
    expected_score,
):
    assert keyword_match_evaluator(
        input={},
        output=output,
        expected_output=expected_output,
    ) == {"name": "keyword_match", "value": expected_score}
