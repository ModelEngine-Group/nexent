# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Unit tests for evaluation scoring and code validation."""

import inspect

import pytest

from contracts.constants.constants import DEFAULT_PASS_THRESHOLD
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from management.services.evaluation.scoring import _is_all_pass, validate_code_evaluator


class TestIsAllPass:
    def test_empty_scores_false(self):
        # Branch 1: not scores → False
        assert _is_all_pass({}) is False

    def test_no_numeric_values_false(self):
        # Branch 2: all values non-numeric → numeric_seen=False → False
        assert (
            _is_all_pass({"ev1": None, "ev2": "string", "ev3": {}})
            is False
        )

    def test_nan_inf_skipped_as_non_numeric(self):
        # Non-finite values must NOT count as numeric (isfinite guard)
        assert (
            _is_all_pass({"ev1": float("nan"), "ev2": float("inf")})
            is False
        )

    def test_single_evaluator_passes_at_threshold(self):
        # Pass *at* threshold – boundary condition (>=)
        assert _is_all_pass({"acc": 0.5}, {"acc": 0.5}) is True

    def test_single_evaluator_passes_above_threshold(self):
        assert _is_all_pass({"acc": 0.9}, {"acc": 0.5}) is True

    def test_single_evaluator_falls_below_threshold(self):
        # Branch: score < threshold → low_evaluators recorded → False
        assert _is_all_pass({"acc": 0.49}, {"acc": 0.5}) is False

    def test_mixed_one_fails_causes_overall_false(self):
        # Branch: multiple evaluators, one low → False
        thresholds = {"acc": 0.5, "rel": 0.6, "style": 0.7}
        scores = {"acc": 0.9, "rel": 0.59, "style": 0.8}  # rel fails by 0.01
        assert _is_all_pass(scores, thresholds) is False

    def test_missing_threshold_uses_default_0_5(self):
        # Branch: thresholds map missing the name → DEFAULT_PASS_THRESHOLD (0.5)
        # 0.5 at boundary → passes
        assert _is_all_pass({"unknown_ev": 0.5}, {}) is True
        # 0.49 → falls below default → fails
        assert _is_all_pass({"unknown_ev": 0.49}, {}) is False

    def test_non_numeric_values_skipped_but_numeric_present(self):
        # One valid numeric + some garbage → numeric_seen=True and the garbage ignored
        scores = {
            "ev1": 0.9,
            "ev2": "rejected",
            "ev3": None,
            "ev4": {"structured": True},
        }
        thresholds = {"ev1": 0.5}
        assert _is_all_pass(scores, thresholds) is True

    def test_int_scores_and_int_thresholds_coerce_to_float(self):
        # Scores/thresholds as ints must work via `float(value) < float(threshold)`
        assert (
            _is_all_pass({"pct": 80}, {"pct": 80}) is True
        )  # at boundary
        assert _is_all_pass({"pct": 79}, {"pct": 80}) is False  # below
        assert _is_all_pass({"pct": 81}, {"pct": 80}) is True  # above

    def test_no_thresholds_map_uses_default_for_all(self):
        # thresholds=None, 3 evaluators all default 0.5
        assert _is_all_pass({"a": 0.9, "b": 0.5, "c": 0.6}) is True
        # one dips below default
        assert _is_all_pass({"a": 0.9, "b": 0.49, "c": 0.6}) is False


# ---------------------------------------------------------------------------
# 5. Unit tests – validate_code_evaluator (10+ branches: 4 stages, signature)
# ---------------------------------------------------------------------------

_GOOD_EVAL_FULL_SIG = """
def evaluate(query, expected, actual, runtime_events, **kwargs):
    if not actual:
        return {"score": 0.0, "reason": "empty answer"}
    score = 1.0 if expected == actual else 0.0
    return {"score": float(score), "reason": "strict equality"}
"""

_GOOD_EVAL_WITH_KWARGS_ONLY = """
def evaluate(**kwargs):
    actual = kwargs.get("actual", "")
    return {"score": float(bool(actual)), "reason": "any non-empty string ok"}
"""

_GOOD_EVAL_EXACT_4_PARAMS = """
def evaluate(query, expected, actual, runtime_events):
    return {"score": 1.0, "reason": "ok"}
"""


