"""Unit tests for ``apps.evaluator_app``.

Directly invoke each async endpoint function with the FastAPI
``Query/Header/Body`` defaults replaced by explicit values, patching the
13 ``services.evaluator_service`` impls and ``utils.auth_utils`` identity
resolution.  The heavy ``services.evaluator_service`` module is stubbed at
``sys.modules`` level (idempotent ``_register_package`` registration) so the
app module can be loaded with ``spec_from_file_location`` without pulling in
SQLAlchemy-heavy service dependencies.  ``consts`` is stubbed too so the
``ErrorCode`` / ``AppException`` used by the endpoints are self-contained.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import UploadFile

# ---------------------------------------------------------------------------
# 1. Path setup + idempotent package registration
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

MODULE_UNDER_TEST = "apps.evaluator_app"

_IMPL_NAMES = [
    "create_evaluator_impl",
    "delete_evaluator_impl",
    "delete_evaluator_version_impl",
    "export_evaluators_impl",
    "generate_evaluator_by_llm_impl",
    "get_evaluator_impl",
    "import_evaluators_impl",
    "list_evaluator_versions_impl",
    "list_evaluators_impl",
    "publish_evaluator_impl",
    "restore_evaluator_version_impl",
    "update_evaluator_impl",
]


def _register_package(name: str) -> types.ModuleType:
    existing = sys.modules.get(name)
    if existing is not None and hasattr(existing, "__path__"):
        return existing
    pkg = types.ModuleType(name)
    backend_path = _BACKEND_DIR / name
    pkg.__path__ = [str(backend_path)] if backend_path.is_dir() else []
    sys.modules[name] = pkg
    return pkg


def _install_stubs():
    """Register placeholder modules for every transitive import of the app."""

    def mk_mod(name, **attrs):
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m
        return m

    # ---- consts ----------------------------------------------------------
    class _ErrorCode:
        COMMON_VALIDATION_ERROR = "000101"
        COMMON_UNAUTHORIZED = "000201"
        COMMON_RESOURCE_NOT_FOUND = "000501"
        SYSTEM_INTERNAL_ERROR = "990105"

    class _AppException(Exception):
        def __init__(self, code, message: str = "", extra=None):
            super().__init__(message)
            self.code = code
            self.message = message
            self.extra = extra

    class _UnauthorizedError(_AppException):
        pass

    _consts_pkg = _register_package("consts")
    _ec_mod = mk_mod("consts.error_code", ErrorCode=_ErrorCode)
    _consts_pkg.error_code = _ec_mod
    _ex_mod = mk_mod(
        "consts.exceptions",
        AppException=_AppException,
        UnauthorizedError=_UnauthorizedError,
    )
    _consts_pkg.exceptions = _ex_mod

    # ---- services.evaluator_service --------------------------------------
    _svc_pkg = _register_package("services")
    _ev_mod = mk_mod("services.evaluator_service", **{n: MagicMock(name=n) for n in _IMPL_NAMES})
    _svc_pkg.evaluator_service = _ev_mod

    # ---- utils.auth_utils ------------------------------------------------
    _utils_pkg = _register_package("utils")
    _au_mod = mk_mod("utils.auth_utils", get_current_user_id=MagicMock(name="get_current_user_id"))
    _utils_pkg.auth_utils = _au_mod
    return _ErrorCode, _AppException, _UnauthorizedError


_ERROR_CODE, _APP_EXC, _UNAUTH_EXC = _install_stubs()


@pytest.fixture
def bundle():
    """Fresh mocks + fresh import of the app module for every test."""
    import importlib.util as _ilu

    for extra in (str(_REPO_ROOT), str(_BACKEND_DIR)):
        if extra not in sys.path:
            sys.path.insert(0, extra)

    impls = {n: MagicMock(name=n) for n in _IMPL_NAMES}
    auth = MagicMock(name="get_current_user_id")
    auth.return_value = ("u1", "t1")

    _svc_mod = sys.modules["services.evaluator_service"]
    for n, m in impls.items():
        setattr(_svc_mod, n, m)
    _au_mod = sys.modules["utils.auth_utils"]
    _au_mod.get_current_user_id = auth

    if MODULE_UNDER_TEST in sys.modules:
        del sys.modules[MODULE_UNDER_TEST]
    apps_pkg = _register_package("apps")
    if hasattr(apps_pkg, "evaluator_app"):
        delattr(apps_pkg, "evaluator_app")

    src = _BACKEND_DIR / "apps" / "evaluator_app.py"
    spec = _ilu.spec_from_file_location(MODULE_UNDER_TEST, str(src))
    assert spec is not None and spec.loader is not None, f"cannot locate {src}"
    mod = _ilu.module_from_spec(spec)
    sys.modules[MODULE_UNDER_TEST] = mod
    spec.loader.exec_module(mod)
    apps_pkg.evaluator_app = mod

    class _Bundle:
        pass

    b = _Bundle()
    b.mod = mod
    b.impls = impls
    b.auth = auth
    b.ErrorCode = _ERROR_CODE
    b.AppException = _APP_EXC
    b.UnauthorizedError = _UNAUTH_EXC
    return b


def _resp_json(resp):
    return json.loads(resp.body)


# ---------------------------------------------------------------------------
# 2. Endpoint tests
# ---------------------------------------------------------------------------


class TestListEvaluators:
    async def test_success(self, bundle):
        bundle.impls["list_evaluators_impl"].return_value = [{"evaluator_id": 1}]
        resp = await bundle.mod.list_evaluators_api(
            source=None, evaluator_type=None, authorization="tok"
        )
        assert resp.status_code == 200
        assert _resp_json(resp) == {"message": "Success", "data": [{"evaluator_id": 1}]}
        bundle.impls["list_evaluators_impl"].assert_called_once_with(
            tenant_id="t1", source=None, evaluator_type=None, status=None
        )
        bundle.auth.assert_called_once_with("tok")

    async def test_unauthorized(self, bundle):
        bundle.auth.side_effect = bundle.UnauthorizedError("no")
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.list_evaluators_api()
        assert exc.value.code == bundle.ErrorCode.COMMON_UNAUTHORIZED

    async def test_app_exception_propagates(self, bundle):
        bundle.impls["list_evaluators_impl"].side_effect = bundle.AppException(
            "BIZ_CODE", "inner"
        )
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.list_evaluators_api()
        assert exc.value.code == "BIZ_CODE"

    async def test_internal_error(self, bundle):
        bundle.impls["list_evaluators_impl"].side_effect = RuntimeError("boom")
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.list_evaluators_api()
        assert exc.value.code == bundle.ErrorCode.SYSTEM_INTERNAL_ERROR


class TestGetEvaluator:
    async def test_success(self, bundle):
        bundle.impls["get_evaluator_impl"].return_value = {"evaluator_id": 1}
        resp = await bundle.mod.get_evaluator_api(evaluator_id=7)
        assert resp.status_code == 200
        assert _resp_json(resp)["data"] == {"evaluator_id": 1}
        bundle.impls["get_evaluator_impl"].assert_called_once_with(
            evaluator_id=7, tenant_id="t1"
        )

    async def test_not_found(self, bundle):
        bundle.impls["get_evaluator_impl"].return_value = None
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.get_evaluator_api(evaluator_id=7)
        assert exc.value.code == bundle.ErrorCode.COMMON_RESOURCE_NOT_FOUND

    async def test_app_exception_propagates(self, bundle):
        bundle.impls["get_evaluator_impl"].side_effect = bundle.AppException(
            "SOME_CODE", "inner"
        )
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.get_evaluator_api(evaluator_id=7)
        assert exc.value.code == "SOME_CODE"

    async def test_internal_error(self, bundle):
        bundle.impls["get_evaluator_impl"].side_effect = RuntimeError("boom")
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.get_evaluator_api(evaluator_id=7)
        assert exc.value.code == bundle.ErrorCode.SYSTEM_INTERNAL_ERROR


class TestCreateEvaluator:
    async def test_success(self, bundle):
        payload = bundle.mod.CreateEvaluatorRequest(
            name="ev", description="d", evaluator_type="llm", model_id=3
        )
        bundle.impls["create_evaluator_impl"].return_value = {"evaluator_id": 9}
        resp = await bundle.mod.create_evaluator_api(payload=payload)
        assert resp.status_code == 200
        assert _resp_json(resp)["data"] == {"evaluator_id": 9}
        bundle.impls["create_evaluator_impl"].assert_called_once_with(
            tenant_id="t1", user_id="u1", name="ev", description="d",
            evaluator_type="llm", prompt=None, prompt_en=None, code=None,
            score_range_min=None, score_range_max=None, pass_threshold=None,
            input_fields=None, model_id=3,
        )

    async def test_unauthorized(self, bundle):
        bundle.auth.side_effect = bundle.UnauthorizedError("no")
        payload = bundle.mod.CreateEvaluatorRequest(name="ev")
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.create_evaluator_api(payload=payload)
        assert exc.value.code == bundle.ErrorCode.COMMON_UNAUTHORIZED

    async def test_app_exception_propagates(self, bundle):
        bundle.impls["create_evaluator_impl"].side_effect = bundle.AppException(
            "BIZ_CODE", "inner"
        )
        payload = bundle.mod.CreateEvaluatorRequest(name="ev")
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.create_evaluator_api(payload=payload)
        assert exc.value.code == "BIZ_CODE"

    async def test_internal_error(self, bundle):
        bundle.impls["create_evaluator_impl"].side_effect = RuntimeError("boom")
        payload = bundle.mod.CreateEvaluatorRequest(name="ev")
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.create_evaluator_api(payload=payload)
        assert exc.value.code == bundle.ErrorCode.SYSTEM_INTERNAL_ERROR


class TestUpdateEvaluator:
    async def test_success(self, bundle):
        bundle.impls["get_evaluator_impl"].return_value = {"evaluator_id": 7}
        bundle.impls["update_evaluator_impl"].return_value = {"evaluator_id": 7, "name": "new"}
        payload = bundle.mod.UpdateEvaluatorRequest(name="new", score_range_max=95.0)
        resp = await bundle.mod.update_evaluator_api(evaluator_id=7, payload=payload)
        assert resp.status_code == 200
        assert _resp_json(resp)["data"] == {"evaluator_id": 7, "name": "new"}
        bundle.impls["update_evaluator_impl"].assert_called_once_with(
            evaluator_id=7, tenant_id="t1", name="new", score_range_max=95.0
        )

    async def test_not_found(self, bundle):
        bundle.impls["get_evaluator_impl"].return_value = None
        payload = bundle.mod.UpdateEvaluatorRequest(name="new")
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.update_evaluator_api(evaluator_id=7, payload=payload)
        assert exc.value.code == bundle.ErrorCode.COMMON_RESOURCE_NOT_FOUND

    async def test_not_draft_validation(self, bundle):
        bundle.impls["get_evaluator_impl"].return_value = {"evaluator_id": 7}
        bundle.impls["update_evaluator_impl"].return_value = None
        payload = bundle.mod.UpdateEvaluatorRequest(name="new")
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.update_evaluator_api(evaluator_id=7, payload=payload)
        assert exc.value.code == bundle.ErrorCode.COMMON_VALIDATION_ERROR

    async def test_internal_error(self, bundle):
        bundle.impls["get_evaluator_impl"].side_effect = RuntimeError("boom")
        payload = bundle.mod.UpdateEvaluatorRequest(name="new")
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.update_evaluator_api(evaluator_id=7, payload=payload)
        assert exc.value.code == bundle.ErrorCode.SYSTEM_INTERNAL_ERROR


class TestDeleteEvaluator:
    async def test_success(self, bundle):
        bundle.impls["delete_evaluator_impl"].return_value = True
        resp = await bundle.mod.delete_evaluator_api(evaluator_id=7)
        assert resp.status_code == 200
        assert _resp_json(resp) == {"message": "Success", "data": None}
        bundle.impls["delete_evaluator_impl"].assert_called_once_with(
            evaluator_id=7, tenant_id="t1"
        )

    async def test_not_deletable_validation(self, bundle):
        bundle.impls["delete_evaluator_impl"].return_value = False
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.delete_evaluator_api(evaluator_id=7)
        assert exc.value.code == bundle.ErrorCode.COMMON_VALIDATION_ERROR

    async def test_internal_error(self, bundle):
        bundle.impls["delete_evaluator_impl"].side_effect = RuntimeError("boom")
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.delete_evaluator_api(evaluator_id=7)
        assert exc.value.code == bundle.ErrorCode.SYSTEM_INTERNAL_ERROR


class TestPublishEvaluator:
    async def test_success(self, bundle):
        bundle.impls["publish_evaluator_impl"].return_value = {"evaluator_id": 7, "status": "PUBLISHED"}
        resp = await bundle.mod.publish_evaluator_api(
            evaluator_id=7, version_name="v1", release_note="note"
        )
        assert resp.status_code == 200
        assert _resp_json(resp)["data"]["status"] == "PUBLISHED"
        bundle.impls["publish_evaluator_impl"].assert_called_once_with(
            evaluator_id=7, tenant_id="t1", version_name="v1", release_note="note"
        )

    async def test_not_draft_validation(self, bundle):
        bundle.impls["publish_evaluator_impl"].return_value = None
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.publish_evaluator_api(evaluator_id=7)
        assert exc.value.code == bundle.ErrorCode.COMMON_VALIDATION_ERROR

    async def test_internal_error(self, bundle):
        bundle.impls["publish_evaluator_impl"].side_effect = RuntimeError("boom")
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.publish_evaluator_api(evaluator_id=7)
        assert exc.value.code == bundle.ErrorCode.SYSTEM_INTERNAL_ERROR


class TestListVersions:
    async def test_success(self, bundle):
        bundle.impls["list_evaluator_versions_impl"].return_value = [{"version_no": 1}]
        resp = await bundle.mod.list_evaluator_versions_api(evaluator_id=7)
        assert resp.status_code == 200
        assert _resp_json(resp)["data"] == [{"version_no": 1}]

    async def test_unauthorized(self, bundle):
        bundle.auth.side_effect = bundle.UnauthorizedError("no")
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.list_evaluator_versions_api(evaluator_id=7)
        assert exc.value.code == bundle.ErrorCode.COMMON_UNAUTHORIZED

    async def test_app_exception_propagates(self, bundle):
        bundle.impls["list_evaluator_versions_impl"].side_effect = bundle.AppException(
            "BIZ_CODE", "inner"
        )
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.list_evaluator_versions_api(evaluator_id=7)
        assert exc.value.code == "BIZ_CODE"

    async def test_internal_error(self, bundle):
        bundle.impls["list_evaluator_versions_impl"].side_effect = RuntimeError("boom")
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.list_evaluator_versions_api(evaluator_id=7)
        assert exc.value.code == bundle.ErrorCode.SYSTEM_INTERNAL_ERROR


class TestRestoreVersion:
    async def test_success(self, bundle):
        bundle.impls["restore_evaluator_version_impl"].return_value = {"version_no": 2}
        resp = await bundle.mod.restore_evaluator_version_api(evaluator_id=7, version_id=2)
        assert resp.status_code == 200
        assert _resp_json(resp)["data"] == {"version_no": 2}
        bundle.impls["restore_evaluator_version_impl"].assert_called_once_with(
            version_id=2, tenant_id="t1"
        )

    async def test_not_found(self, bundle):
        bundle.impls["restore_evaluator_version_impl"].return_value = None
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.restore_evaluator_version_api(evaluator_id=7, version_id=2)
        assert exc.value.code == bundle.ErrorCode.COMMON_RESOURCE_NOT_FOUND

    async def test_internal_error(self, bundle):
        bundle.impls["restore_evaluator_version_impl"].side_effect = RuntimeError("boom")
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.restore_evaluator_version_api(evaluator_id=7, version_id=2)
        assert exc.value.code == bundle.ErrorCode.SYSTEM_INTERNAL_ERROR


class TestDeleteVersion:
    async def test_success(self, bundle):
        bundle.impls["delete_evaluator_version_impl"].return_value = True
        resp = await bundle.mod.delete_evaluator_version_api(evaluator_id=7, version_id=2)
        assert resp.status_code == 200
        assert _resp_json(resp) == {"message": "Success", "data": None}

    async def test_not_found(self, bundle):
        bundle.impls["delete_evaluator_version_impl"].return_value = False
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.delete_evaluator_version_api(evaluator_id=7, version_id=2)
        assert exc.value.code == bundle.ErrorCode.COMMON_RESOURCE_NOT_FOUND

    async def test_internal_error(self, bundle):
        bundle.impls["delete_evaluator_version_impl"].side_effect = RuntimeError("boom")
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.delete_evaluator_version_api(evaluator_id=7, version_id=2)
        assert exc.value.code == bundle.ErrorCode.SYSTEM_INTERNAL_ERROR


class TestExport:
    async def test_success_streams_json(self, bundle):
        data = {"version": "1.0", "items": [{"name": "ev"}]}
        bundle.impls["export_evaluators_impl"].return_value = data
        payload = bundle.mod.ExportEvaluatorsRequest(evaluator_ids=[1, 2])
        resp = await bundle.mod.export_evaluators_api(payload=payload)
        assert resp.status_code == 200
        assert resp.headers["Content-Disposition"] == 'attachment; filename="evaluators_export.json"'
        chunks = []
        async for chunk in resp.body_iterator:
            chunks.append(chunk)
        assert json.loads(b"".join(chunks)) == data

    async def test_internal_error(self, bundle):
        bundle.impls["export_evaluators_impl"].side_effect = RuntimeError("boom")
        payload = bundle.mod.ExportEvaluatorsRequest(evaluator_ids=[1])
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.export_evaluators_api(payload=payload)
        assert exc.value.code == bundle.ErrorCode.SYSTEM_INTERNAL_ERROR

    async def test_app_exception_propagates(self, bundle):
        bundle.impls["export_evaluators_impl"].side_effect = bundle.AppException(
            "BIZ_CODE", "inner"
        )
        payload = bundle.mod.ExportEvaluatorsRequest(evaluator_ids=[1])
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.export_evaluators_api(payload=payload)
        assert exc.value.code == "BIZ_CODE"


class TestImport:
    class _FakeFile:
        """Synchronous file object: starlette's UploadFile.read() runs the
        underlying ``file.read`` inside a thread pool (``run_in_threadpool``),
        so this must be a plain sync method accepting ``size``."""

        def __init__(self, raw: bytes):
            self._raw = raw

        def read(self, size: int = -1):
            if size is None or size < 0:
                return self._raw
            return self._raw[:size]

    def _make_upload(self, raw: bytes) -> UploadFile:
        return UploadFile(file=self._FakeFile(raw))

    async def test_success(self, bundle):
        bundle.impls["import_evaluators_impl"].return_value = {
            "imported": 1, "skipped": 0, "errors": []
        }
        resp = await bundle.mod.import_evaluators_api(
            file=self._make_upload(b'{"evaluators": []}')
        )
        assert resp.status_code == 200
        assert _resp_json(resp)["data"]["imported"] == 1
        bundle.impls["import_evaluators_impl"].assert_called_once_with(
            tenant_id="t1", user_id="u1", export_data={"evaluators": []}
        )

    async def test_invalid_json(self, bundle):
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.import_evaluators_api(
                file=self._make_upload(b"{not-json")
            )
        assert exc.value.code == bundle.ErrorCode.COMMON_VALIDATION_ERROR
        assert "Invalid JSON" in exc.value.message

    async def test_unicode_error(self, bundle):
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.import_evaluators_api(
                file=self._make_upload(b"\xff\xfe invalid utf8")
            )
        assert exc.value.code == bundle.ErrorCode.COMMON_VALIDATION_ERROR

    async def test_unauthorized(self, bundle):
        bundle.auth.side_effect = bundle.UnauthorizedError("no")
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.import_evaluators_api(
                file=self._make_upload(b"{}")
            )
        assert exc.value.code == bundle.ErrorCode.COMMON_UNAUTHORIZED

    async def test_internal_error(self, bundle):
        bundle.impls["import_evaluators_impl"].side_effect = RuntimeError("boom")
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.import_evaluators_api(
                file=self._make_upload(b"{}")
            )
        assert exc.value.code == bundle.ErrorCode.SYSTEM_INTERNAL_ERROR


class TestGenerate:
    async def test_success(self, bundle):
        bundle.impls["generate_evaluator_by_llm_impl"].return_value = {"evaluator_id": 5}
        payload = bundle.mod.GenerateEvaluatorRequest(description="d", model_id=3, agent_id=9)
        resp = await bundle.mod.generate_evaluator_api(payload=payload)
        assert resp.status_code == 200
        assert _resp_json(resp)["data"] == {"evaluator_id": 5}
        bundle.impls["generate_evaluator_by_llm_impl"].assert_called_once_with(
            description="d", tenant_id="t1", model_id=3, agent_id=9
        )

    async def test_internal_error(self, bundle):
        bundle.impls["generate_evaluator_by_llm_impl"].side_effect = RuntimeError("boom")
        payload = bundle.mod.GenerateEvaluatorRequest(description="d", model_id=3)
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.generate_evaluator_api(payload=payload)
        assert exc.value.code == bundle.ErrorCode.SYSTEM_INTERNAL_ERROR

    async def test_app_exception_propagates(self, bundle):
        bundle.impls["generate_evaluator_by_llm_impl"].side_effect = bundle.AppException(
            "BIZ_CODE", "inner"
        )
        payload = bundle.mod.GenerateEvaluatorRequest(description="d", model_id=3)
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.generate_evaluator_api(payload=payload)
        assert exc.value.code == "BIZ_CODE"


# ---------------------------------------------------------------------------
# 3. Pydantic request model tests
# ---------------------------------------------------------------------------


class TestRequestModels:
    def test_create_request_defaults(self, bundle):
        req = bundle.mod.CreateEvaluatorRequest(name="ev")
        assert req.evaluator_type == "llm"
        assert req.name == "ev"

    def test_score_range_valid(self, bundle):
        req = bundle.mod.EvaluatorFields(
            score_range_min=0, score_range_max=100, pass_threshold=50
        )
        assert req.score_range_min == 0
        assert req.score_range_max == 100

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"score_range_min": 90, "score_range_max": 80},  # lo >= hi
            {"score_range_min": 0, "score_range_max": 101},  # hi > 100
            {"score_range_min": 0, "score_range_max": 10, "pass_threshold": 11},
            {"score_range_min": 0, "score_range_max": 10, "pass_threshold": -1},
        ],
    )
    def test_score_range_invalid(self, bundle, kwargs):
        with pytest.raises(ValueError):
            bundle.mod.EvaluatorFields(**kwargs)

    def test_score_range_nan(self, bundle):
        with pytest.raises(ValueError, match="NaN or Infinity"):
            bundle.mod.EvaluatorFields(score_range_min=float("nan"), score_range_max=100)

    def test_score_range_inf(self, bundle):
        with pytest.raises(ValueError, match="NaN or Infinity"):
            bundle.mod.EvaluatorFields(score_range_min=0, score_range_max=float("inf"))
