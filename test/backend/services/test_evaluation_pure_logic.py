"""Unit tests for the ``agent_evaluation_service`` pure-logic helpers.

Targets
-------
* ``_coerce_score`` – JSONB string / dict / numeric normalisation (9 branches)
* ``_coerce_reason`` – reason column coercion to ``{name: text}`` (6 branches)
* ``_coerce_score_dict`` – numeric extraction with ``isfinite`` filter (5 branches)
* ``_is_all_pass`` – threshold alignment, non-numeric skip, DEFAULT_PASS_THRESHOLD fallback (8 branches)
* ``validate_code_evaluator`` – the 4-stage validator (syntax / AST / sandbox-exec / signature)

The test file intentionally uses a fresh per-test import (via ``pytest.importorskip``
and ``importlib.reload``) so that ``sys.modules`` stubbing is isolated and the
target functions are imported *directly* from the real source file – avoiding the
nexent ``sandbox`` / DB / logger dependency chain at runtime.
"""

from __future__ import annotations

import ast
import importlib
import sys
import types
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# 1. Real AST-based safety scanner – mirrors what nexent sandbox does
# ---------------------------------------------------------------------------

# Names that *any* code evaluator is never allowed to reference.
_FORBIDDEN_NAMES = {
    # Filesystem / subprocess
    "open",
    "subprocess",
    "os",
    "sys",
    "pathlib",
    "shutil",
    # Dynamic execution
    "eval",
    "exec",
    "compile",
    "__import__",
    "importlib",
    # Network
    "socket",
    "urllib",
    "requests",
    "httpx",
    # Other risky primitives
    "globals",
    "locals",
    "vars",
    "getattr",
    "setattr",
    "delattr",
}

_ATTRIBUTE_PATHS_BLOCKED = {
    ("os",),
    ("sys",),
    ("subprocess",),
    ("pathlib", "Path"),
    ("shutil",),
    ("__builtins__", "__import__"),
    ("__builtins__", "eval"),
    ("__builtins__", "exec"),
}