class TestValidateCodeEvaluator:
    # ---- Stage 1 – SyntaxError -------------------------------------------

    def test_stage1_syntax_error(self):
        with pytest.raises(AppException) as exc_info:
            validate_code_evaluator("def evaluate(: pass")
        assert "Code syntax error" in exc_info.value.message
        assert exc_info.value.error_code == ErrorCode.COMMON_VALIDATION_ERROR

    # ---- Stage 2 – AST forbidden calls -----------------------------------

    def test_stage2_forbidden_dynamic_import(self):
        code = """
def evaluate(query, expected, actual, runtime_events, **kwargs):
    m = __import__("os")
    return {"score": 0.0}
"""
        with pytest.raises(AppException):
            validate_code_evaluator(code)

    # ---- Stage 3 – Sandboxed exec ----------------------------------------

    @pytest.mark.parametrize("name", ["open", "eval", "os"])
    def test_unavailable_builtins_and_modules_are_rejected(self, name):
        with pytest.raises(AppException, match="forbidden or undefined name"):
            validate_code_evaluator(f"{name}\n{_GOOD_EVAL_EXACT_4_PARAMS}")

    def test_sandbox_cannot_import_modules(self):
        with pytest.raises(AppException, match="Code execution failed"):
            validate_code_evaluator(f"import math\n{_GOOD_EVAL_EXACT_4_PARAMS}")

    def test_stage3_nameerror_for_unavailable_module(self):
        # Forbidden name referenced at **module** top-level → NameError during exec.
        # (Function-body references are NOT exercised in stage 3; only the
        #  top-level statements run – that is intentional.)
        code = """
_frob = re.match  # noqa: F821 – undefined name on purpose
def evaluate(query, expected, actual, runtime_events, **kwargs):
    return {"score": 1.0}
"""
        with pytest.raises(AppException) as exc_info:
            validate_code_evaluator(code)
        assert "forbidden or undefined name" in exc_info.value.message

    def test_stage3_generic_exec_exception(self):
        # Top-level code throws a non-NameError: division-by-zero at module-load.
        code = """
x = 1 / 0
def evaluate(query, expected, actual, runtime_events, **kwargs):
    return {"score": 1.0}
"""
        with pytest.raises(AppException) as exc_info:
            validate_code_evaluator(code)
        assert "Code execution failed" in exc_info.value.message

    # ---- Stage 4 – Signature check ---------------------------------------

    def test_stage4_no_evaluate_function(self):
        code = """
def helper(x):
    return x + 1
"""
        with pytest.raises(AppException) as exc_info:
            validate_code_evaluator(code)
        # The real message wraps the signature in single quotes.
        assert "must define" in exc_info.value.message
        assert (
            "query" in exc_info.value.message
            and "runtime_events" in exc_info.value.message
        )

    def test_stage4_evaluate_not_callable(self):
        code = "evaluate = 42"
        with pytest.raises(AppException) as exc_info:
            validate_code_evaluator(code)
        assert "must define" in exc_info.value.message
        assert "evaluate" in exc_info.value.message

    def test_stage4_missing_required_params_no_kwargs(self):
        # Intentionally only 2 of the 4 required params → strict missing-param error.
        code = """
def evaluate(query, expected):
    return {"score": 1.0, "reason": "missing runtime_events and actual"}
"""
        with pytest.raises(AppException) as exc_info:
            validate_code_evaluator(code)
        assert "missing required parameters" in exc_info.value.message
        # Both missing params should be named.
        assert "actual" in exc_info.value.message
        assert "runtime_events" in exc_info.value.message

    def test_stage4_kwargs_fills_all_missing_params(self):
        # Missing the 4 required params explicitly, but **kwargs is present → OK.
        # No assert on exception – must NOT raise.
        validate_code_evaluator(_GOOD_EVAL_WITH_KWARGS_ONLY)

    def test_stage4_exact_4_param_signature_passes(self):
        validate_code_evaluator(_GOOD_EVAL_EXACT_4_PARAMS)

    def test_stage4_full_signature_passes(self):
        validate_code_evaluator(_GOOD_EVAL_FULL_SIG)

    def test_stage4_non_introspectable_callable_allowed(self, monkeypatch):
        signature = inspect.signature

        def reject_evaluator_signature(callable_object, *args, **kwargs):
            if getattr(callable_object, "__name__", None) == "evaluate":
                raise ValueError("Signature unavailable")
            return signature(callable_object, *args, **kwargs)

        monkeypatch.setattr(inspect, "signature", reject_evaluator_signature)
        validate_code_evaluator(_GOOD_EVAL_EXACT_4_PARAMS)


# ---------------------------------------------------------------------------
# 6. Sanity tests – ensure DEFAULT_PASS_THRESHOLD == 0.5 (contract anchor)
# ---------------------------------------------------------------------------


def test_default_pass_threshold_is_half():
    """Keep the default threshold aligned with the fallback assertions."""
    assert DEFAULT_PASS_THRESHOLD == 0.5
