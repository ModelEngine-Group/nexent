from sdk.benchmark.generic.evaluators.gaia_final_answer import (
    gaia_final_answer_evaluator,
)


def _scores(output, gold):
    results = gaia_final_answer_evaluator(
        input={},
        output=output,
        expected_output={"answer": gold},
    )
    return {result["name"]: result["value"] for result in results}


def test_valid_final_answer_contract_has_no_submission_loss():
    scores = _scores(
        {
            "final_answer": "FINAL ANSWER: 89,706",
            "steps": [{"step_number": 1, "thinking": "The value is 89,706."}],
        },
        "89706",
    )

    assert scores == {
        "gaia_final_answer_present": 1.0,
        "gaia_final_answer_contract": 1.0,
        "gaia_gold_candidate_seen": 1.0,
        "gaia_submission_loss": 0.0,
    }


def test_candidate_seen_but_wrong_submission_is_diagnosed():
    scores = _scores(
        {
            "final_answer": "FINAL ANSWER: 41",
            "steps": [{"step_number": 1, "thinking": "Evidence says 42."}],
        },
        "42",
    )

    assert scores["gaia_final_answer_contract"] == 1.0
    assert scores["gaia_gold_candidate_seen"] == 1.0
    assert scores["gaia_submission_loss"] == 1.0


def test_missing_marker_and_multiline_explanation_fail_contract():
    scores = _scores(
        {"final_answer": "42\nBecause the source says so.", "steps": []},
        "42",
    )

    assert scores["gaia_final_answer_present"] == 1.0
    assert scores["gaia_final_answer_contract"] == 0.0
