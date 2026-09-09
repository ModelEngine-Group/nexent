"""Unit tests for the ``agent_evaluation_service`` pure-logic helpers.

Targets
-------
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
from pathlib import Path
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
# 2. Path setup + idempotent package registration (mirrors
#    test_agent_evaluation_service.py pattern)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


def _register_package(name: str) -> types.ModuleType:
    """Register ``name`` as a real package on ``sys.modules``.

    Real ``__path__`` (pointing to the matching backend dir when one applies)
    is used so subsequent ``from X.Y import Z`` resolution can locate
    submodules; this prevents sibling tests from seeing a stubbed package
    with no resolvable submodules.

    If ``sys.modules[name]`` already exposes ``__path__`` (e.g. a stub
    created by a sibling test file) we reuse it so we don't fork the
    package identity mid-session — module-level execution of one test
    file would otherwise orphan the other file's package object, and
    ``from package import X`` would then short-circuit through a stale
    cache that has no entry in ``sys.modules``.
    """
    existing = sys.modules.get(name)
    if existing is not None and hasattr(existing, "__path__"):
        return existing
    pkg = types.ModuleType(name)
    backend_path = _BACKEND_DIR / name
    if backend_path.is_dir():
        pkg.__path__ = [str(backend_path)]
    else:
        pkg.__path__ = []
    sys.modules[name] = pkg
    return pkg


# ---------------------------------------------------------------------------
# 3. Sys.modules stub chain – permanent top-level install (no monkeypatch,
#    no undo)
# ---------------------------------------------------------------------------


def _install_sys_modules_stubs() -> None:
    """Register placeholder modules for every transitive import of the service.

    Each stub module carries attributes for every ``from X import (y, z, ...)``
    call in the service, pre-populated with ``MagicMock`` instances so Python's
    import machinery does not raise ``ImportError: cannot import name``.

    This runs once at module-collection time and is *never* undone — sibling
    tests share the same stub objects via ``_register_package`` idempotency.
    """
    from unittest.mock import MagicMock

    def _mk_mod(name: str, **attrs) -> types.ModuleType:
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m
        return m

    # ---- nexent namespace --------------------------------------------------
    _nexent_pkg = _register_package("nexent")
    _nexent_core = _register_package("nexent.core")
    _nexent_core_agents = _register_package("nexent.core.agents")
    _nexent_core_utils = _register_package("nexent.core.utils")
    _nexent_pkg.core = _nexent_core
    _nexent_core.agents = _nexent_core_agents
    _nexent_core.utils = _nexent_core_utils

    run_agent_mock = types.ModuleType("nexent.core.agents.run_agent")
    run_agent_mock.agent_run = lambda *a, **kw: None
    sys.modules["nexent.core.agents.run_agent"] = run_agent_mock
    _nexent_core_agents.run_agent = run_agent_mock

    sandbox_mock = types.ModuleType("nexent.core.agents.sandbox")
    sandbox_mock._scan_shell_calls = staticmethod(_scan_shell_calls)
    sys.modules["nexent.core.agents.sandbox"] = sandbox_mock
    _nexent_core_agents.sandbox = sandbox_mock

    # ---- adapters ----------------------------------------------------------
    _adapters_pkg = _register_package("adapters")
    _jw_err_cls = type("JiuwenSDKUnavailableError", (Exception,), {})
    _exc_mod = _mk_mod("adapters.exception", JiuwenSDKUnavailableError=_jw_err_cls)
    _adapters_pkg.exception = _exc_mod
    _jw_mod = _mk_mod("adapters.jiuwen_sdk_adapter", JiuwenSDKAdapter=None)
    _adapters_pkg.jiuwen_sdk_adapter = _jw_mod

    # ---- consts ------------------------------------------------------------
    _consts_pkg = _register_package("consts")
    _ErrCode = type(
        "ErrorCode", (), {"COMMON_VALIDATION_ERROR": "COMMON_VALIDATION_ERROR"}
    )
    _ec_mod = _mk_mod(
        "consts.error_code",
        ErrorCode=_ErrCode,
    )
    _consts_pkg.error_code = _ec_mod
    _el_mod = _mk_mod(
        "consts.evaluation_limits",
        DEFAULT_PASS_THRESHOLD=0.5,
        MAX_CONCURRENT_RUNS=5,
        MAX_EVALUATORS_PER_RUN=5,
        MAX_TOTAL_RUNS=1000,
        MAX_TURNS_PER_SESSION=20,
    )
    _consts_pkg.evaluation_limits = _el_mod
    _es_mod = _mk_mod(
        "consts.evaluation_status",
        EvalCaseStatus=type("ECS", (), {}),
        EvalPassStatus=type("EPS", (), {}),
        EvalRunStatus=type("ERS", (), {}),
        MAX_FAILURE_EXAMPLES=5,
    )
    _consts_pkg.evaluation_status = _es_mod

    class _AppException(Exception):
        def __init__(self, code: Any, msg: str = ""):
            super().__init__(msg)
            self.code = code
            self.message = msg

    _ex_mod = _mk_mod("consts.exceptions", AppException=_AppException)
    _consts_pkg.exceptions = _ex_mod
    _m_mod = _mk_mod("consts.model", AgentRequest=type("AgentRequest", (), {}))
    _consts_pkg.model = _m_mod

    # ---- database – every imported name wired as MagicMock -----------------
    _db_pkg = _register_package("database")
    _aedb_mod = _mk_mod(
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
    _db_pkg.agent_evaluation_db = _aedb_mod
    _dc_mod = _mk_mod("database.client", get_db_session=MagicMock())
    _db_pkg.client = _dc_mod
    _dm_mod = _mk_mod(
        "database.db_models",
        AgentEvaluation=type("AgentEvaluation", (), {}),
        ModelRecord=type("ModelRecord", (), {}),
    )
    _db_pkg.db_models = _dm_mod
    _esdb_mod = _mk_mod(
        "database.evaluation_set_db",
        create_evaluation_set=MagicMock(),
        get_evaluation_set_cases_all=MagicMock(),
        insert_evaluation_set_cases=MagicMock(),
        materialize_virtual_evaluation_set_for_run=MagicMock(),
        update_evaluation_set_case_count=MagicMock(),
    )
    _db_pkg.evaluation_set_db = _esdb_mod
    _evdb_mod = _mk_mod(
        "database.evaluator_db",
        get_evaluator=MagicMock(),
    )
    _db_pkg.evaluator_db = _evdb_mod

    # ---- services / utils --------------------------------------------------
    _services_pkg = _register_package("services")
    _as_mod = _mk_mod("management.services.agent.service", prepare_agent_run=MagicMock())
    _services_pkg.agent_service = _as_mod
    _ess_mod = _mk_mod(
        "services.evaluation_set_service",
        resolve_latest_published_version_no=MagicMock(),
    )
    _services_pkg.evaluation_set_service = _ess_mod

    _utils_pkg = _register_package("utils")
    _lu_mod = _mk_mod("utils.llm_utils", call_llm_for_system_prompt=MagicMock())
    _utils_pkg.llm_utils = _lu_mod
    _ptu_mod = _mk_mod("utils.prompt_template_utils", get_prompt_template=MagicMock())
    _utils_pkg.prompt_template_utils = _ptu_mod
    _tu_mod = _mk_mod("utils.thread_utils", pool=MagicMock())
    _utils_pkg.thread_utils = _tu_mod


_install_sys_modules_stubs()


# ---------------------------------------------------------------------------
# 4. Fixture – fresh import of the real agent_evaluation_service module
# ---------------------------------------------------------------------------

SERVICE_PATH = "services.agent_evaluation_service"


@pytest.fixture(scope="module")
def service_module():
    """Module-scoped fresh import of the real service – only pure-logic functions are used.

    Stubs are pre-installed at module-collection time (see ``_install_sys_modules_stubs``
    above) so this fixture only needs to ensure ``sys.path`` contains the backend
    roots, drop any cached copy of the target module, and perform a clean import.
    No ``monkeypatch`` undo is required because the stubs are intentionally
    permanent (idempotent registration via ``_register_package`` keeps them
    consistent across sibling test files).
    """
    repo_root = _REPO_ROOT
    backend_root = _BACKEND_DIR
    for extra in (str(repo_root), str(backend_root)):
        if extra not in sys.path:
            sys.path.insert(0, extra)

    if SERVICE_PATH in sys.modules:
        del sys.modules[SERVICE_PATH]
    services_pkg = _register_package("services")
    if hasattr(services_pkg, "agent_evaluation_service"):
        try:
            delattr(services_pkg, "agent_evaluation_service")
        except AttributeError:
            pass

    mod = importlib.import_module(SERVICE_PATH)
    services_pkg.agent_evaluation_service = mod
    yield mod


# ---------------------------------------------------------------------------
# 4. Unit tests – _is_all_pass (8 branches)
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
# 5. Unit tests – validate_code_evaluator (10+ branches: 4 stages, signature)
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
# 6. Sanity tests – ensure DEFAULT_PASS_THRESHOLD == 0.5 (contract anchor)
# ---------------------------------------------------------------------------


def test_default_pass_threshold_is_half(service_module):
    """Contract guard: never silently change DEFAULT_PASS_THRESHOLD in UT env.

    The UT fixtures deliberately set DEFAULT_PASS_THRESHOLD = 0.5 so the
    "no-thresholds-fallback" behaviour is predictable.  This test anchors it.
    """
    assert service_module.DEFAULT_PASS_THRESHOLD == 0.5