def _scan_shell_calls(code: str) -> list[str]:
    """Static AST scan – returns a list of human-readable violation descriptions.

    Mirrors the behaviour of ``nexent.core.agents.sandbox._scan_shell_calls``
    closely enough that the UT decision paths match production semantics.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        # Stage 1 already caught syntax errors, but be defensive.
        return ["<syntax-error>"]

    violations: list[str] = []
    seen_names: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
            if node.id not in seen_names:
                violations.append(f"forbidden identifier '{node.id}'")
                seen_names.add(node.id)
        elif isinstance(node, ast.Attribute):
            # Walk attribute chain left-to-right, collecting dotted-path pieces.
            chain: list[str] = []
            cur: ast.AST = node
            while isinstance(cur, ast.Attribute):
                chain.insert(0, cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                chain.insert(0, cur.id)
                for blocked in _ATTRIBUTE_PATHS_BLOCKED:
                    if tuple(chain[: len(blocked)]) == blocked:
                        desc = "forbidden attribute '" + ".".join(chain) + "'"
                        if desc not in violations:
                            violations.append(desc)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            module = getattr(node, "module", None) or ""
            top = module.split(".")[0]
            if top in _FORBIDDEN_NAMES:
                desc = f"forbidden import '{module or '<star>'}'"
                if desc not in violations:
                    violations.append(desc)
            for alias in getattr(node, "names", []):
                name_top = alias.name.split(".")[0]
                if name_top in _FORBIDDEN_NAMES:
                    desc = f"forbidden import '{alias.name}'"
                    if desc not in violations:
                        violations.append(desc)
    return violations


# ---------------------------------------------------------------------------
# 2. Sys.modules stub chain – mirror test_agent_evaluation_service.py layout
# ---------------------------------------------------------------------------


def _install_sys_modules_stubs(monkeypatch) -> None:
    """Register placeholder modules for every transitive import of the service.

    Each stub module carries attributes for every ``from X import (y, z, ...)``
    call in the service, pre-populated with ``MagicMock`` instances so Python's
    import machinery does not raise ``ImportError: cannot import name``.
    """
    from unittest.mock import MagicMock

    def _mk_mod(name: str, **attrs) -> types.ModuleType:
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules.setdefault(name, m)
        return m

    # ---- nexent namespace --------------------------------------------------
    nexent_mock = types.ModuleType("nexent")
    nexent_core_mock = types.ModuleType("nexent.core")
    nexent_agents_mock = types.ModuleType("nexent.core.agents")
    run_agent_mock = types.ModuleType("nexent.core.agents.run_agent")
    sandbox_mock = types.ModuleType("nexent.core.agents.sandbox")
    nexent_utils_mock = types.ModuleType("nexent.core.utils")

    # Provide the *real* _scan_shell_calls implementation so validate_code_evaluator
    # stage 2 exercises the AST paths.
    sandbox_mock._scan_shell_calls = staticmethod(_scan_shell_calls)

    run_agent_mock.agent_run = lambda *a, **kw: None

    sys.modules.setdefault("nexent", nexent_mock)
    sys.modules.setdefault("nexent.core", nexent_core_mock)
    sys.modules.setdefault("nexent.core.agents", nexent_agents_mock)
    sys.modules.setdefault("nexent.core.agents.run_agent", run_agent_mock)
    sys.modules.setdefault("nexent.core.agents.sandbox", sandbox_mock)
    sys.modules.setdefault("nexent.core.utils", nexent_utils_mock)

    # ---- adapters ----------------------------------------------------------
    _jw_err_cls = type("JiuwenSDKUnavailableError", (Exception,), {})
    _exc_mod = _mk_mod("adapters.exception", JiuwenSDKUnavailableError=_jw_err_cls)
    _jw_mod = _mk_mod("adapters.jiuwen_sdk_adapter", JiuwenSDKAdapter=None)
    sys.modules.setdefault("adapters", types.ModuleType("adapters"))

    # ---- consts ------------------------------------------------------------
    _ErrCode = type(
        "ErrorCode", (), {"COMMON_VALIDATION_ERROR": "COMMON_VALIDATION_ERROR"}
    )
    _mk_mod(
        "consts.error_code",
        ErrorCode=_ErrCode,
    )
    _mk_mod(
        "consts.evaluation_limits",
        DEFAULT_PASS_THRESHOLD=0.5,
        MAX_CONCURRENT_RUNS=5,
        MAX_EVALUATORS_PER_RUN=5,
        MAX_TOTAL_RUNS=1000,
        MAX_TURNS_PER_SESSION=20,
    )
    _mk_mod(
        "consts.evaluation_status",
        EvalCaseStatus=type("ECS", (), {}),
        EvalPassStatus=type("EPS", (), {}),
        EvalRunStatus=type("ERS", (), {}),
        MAX_FAILURE_EXAMPLES=5,
    )

    class _AppException(Exception):
        def __init__(self, code: Any, msg: str = ""):
            super().__init__(msg)
            self.code = code
            self.message = msg

    _mk_mod("consts.exceptions", AppException=_AppException)
    _mk_mod("consts.model", AgentRequest=type("AgentRequest", (), {}))
    sys.modules.setdefault("consts", types.ModuleType("consts"))

    # ---- database – every imported name wired as MagicMock -----------------
    _mk_mod(
        "database.agent_evaluation_db",
        count_active_runs=MagicMock(),
        count_total_runs=MagicMock(),
        create_agent_evaluation=MagicMock(),
        create_agent_evaluation_cases=MagicMock(),
        get_agent_evaluation=MagicMock(),
        get_evaluation_case_scores=MagicMock(),
        hard_delete_agent_evaluation=MagicMock(),
        list_agent_evaluation_cases=MagicMock(),
        list_agent_evaluations_by_agent=MagicMock(),
        update_agent_evaluation_analysis_report=MagicMock(),
        update_agent_evaluation_case_result=MagicMock(),
        update_agent_evaluation_status=MagicMock(),
    )
    _mk_mod("database.client", get_db_session=MagicMock())
    _mk_mod(
        "database.db_models",
        AgentEvaluation=type("AgentEvaluation", (), {}),
        ModelRecord=type("ModelRecord", (), {}),
    )
    _mk_mod(
        "database.evaluation_set_db",
        create_evaluation_set=MagicMock(),
        get_evaluation_set_cases_all=MagicMock(),
        insert_evaluation_set_cases=MagicMock(),
        update_evaluation_set_case_count=MagicMock(),
    )
    _mk_mod(
        "database.evaluator_db",
        get_evaluator=MagicMock(),
    )
    sys.modules.setdefault("database", types.ModuleType("database"))

    # ---- services / utils --------------------------------------------------
    _mk_mod("services.agent_service", prepare_agent_run=MagicMock())
    _mk_mod(
        "services.evaluation_set_service",
        resolve_latest_published_version_no=MagicMock(),
    )
    sys.modules.setdefault("services", types.ModuleType("services"))

    _mk_mod("utils.llm_utils", call_llm_for_system_prompt=MagicMock())
    _mk_mod("utils.prompt_template_utils", get_prompt_template=MagicMock())
    _mk_mod("utils.thread_utils", pool=MagicMock())
    sys.modules.setdefault("utils", types.ModuleType("utils"))


# ---------------------------------------------------------------------------
# 3. Fixture – fresh import of the real agent_evaluation_service module
# ---------------------------------------------------------------------------

SERVICE_PATH = "backend.services.agent_evaluation_service"


@pytest.fixture(scope="module")
def service_module(request):
    """Module-scoped fresh import of the real service – only pure-logic functions are used."""
    # Use the builtin monkeypatch indirectly via a module-level setup/teardown helper.
    import os as _os

    # Ensure backend is on sys.path (mirror the test_agent_evaluation_service convention)
    repo_root = _os.path.abspath(
        _os.path.join(_os.path.dirname(__file__), "..", "..", "..")
    )
    backend_root = _os.path.join(repo_root, "backend")
    for extra in (repo_root, backend_root):
        if extra not in sys.path:
            sys.path.insert(0, extra)

    # Install stubs BEFORE importing the target module.
    import _pytest.monkeypatch as _mp

    mp = _mp.MonkeyPatch()
    try:
        _install_sys_modules_stubs(mp)
        if SERVICE_PATH in sys.modules:
            del sys.modules[SERVICE_PATH]
        mod = importlib.import_module(SERVICE_PATH)
        yield mod
    finally:
        mp.undo()


# ---------------------------------------------------------------------------
# 4. Unit tests – _coerce_score (9 branches)
# ---------------------------------------------------------------------------


class TestCoerceScore:
    def test_none_returns_none(self, service_module):
        assert service_module._coerce_score(None) is None

    def test_dict_passthrough(self, service_module):
        d = {"accuracy": 0.9, "relevance": 0.8}
        assert service_module._coerce_score(d) is d

    def test_int_passthrough(self, service_module):
        assert service_module._coerce_score(42) == 42

    def test_float_passthrough(self, service_module):
        assert service_module._coerce_score(0.75) == 0.75

    def test_empty_string_returns_none(self, service_module):
        assert service_module._coerce_score("") is None
        assert service_module._coerce_score("   ") is None

    def test_json_encoded_dict_string(self, service_module):
        s = '{"accuracy": 0.9, "relevance": 0.8}'
        result = service_module._coerce_score(s)
        assert isinstance(result, dict)
        assert result == {"accuracy": 0.9, "relevance": 0.8}

    def test_json_encoded_number_string(self, service_module):
        # JSON-decoded int
        assert service_module._coerce_score("42") == 42
        # JSON-decoded float
        assert service_module._coerce_score("0.75") == 0.75

    def test_numeric_string_not_json(self, service_module):
        # "0.85" is NOT valid JSON by itself? Actually yes it IS valid JSON number.
        # Let's use a case where JSON fails but float works: trailing + space.
        assert service_module._coerce_score("0.85 ") == 0.85

    def test_invalid_string_returns_none(self, service_module):
        assert service_module._coerce_score("not-a-number") is None
        assert service_module._coerce_score("{invalid json") is None

    def test_unknown_type_returns_none(self, service_module):
        # list falls through to the final `return None` branch
        assert service_module._coerce_score([1, 2, 3]) is None
        # object
        assert service_module._coerce_score(object()) is None


# ---------------------------------------------------------------------------
# 5. Unit tests – _coerce_reason (6 branches)
# ---------------------------------------------------------------------------


class TestCoerceReason:
    def test_none_returns_empty(self, service_module):
        assert service_module._coerce_reason(None) == {}

    def test_empty_string_returns_empty(self, service_module):
        assert service_module._coerce_reason("") == {}
        assert service_module._coerce_reason("   ") == {}

    def test_dict_passthrough_none_values_become_empty_string(self, service_module):
        raw = {"grammar": None, "accuracy": "correct", 123: "numeric-keyed"}
        out = service_module._coerce_reason(raw)
        assert out == {"grammar": "", "accuracy": "correct", "123": "numeric-keyed"}

    def test_json_encoded_dict_string(self, service_module):
        s = '{"accuracy": "All facts correct", "grammar": "One typo"}'
        out = service_module._coerce_reason(s)
        assert out == {"accuracy": "All facts correct", "grammar": "One typo"}

    def test_json_dict_with_none_value(self, service_module):
        s = '{"accuracy": null}'
        out = service_module._coerce_reason(s)
        assert out == {"accuracy": ""}

    def test_plain_string_falls_back_to_reason_key(self, service_module):
        out = service_module._coerce_reason("a plain text reason")
        assert out == {"reason": "a plain text reason"}

    def test_invalid_json_string_uses_reason_key(self, service_module):
        out = service_module._coerce_reason("{not valid json here")
        assert out == {"reason": "{not valid json here"}

    def test_non_string_non_dict_coerced_via_str(self, service_module):
        out = service_module._coerce_reason(12345)
        assert out == {"reason": "12345"}


# ---------------------------------------------------------------------------
# 6. Unit tests – _coerce_score_dict (5 branches)
# ---------------------------------------------------------------------------


class TestCoerceScoreDict:
    def test_dict_of_numbers(self, service_module):
        raw = {"a": 1, "b": 0.5, "c": 0.0}
        out = service_module._coerce_score_dict(raw)
        assert out == {"a": 1.0, "b": 0.5, "c": 0.0}

    def test_dict_filters_non_finite_and_non_numeric(self, service_module):
        raw = {
            "good": 0.8,
            "nan": float("nan"),
            "inf": float("inf"),
            "neg_inf": float("-inf"),
            "str_val": "oops",
            "none": None,
        }
        out = service_module._coerce_score_dict(raw)
        # Only finite numeric entries survive
        assert out == {"good": 0.8}

    def test_standalone_numeric_becomes_score_key(self, service_module):
        assert service_module._coerce_score_dict(0.8) == {"score": 0.8}
        assert service_module._coerce_score_dict(1) == {"score": 1.0}

    def test_non_finite_standalone_yields_empty(self, service_module):
        assert service_module._coerce_score_dict(float("nan")) == {}
        assert service_module._coerce_score_dict(float("inf")) == {}

    def test_none_and_garbage_yield_empty(self, service_module):
        assert service_module._coerce_score_dict(None) == {}
        assert service_module._coerce_score_dict("not-a-score") == {}
        assert service_module._coerce_score_dict(object()) == {}

    def test_json_encoded_dict_string_flow_through(self, service_module):
        raw = '{"accuracy": 0.9}'
        out = service_module._coerce_score_dict(raw)
        assert out == {"accuracy": 0.9}


# ---------------------------------------------------------------------------
# 7. Unit tests – _is_all_pass (8 branches)
# ---------------------------------------------------------------------------


class TestIsAllPass:
    def test_empty_scores_false(self, service_module):
        # Branch 1: not scores → False
        assert service_module._is_all_pass({}) is False

    def test_no_numeric_values_false(self, service_module):
        # Branch 2: all values non-numeric → numeric_seen=False → False
        assert (
            service_module._is_all_pass({"ev1": None, "ev2": "string", "ev3": {}})
            is False
        )

    def test_nan_inf_skipped_as_non_numeric(self, service_module):
        # Non-finite values must NOT count as numeric (isfinite guard)
        assert (
            service_module._is_all_pass({"ev1": float("nan"), "ev2": float("inf")})
            is False
        )

    def test_single_evaluator_passes_at_threshold(self, service_module):
        # Pass *at* threshold – boundary condition (>=)
        assert service_module._is_all_pass({"acc": 0.5}, {"acc": 0.5}) is True

    def test_single_evaluator_passes_above_threshold(self, service_module):
        assert service_module._is_all_pass({"acc": 0.9}, {"acc": 0.5}) is True

    def test_single_evaluator_falls_below_threshold(self, service_module):
        # Branch: score < threshold → low_evaluators recorded → False
        assert service_module._is_all_pass({"acc": 0.49}, {"acc": 0.5}) is False

    def test_mixed_one_fails_causes_overall_false(self, service_module):
        # Branch: multiple evaluators, one low → False
        thresholds = {"acc": 0.5, "rel": 0.6, "style": 0.7}
        scores = {"acc": 0.9, "rel": 0.59, "style": 0.8}  # rel fails by 0.01
        assert service_module._is_all_pass(scores, thresholds) is False

    def test_missing_threshold_uses_default_0_5(self, service_module):
        # Branch: thresholds map missing the name → DEFAULT_PASS_THRESHOLD (0.5)
        # 0.5 at boundary → passes
        assert service_module._is_all_pass({"unknown_ev": 0.5}, {}) is True
        # 0.49 → falls below default → fails
        assert service_module._is_all_pass({"unknown_ev": 0.49}, {}) is False

    def test_non_numeric_values_skipped_but_numeric_present(self, service_module):
        # One valid numeric + some garbage → numeric_seen=True and the garbage ignored
        scores = {
            "ev1": 0.9,
            "ev2": "rejected",
            "ev3": None,
            "ev4": {"structured": True},
        }
        thresholds = {"ev1": 0.5}
        assert service_module._is_all_pass(scores, thresholds) is True

    def test_int_scores_and_int_thresholds_coerce_to_float(self, service_module):
        # Scores/thresholds as ints must work via `float(value) < float(threshold)`
        assert (
            service_module._is_all_pass({"pct": 80}, {"pct": 80}) is True
        )  # at boundary
        assert service_module._is_all_pass({"pct": 79}, {"pct": 80}) is False  # below
        assert service_module._is_all_pass({"pct": 81}, {"pct": 80}) is True  # above

    def test_no_thresholds_map_uses_default_for_all(self, service_module):
        # thresholds=None, 3 evaluators all default 0.5
        assert service_module._is_all_pass({"a": 0.9, "b": 0.5, "c": 0.6}) is True
        # one dips below default
        assert service_module._is_all_pass({"a": 0.9, "b": 0.49, "c": 0.6}) is False


# ---------------------------------------------------------------------------
# 8. Unit tests – validate_code_evaluator (10+ branches: 4 stages, signature)
# ---------------------------------------------------------------------------

_GOOD_EVAL_FULL_SIG = """
def evaluate(query, expected, actual, runtime_events, **kwargs):
    from math import isfinite  # stdlib modules ARE NOT on whitelist → but we DON'T have `math` in ALLOWED_BUILTINS; keep this evaluator pure-python only.
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

    def test_stage1_syntax_error(self, service_module):
        AppExc = service_module.AppException
        with pytest.raises(AppExc) as exc_info:
            service_module.validate_code_evaluator("def evaluate(: pass")
        assert "Code syntax error" in exc_info.value.message
        assert exc_info.value.code == "COMMON_VALIDATION_ERROR"

    # ---- Stage 2 – AST forbidden calls -----------------------------------

    def test_stage2_forbidden_open_call(self, service_module):
        code = """
def evaluate(query, expected, actual, runtime_events, **kwargs):
    f = open("/etc/passwd")
    return {"score": 0.0, "reason": "bad"}
"""
        with pytest.raises(service_module.AppException) as exc_info:
            service_module.validate_code_evaluator(code)
        assert "forbidden operations detected" in exc_info.value.message
        assert "open" in exc_info.value.message

    def test_stage2_forbidden_subprocess_import(self, service_module):
        code = """
import subprocess
def evaluate(query, expected, actual, runtime_events, **kwargs):
    return {"score": 0.0}
"""
        with pytest.raises(service_module.AppException) as exc_info:
            service_module.validate_code_evaluator(code)
        assert (
            "forbidden" in exc_info.value.message
            or "subprocess" in exc_info.value.message
        )

    def test_stage2_forbidden_os_path_attribute(self, service_module):
        code = """
def evaluate(query, expected, actual, runtime_events, **kwargs):
    os.path.join("a", "b")
    return {"score": 0.0}
"""
        with pytest.raises(service_module.AppException):
            service_module.validate_code_evaluator(code)

    def test_stage2_forbidden_eval_call(self, service_module):
        code = """
def evaluate(query, expected, actual, runtime_events, **kwargs):
    return {"score": float(eval("1+1"))}
"""
        with pytest.raises(service_module.AppException):
            service_module.validate_code_evaluator(code)

    def test_stage2_forbidden_dynamic_import(self, service_module):
        code = """
def evaluate(query, expected, actual, runtime_events, **kwargs):
    m = __import__("os")
    return {"score": 0.0}
"""
        with pytest.raises(service_module.AppException):
            service_module.validate_code_evaluator(code)

    # ---- Stage 3 – Sandboxed exec ----------------------------------------

    def test_stage3_nameerror_for_unavailable_module(self, service_module):
        # Forbidden name referenced at **module** top-level → NameError during exec.
        # (Function-body references are NOT exercised in stage 3; only the
        #  top-level statements run – that is intentional.)
        code = """
_frob = re.match  # noqa: F821 – undefined name on purpose
def evaluate(query, expected, actual, runtime_events, **kwargs):
    return {"score": 1.0}
"""
        with pytest.raises(service_module.AppException) as exc_info:
            service_module.validate_code_evaluator(code)
        assert "forbidden or undefined name" in exc_info.value.message

    def test_stage3_generic_exec_exception(self, service_module):
        # Top-level code throws a non-NameError: division-by-zero at module-load.
        code = """
x = 1 / 0
def evaluate(query, expected, actual, runtime_events, **kwargs):
    return {"score": 1.0}
"""
        with pytest.raises(service_module.AppException) as exc_info:
            service_module.validate_code_evaluator(code)
        assert "Code execution failed" in exc_info.value.message

    # ---- Stage 4 – Signature check ---------------------------------------

    def test_stage4_no_evaluate_function(self, service_module):
        code = """
def helper(x):
    return x + 1
"""
        with pytest.raises(service_module.AppException) as exc_info:
            service_module.validate_code_evaluator(code)
        # The real message wraps the signature in single quotes.
        assert "must define" in exc_info.value.message
        assert (
            "query" in exc_info.value.message
            and "runtime_events" in exc_info.value.message
        )

    def test_stage4_evaluate_not_callable(self, service_module):
        code = "evaluate = 42"
        with pytest.raises(service_module.AppException) as exc_info:
            service_module.validate_code_evaluator(code)
        assert "must define" in exc_info.value.message
        assert "evaluate" in exc_info.value.message

    def test_stage4_missing_required_params_no_kwargs(self, service_module):
        # Intentionally only 2 of the 4 required params → strict missing-param error.
        code = """
def evaluate(query, expected):
    return {"score": 1.0, "reason": "missing runtime_events and actual"}
"""
        with pytest.raises(service_module.AppException) as exc_info:
            service_module.validate_code_evaluator(code)
        assert "missing required parameters" in exc_info.value.message
        # Both missing params should be named.
        assert "actual" in exc_info.value.message
        assert "runtime_events" in exc_info.value.message

    def test_stage4_kwargs_fills_all_missing_params(self, service_module):
        # Missing the 4 required params explicitly, but **kwargs is present → OK.
        # No assert on exception – must NOT raise.
        service_module.validate_code_evaluator(_GOOD_EVAL_WITH_KWARGS_ONLY)

    def test_stage4_exact_4_param_signature_passes(self, service_module):
        service_module.validate_code_evaluator(_GOOD_EVAL_EXACT_4_PARAMS)

    def test_stage4_full_signature_passes(self, service_module):
        service_module.validate_code_evaluator(_GOOD_EVAL_FULL_SIG)

    def test_stage4_non_introspectable_callable_allowed(self, service_module):
        # C-level callables (or objects whose __call__ can't be inspected)
        # should skip the strict-param check rather than raising.
        # Simulate by assigning a callable whose `inspect.signature` raises ValueError.
        # We emulate that by injecting a stub that raises before checking params.

        class _BadSigCallable:
            def __call__(self, *a, **kw):
                return {"score": 0.0}

            def __signature__(self):
                raise ValueError("built-in / cannot introspect")

        # We can't easily produce a callable that fails `signature()`.  Instead,
        # verify that if introspection fails we still allow the callable:
        # Use a lambda bound via exec with an attribute descriptor that fools
        # signature.  The simplest robust test is to use a callable class instance
        # where we override signature() by monkey-patching inspect.
        _code = """
class _Eval:
    def __call__(self, *a, **kw):
        return {"score": 1.0, "reason": "ok"}
evaluate = _Eval()
"""
        # The `_Eval()` object has a __call__ but inspect.signature may succeed or
        # fail depending on Python version.  To force the "introspection failed"
        # path we patch inspect.signature locally around the exec.  Do that by
        # calling a custom test helper instead:
        self._run_stage4_introspect_fail_branch(service_module)

    # Helper – can't be a nested method of a pytest class but that's OK, call
    # it as part of the previous test.
    @staticmethod
    def _run_stage4_introspect_fail_branch(service_module):
        import inspect as _inspect

        original_signature = _inspect.signature

        def _bad_signature(*a, **kw):
            # Only reject when called with the test's non-introspectable callable.
            obj = a[0]
            if isinstance(obj, type(lambda: None)) and obj.__name__ == "_proxy":
                raise ValueError("built-in callable: no signature")
            return original_signature(*a, **kw)

        # Build a well-formed code snippet that passes stages 1-3 + produces a
        # lambda we can reliably identify.
        code = """
def _proxy(*a, **kw):
    return {"score": 1.0, "reason": "ok"}
evaluate = _proxy
"""
        from unittest.mock import patch as _patch

        with _patch("inspect.signature", _bad_signature):
            # Should NOT raise – introspection failure is allowed.
            service_module.validate_code_evaluator(code)


# ---------------------------------------------------------------------------
# 9. Sanity tests – ensure DEFAULT_PASS_THRESHOLD == 0.5 (contract anchor)
# ---------------------------------------------------------------------------


def test_default_pass_threshold_is_half(service_module):
    """Contract guard: never silently change DEFAULT_PASS_THRESHOLD in UT env.

    The UT fixtures deliberately set DEFAULT_PASS_THRESHOLD = 0.5 so the
    "no-thresholds-fallback" behaviour is predictable.  This test anchors it.
    """
    assert service_module.DEFAULT_PASS_THRESHOLD == 0.5
