"""Unit tests for ``services.evaluator_service``.

The module is loaded with ``spec_from_file_location`` while the
``consts`` / ``database`` / ``services`` / ``utils`` packages are stubbed
at ``sys.modules`` level.  All DB helpers, LLM call, agent-profile utils
and prompt templates are mocked; only the service logic itself runs.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(_REPO_ROOT), str(_REPO_ROOT / "backend")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

MODULE_UNDER_TEST = "services.evaluator_service"

_DB_IMPL_NAMES = [
    "create_evaluator",
    "delete_evaluator",
    "delete_evaluator_version",
    "get_evaluator",
    "list_evaluator_versions",
    "list_evaluators",
    "publish_evaluator",
    "restore_evaluator_version",
    "update_evaluator",
]


def _register_package(name: str) -> types.ModuleType:
    existing = sys.modules.get(name)
    if existing is not None and hasattr(existing, "__path__"):
        return existing
    pkg = types.ModuleType(name)
    backend_path = _REPO_ROOT / "backend" / name
    pkg.__path__ = [str(backend_path)] if backend_path.is_dir() else []
    sys.modules[name] = pkg
    return pkg


def _mk_mod(name: str, **attrs) -> types.ModuleType:
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


def _install_stubs():
    class _ErrorCode:
        COMMON_VALIDATION_ERROR = "000502"
        COMMON_RESOURCE_NOT_FOUND = "000501"

    class _AppException(Exception):
        def __init__(self, code, message: str = "", extra=None):
            super().__init__(message)
            self.code = code
            self.message = message
            self.extra = extra

    _consts = _register_package("consts")
    _consts.error_code = _mk_mod("consts.error_code", ErrorCode=_ErrorCode)
    _consts.exceptions = _mk_mod("consts.exceptions", AppException=_AppException)

    _db = _register_package("database")
    _db.evaluator_db = _mk_mod(
        "database.evaluator_db", **{n: MagicMock(name=n) for n in _DB_IMPL_NAMES}
    )

    _svc = _register_package("services")
    _svc.agent_evaluation_service = _mk_mod(
        "services.agent_evaluation_service",
        validate_code_evaluator=MagicMock(name="validate_code_evaluator"),
    )

    _utils = _register_package("utils")
    _utils.agent_profile_utils = _mk_mod(
        "utils.agent_profile_utils",
        fetch_agent_profile=MagicMock(name="fetch_agent_profile"),
        format_agent_profile_context=MagicMock(name="format_agent_profile_context"),
    )
    _utils.llm_utils = _mk_mod(
        "utils.llm_utils", call_llm_for_system_prompt=MagicMock(name="call_llm_for_system_prompt")
    )
    _utils.prompt_template_utils = _mk_mod(
        "utils.prompt_template_utils", get_prompt_template=MagicMock(name="get_prompt_template")
    )
    return _ErrorCode, _AppException


_ERROR_CODE, _APP_EXC = _install_stubs()


@pytest.fixture
def bundle():
    """Fresh mocks + fresh import of the module for every test."""
    import importlib.util as _ilu

    db_impls = {n: MagicMock(name=n) for n in _DB_IMPL_NAMES}
    code_val = MagicMock(name="validate_code_evaluator")
    profile = MagicMock(name="fetch_agent_profile")
    fmt_profile = MagicMock(name="format_agent_profile_context")
    llm = MagicMock(name="call_llm_for_system_prompt")
    tmpl = MagicMock(name="get_prompt_template")

    for n, m in db_impls.items():
        setattr(sys.modules["database.evaluator_db"], n, m)
    sys.modules["services.agent_evaluation_service"].validate_code_evaluator = code_val
    sys.modules["utils.agent_profile_utils"].fetch_agent_profile = profile
    sys.modules["utils.agent_profile_utils"].format_agent_profile_context = fmt_profile
    sys.modules["utils.llm_utils"].call_llm_for_system_prompt = llm
    sys.modules["utils.prompt_template_utils"].get_prompt_template = tmpl

    if MODULE_UNDER_TEST in sys.modules:
        del sys.modules[MODULE_UNDER_TEST]
    svc_pkg = _register_package("services")
    if hasattr(svc_pkg, "evaluator_service"):
        delattr(svc_pkg, "evaluator_service")

    src = _REPO_ROOT / "backend" / "services" / "evaluator_service.py"
    spec = _ilu.spec_from_file_location(MODULE_UNDER_TEST, str(src))
    assert spec is not None and spec.loader is not None, f"cannot locate {src}"
    mod = _ilu.module_from_spec(spec)
    sys.modules[MODULE_UNDER_TEST] = mod
    spec.loader.exec_module(mod)
    svc_pkg.evaluator_service = mod

    class _Bundle:
        pass

    b = _Bundle()
    b.mod = mod
    b.db = db_impls
    b.code_val = code_val
    b.profile = profile
    b.fmt_profile = fmt_profile
    b.llm = llm
    b.tmpl = tmpl
    b.ErrorCode = _ERROR_CODE
    b.AppException = _APP_EXC
    return b


def _exc_code(bundle, fn, *args, **kwargs):
    with pytest.raises(bundle.AppException) as exc:
        fn(*args, **kwargs)
    return exc.value.code


# ---------------------------------------------------------------------------
# 1. Thin CRUD wrappers
# ---------------------------------------------------------------------------


class TestCRUDWrappers:
    def test_list(self, bundle):
        bundle.db["list_evaluators"].return_value = [{"id": 1}]
        out = bundle.mod.list_evaluators_impl("t1", source="custom", evaluator_type="llm", status="draft")
        assert out == [{"id": 1}]
        bundle.db["list_evaluators"].assert_called_once_with(
            tenant_id="t1", source="custom", evaluator_type="llm", status="draft"
        )

    def test_list_defaults(self, bundle):
        bundle.mod.list_evaluators_impl("t1")
        bundle.db["list_evaluators"].assert_called_once_with(
            tenant_id="t1", source=None, evaluator_type=None, status=None
        )

    def test_get(self, bundle):
        bundle.db["get_evaluator"].return_value = {"id": 1}
        assert bundle.mod.get_evaluator_impl(1, "t1") == {"id": 1}
        bundle.db["get_evaluator"].assert_called_once_with(evaluator_id=1, tenant_id="t1")

    def test_create_without_code(self, bundle):
        bundle.db["create_evaluator"].return_value = {"id": 1}
        out = bundle.mod.create_evaluator_impl(
            tenant_id="t1", user_id="u1", name="n", description="d",
            evaluator_type="llm", prompt="p",
        )
        assert out == {"id": 1}
        bundle.code_val.assert_not_called()
        bundle.db["create_evaluator"].assert_called_once_with(
            tenant_id="t1", user_id="u1", name="n", description="d",
            evaluator_type="llm", prompt="p", code=None,
            score_range_min=0.0, score_range_max=1.0, pass_threshold=0.5,
            input_fields=[], model_id=None,
        )

    def test_create_with_code_validates(self, bundle):
        bundle.mod.create_evaluator_impl(
            tenant_id="t1", user_id="u1", name="n", description="d",
            evaluator_type="code", prompt=None, code="print(1)",
        )
        bundle.code_val.assert_called_once_with("print(1)")

    def test_update(self, bundle):
        bundle.db["update_evaluator"].return_value = {"id": 1}
        out = bundle.mod.update_evaluator_impl(1, "t1", name="new")
        assert out == {"id": 1}
        bundle.code_val.assert_not_called()
        bundle.db["update_evaluator"].assert_called_once_with(
            evaluator_id=1, tenant_id="t1", name="new"
        )

    def test_update_with_code_validates(self, bundle):
        bundle.mod.update_evaluator_impl(1, "t1", code="x", name="new")
        bundle.code_val.assert_called_once_with("x")

    def test_delete(self, bundle):
        bundle.db["delete_evaluator"].return_value = True
        assert bundle.mod.delete_evaluator_impl(1, "t1") is True
        bundle.db["delete_evaluator"].assert_called_once_with(evaluator_id=1, tenant_id="t1")

    def test_publish(self, bundle):
        bundle.db["publish_evaluator"].return_value = {"id": 1}
        assert bundle.mod.publish_evaluator_impl(1, "t1", version_name="v", release_note="r") == {"id": 1}
        bundle.db["publish_evaluator"].assert_called_once_with(
            evaluator_id=1, tenant_id="t1", version_name="v", release_note="r"
        )

    def test_list_versions(self, bundle):
        bundle.db["list_evaluator_versions"].return_value = [{"v": 1}]
        assert bundle.mod.list_evaluator_versions_impl(1, "t1") == [{"v": 1}]
        bundle.db["list_evaluator_versions"].assert_called_once_with(evaluator_id=1, tenant_id="t1")

    def test_restore_version(self, bundle):
        bundle.db["restore_evaluator_version"].return_value = {"id": 1}
        assert bundle.mod.restore_evaluator_version_impl(9, "t1") == {"id": 1}
        bundle.db["restore_evaluator_version"].assert_called_once_with(version_id=9, tenant_id="t1")

    def test_delete_version(self, bundle):
        bundle.db["delete_evaluator_version"].return_value = True
        assert bundle.mod.delete_evaluator_version_impl(9, "t1") is True
        bundle.db["delete_evaluator_version"].assert_called_once_with(version_id=9, tenant_id="t1")


# ---------------------------------------------------------------------------
# 2. LLM generation helpers
# ---------------------------------------------------------------------------


class TestBuildEvaluatorGenPrompt:
    def test_without_agent(self, bundle):
        out = bundle.mod._build_evaluator_gen_prompt("req", None, "t1")
        assert "req" in out and "Evaluation Request" not in out
        bundle.profile.assert_not_called()

    def test_agent_without_profile(self, bundle):
        bundle.profile.return_value = None
        bundle.fmt_profile.return_value = ""
        out = bundle.mod._build_evaluator_gen_prompt("req", 3, "t1")
        assert "Evaluation Request" not in out
        bundle.profile.assert_called_once_with(3, "t1")

    def test_agent_with_profile(self, bundle):
        bundle.profile.return_value = {"name": "a"}
        bundle.fmt_profile.return_value = "Agent profile text"
        out = bundle.mod._build_evaluator_gen_prompt("req", 3, "t1")
        assert "Agent profile text" in out
        assert "Evaluation Request" in out
        assert "req" in out


class TestParseLlmEvaluatorResponse:
    def test_fenced_json(self, bundle):
        out = bundle.mod._parse_llm_evaluator_response('```json\n{"name": "x"}\n```')
        assert out == {"name": "x"}

    def test_plain_json(self, bundle):
        assert bundle.mod._parse_llm_evaluator_response('{"a": 1}') == {"a": 1}

    def test_invalid_json(self, bundle):
        code = _exc_code(bundle, bundle.mod._parse_llm_evaluator_response, "not json")
        assert code == bundle.ErrorCode.COMMON_VALIDATION_ERROR

    def test_fenced_invalid_json(self, bundle):
        code = _exc_code(bundle, bundle.mod._parse_llm_evaluator_response, '```\nbad\n```')
        assert code == bundle.ErrorCode.COMMON_VALIDATION_ERROR


class TestValidateEvaluatorFields:
    def test_missing_name(self, bundle):
        code = _exc_code(bundle, bundle.mod._validate_evaluator_fields, {})
        assert code == bundle.ErrorCode.COMMON_VALIDATION_ERROR

    def test_unsupported_type(self, bundle):
        code = _exc_code(
            bundle, bundle.mod._validate_evaluator_fields, {"name": "n", "evaluator_type": "x"}
        )
        assert code == bundle.ErrorCode.COMMON_VALIDATION_ERROR

    def test_llm_without_prompt(self, bundle):
        code = _exc_code(
            bundle, bundle.mod._validate_evaluator_fields, {"name": "n", "evaluator_type": "llm"}
        )
        assert code == bundle.ErrorCode.COMMON_VALIDATION_ERROR

    def test_code_without_code(self, bundle):
        code = _exc_code(
            bundle, bundle.mod._validate_evaluator_fields, {"name": "n", "evaluator_type": "code"}
        )
        assert code == bundle.ErrorCode.COMMON_VALIDATION_ERROR

    def test_valid_llm(self, bundle):
        assert bundle.mod._validate_evaluator_fields(
            {"name": "n", "evaluator_type": "llm", "prompt": "p"}
        ) == "llm"

    def test_valid_code(self, bundle):
        assert bundle.mod._validate_evaluator_fields(
            {"name": "n", "evaluator_type": "code", "code": "x"}
        ) == "code"


class TestGenerateEvaluatorByLlm:
    def test_success_llm(self, bundle):
        bundle.tmpl.return_value = {"SYSTEM_PROMPT": "sys"}
        bundle.llm.return_value = '{"name": "n", "evaluator_type": "llm", "prompt": "p"}'
        out = bundle.mod.generate_evaluator_by_llm_impl("desc", "t1", 7)
        assert out["name"] == "n" and out["evaluator_type"] == "llm"
        assert out["prompt"] == "p"
        assert out["code"] is None
        assert out["score_range_min"] == 0.0 and out["score_range_max"] == 1.0
        assert out["pass_threshold"] == 0.5
        assert out["input_fields"] == [
            {"name": "query", "type": "string", "required": True},
            {"name": "expected", "type": "string", "required": True},
            {"name": "actual", "type": "string", "required": True},
        ]
        bundle.tmpl.assert_called_once_with("evaluation_generate_evaluator", "zh")
        bundle.llm.assert_called_once_with(
            model_id=7, user_prompt=bundle.llm.call_args.kwargs["user_prompt"],
            system_prompt="sys", tenant_id="t1",
        )

    def test_success_code_with_agent(self, bundle):
        bundle.tmpl.return_value = {"SYSTEM_PROMPT": "sys"}
        bundle.profile.return_value = {"name": "a"}
        bundle.fmt_profile.return_value = "profile"
        bundle.llm.return_value = '{"name": "n", "evaluator_type": "code", "code": "x"}'
        out = bundle.mod.generate_evaluator_by_llm_impl("desc", "t1", 7, agent_id=3)
        assert out["code"] == "x" and out["prompt"] is None
        assert "profile" in bundle.llm.call_args.kwargs["user_prompt"]

    def test_llm_call_failure(self, bundle):
        bundle.tmpl.return_value = {"SYSTEM_PROMPT": "sys"}
        bundle.llm.side_effect = RuntimeError("boom")
        code = _exc_code(bundle, bundle.mod.generate_evaluator_by_llm_impl, "desc", "t1", 7)
        assert code == bundle.ErrorCode.COMMON_VALIDATION_ERROR


# ---------------------------------------------------------------------------
# 3. Export / Import
# ---------------------------------------------------------------------------


class TestStripInstanceFields:
    def test_strips(self, bundle):
        row = {
            "evaluator_id": 1, "tenant_id": "t1", "name": "n", "evaluator_type": "llm",
            "prompt": "p", "status": "active",
        }
        out = bundle.mod._strip_instance_fields(row)
        assert "name" in out
        assert "prompt" in out
        assert "evaluator_type" in out
        assert "evaluator_id" not in out and "tenant_id" not in out and "status" not in out


class TestExportEvaluators:
    def test_success(self, bundle):
        bundle.db["get_evaluator"].side_effect = [
            {"evaluator_id": 1, "tenant_id": "t1", "source": "custom", "name": "a", "evaluator_type": "llm"},
            {"evaluator_id": 2, "tenant_id": "t1", "source": "custom", "name": "b", "evaluator_type": "code"},
        ]
        out = bundle.mod.export_evaluators_impl("t1", [1, 2])
        assert out["version"] == "1.0"
        assert out["type"] == "nexent_evaluator_export"
        assert "exported_at" in out
        assert out["evaluators"] == [
            {"name": "a", "evaluator_type": "llm"},
            {"name": "b", "evaluator_type": "code"},
        ]

    def test_not_found(self, bundle):
        bundle.db["get_evaluator"].return_value = None
        code = _exc_code(bundle, bundle.mod.export_evaluators_impl, "t1", [9])
        assert code == bundle.ErrorCode.COMMON_RESOURCE_NOT_FOUND

    def test_builtin_rejected(self, bundle):
        bundle.db["get_evaluator"].return_value = {"source": "builtin", "name": "b"}
        code = _exc_code(bundle, bundle.mod.export_evaluators_impl, "t1", [1])
        assert code == bundle.ErrorCode.COMMON_VALIDATION_ERROR


class TestValidateEvaluatorItem:
    def test_non_dict(self, bundle):
        assert bundle.mod._validate_evaluator_item("x", 0)[5] == {
            "index": 0, "reason": "evaluator entry must be an object",
        }

    def test_missing_name(self, bundle):
        assert bundle.mod._validate_evaluator_item({"evaluator_type": "llm", "prompt": "p"}, 1)[5] == {
            "index": 1, "reason": "name is required",
        }

    def test_unsupported_type(self, bundle):
        err = bundle.mod._validate_evaluator_item({"name": "n", "evaluator_type": "x"}, 2)[5]
        assert err["reason"].startswith("unsupported evaluator_type")

    def test_llm_requires_prompt(self, bundle):
        err = bundle.mod._validate_evaluator_item({"name": "n", "evaluator_type": "llm"}, 3)[5]
        assert err["reason"] == "llm evaluator requires prompt"

    def test_code_requires_code(self, bundle):
        err = bundle.mod._validate_evaluator_item({"name": "n", "evaluator_type": "code"}, 4)[5]
        assert err["reason"] == "code evaluator requires code"

    def test_invalid_range(self, bundle):
        item = {"name": "n", "evaluator_type": "llm", "prompt": "p", "score_range_min": 1, "score_range_max": 1}
        err = bundle.mod._validate_evaluator_item(item, 5)[5]
        assert "score_range_min(1.0) >= score_range_max(1.0)" in err["reason"]

    def test_threshold_outside_range(self, bundle):
        item = {"name": "n", "evaluator_type": "llm", "prompt": "p", "score_range_min": 0, "score_range_max": 10, "pass_threshold": 10}
        err = bundle.mod._validate_evaluator_item(item, 6)[5]
        assert err["reason"].startswith("pass_threshold")

    def test_valid(self, bundle):
        item = {"name": "n", "evaluator_type": "llm", "prompt": "p", "score_range_min": 0, "score_range_max": 10, "pass_threshold": 5}
        name, etype, lo, hi, th, err = bundle.mod._validate_evaluator_item(item, 7)
        assert (name, etype, lo, hi, th, err) == ("n", "llm", 0.0, 10.0, 5.0, None)

    def test_name_stripped(self, bundle):
        item = {"name": "  ", "evaluator_type": "llm"}
        assert bundle.mod._validate_evaluator_item(item, 8)[5]["reason"] == "name is required"


class TestImportEvaluators:
    def _export(self, evaluators):
        return {"version": "1.0", "type": "nexent_evaluator_export", "evaluators": evaluators}

    def _valid_item(self, name="new", etype="llm", **over):
        item = {"name": name, "evaluator_type": etype, "prompt": "p"}
        if etype == "code":
            item = {"name": name, "evaluator_type": "code", "code": "x"}
        item.update(over)
        return item

    def test_non_dict_payload(self, bundle):
        code = _exc_code(bundle, bundle.mod.import_evaluators_impl, "t1", "u1", "nope")
        assert code == bundle.ErrorCode.COMMON_VALIDATION_ERROR

    def test_wrong_version_type(self, bundle):
        code = _exc_code(
            bundle, bundle.mod.import_evaluators_impl, "t1", "u1",
            {"version": "0.9", "type": "nexent_evaluator_export", "evaluators": []},
        )
        assert code == bundle.ErrorCode.COMMON_VALIDATION_ERROR

    def test_no_evaluators(self, bundle):
        code = _exc_code(
            bundle, bundle.mod.import_evaluators_impl, "t1", "u1",
            {"version": "1.0", "type": "nexent_evaluator_export", "evaluators": []},
        )
        assert code == bundle.ErrorCode.COMMON_VALIDATION_ERROR

    def test_import_mix(self, bundle):
        bundle.db["list_evaluators"].return_value = [
            {"name": "dup", "evaluator_type": "llm", "source": "custom"},
        ]
        bundle.db["create_evaluator"].return_value = {"id": 1}
        export = self._export([
            self._valid_item("dup"),            # skipped
            self._valid_item("ok1"),            # imported
            self._valid_item("ok2", etype="code"),  # imported
            "not-a-dict",                       # error
            {"name": "n", "evaluator_type": "x"},  # error
        ])
        out = bundle.mod.import_evaluators_impl("t1", "u1", export)
        assert out["imported"] == 2 and out["skipped"] == 1
        assert out["errors"] == [
            {"index": 3, "reason": "evaluator entry must be an object"},
            {"index": 4, "name": "n", "reason": "unsupported evaluator_type: x"},
        ]
        assert bundle.db["create_evaluator"].call_count == 2

    def test_create_failure(self, bundle):
        bundle.db["list_evaluators"].return_value = []
        bundle.db["create_evaluator"].side_effect = RuntimeError("boom")
        export = self._export([self._valid_item("bad")])
        out = bundle.mod.import_evaluators_impl("t1", "u1", export)
        assert out["imported"] == 0
        assert out["errors"][0]["reason"] == "Invalid evaluator data"

    def test_create_returns_falsy(self, bundle):
        bundle.db["list_evaluators"].return_value = []
        bundle.db["create_evaluator"].return_value = None
        export = self._export([self._valid_item("weird")])
        out = bundle.mod.import_evaluators_impl("t1", "u1", export)
        assert out == {"imported": 0, "skipped": 0, "errors": []}

    def test_create_fields_passed(self, bundle):
        bundle.db["list_evaluators"].return_value = []
        bundle.db["create_evaluator"].return_value = {"id": 9}
        item = self._valid_item(
            "rich", description="d", score_range_min=0, score_range_max=10,
            pass_threshold=5, input_fields=[{"name": "q"}], model_id=3,
        )
        out = bundle.mod.import_evaluators_impl("t1", "u1", self._export([item]))
        assert out == {"imported": 1, "skipped": 0, "errors": []}
        bundle.db["create_evaluator"].assert_called_once_with(
            tenant_id="t1", user_id="u1", name="rich", description="d",
            evaluator_type="llm", prompt="p", code=None,
            score_range_min=0.0, score_range_max=10.0, pass_threshold=5.0,
            input_fields=[{"name": "q"}], model_id=3,
        )
