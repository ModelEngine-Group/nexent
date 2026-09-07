"""Unit tests for ``apps.evaluation_annotation_app``.

Directly invoke each async endpoint, patching the 8
``database.evaluation_annotation_db`` helpers plus the lazily-imported
``database.agent_evaluation_db.count_active_runs_using_schema`` and the
``utils.auth_utils`` identity resolver.  ``consts`` and the two database
modules are stubbed at ``sys.modules`` level (idempotent
``_register_package`` registration); the app module is loaded with
``spec_from_file_location`` so the FastAPI decorators run against the real
``fastapi``/``pydantic`` installed in the venv.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# 1. Path setup + idempotent package registration
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

MODULE_UNDER_TEST = "apps.evaluation_annotation_app"

_DB_IMPL_NAMES = [
    "batch_upsert_annotations",
    "count_annotations_for_schema",
    "create_annotation_schema",
    "delete_annotation_schema",
    "delete_annotations_by_evaluation_schema",
    "get_annotation_values",
    "list_annotation_schemas",
    "list_annotations_by_evaluation_id",  # lazily imported inside the endpoint
    "update_annotation_schema",
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
    def mk_mod(name, **attrs):
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m
        return m

    class _ErrorCode:
        COMMON_UNAUTHORIZED = "000201"
        COMMON_RESOURCE_NOT_FOUND = "000501"
        AGENT_EVALUATION_ANNOTATION_SCHEMA_IN_USE = "180103"
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

    # ---- database stubs --------------------------------------------------
    _db_pkg = _register_package("database")
    _eadb_mod = mk_mod(
        "database.evaluation_annotation_db",
        **{n: MagicMock(name=n) for n in _DB_IMPL_NAMES},
    )
    _db_pkg.evaluation_annotation_db = _eadb_mod
    _aedb_mod = mk_mod(
        "database.agent_evaluation_db",
        count_active_runs_using_schema=MagicMock(name="count_active_runs_using_schema"),
    )
    _db_pkg.agent_evaluation_db = _aedb_mod

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

    db_impls = {n: MagicMock(name=n) for n in _DB_IMPL_NAMES}
    in_use = MagicMock(name="count_active_runs_using_schema")
    auth = MagicMock(name="get_current_user_id")
    auth.return_value = ("u1", "t1")

    _eadb = sys.modules["database.evaluation_annotation_db"]
    for n, m in db_impls.items():
        setattr(_eadb, n, m)
    sys.modules["database.agent_evaluation_db"].count_active_runs_using_schema = in_use
    sys.modules["utils.auth_utils"].get_current_user_id = auth

    if MODULE_UNDER_TEST in sys.modules:
        del sys.modules[MODULE_UNDER_TEST]
    apps_pkg = _register_package("apps")
    if hasattr(apps_pkg, "evaluation_annotation_app"):
        delattr(apps_pkg, "evaluation_annotation_app")

    src = _BACKEND_DIR / "apps" / "evaluation_annotation_app.py"
    spec = _ilu.spec_from_file_location(MODULE_UNDER_TEST, str(src))
    assert spec is not None and spec.loader is not None, f"cannot locate {src}"
    mod = _ilu.module_from_spec(spec)
    sys.modules[MODULE_UNDER_TEST] = mod
    spec.loader.exec_module(mod)
    apps_pkg.evaluation_annotation_app = mod

    class _Bundle:
        pass

    b = _Bundle()
    b.mod = mod
    b.db = db_impls
    b.in_use = in_use
    b.auth = auth
    b.ErrorCode = _ERROR_CODE
    b.AppException = _APP_EXC
    b.UnauthorizedError = _UNAUTH_EXC
    return b


def _resp_json(resp):
    return json.loads(resp.body)


# ---------------------------------------------------------------------------
# 2. Schema endpoint tests
# ---------------------------------------------------------------------------


class TestListSchemas:
    async def test_success(self, bundle):
        bundle.db["list_annotation_schemas"].return_value = [{"schema_id": 1}]
        resp = await bundle.mod.list_schemas_api()
        assert resp.status_code == 200
        assert _resp_json(resp) == {"message": "Success", "data": [{"schema_id": 1}]}
        bundle.db["list_annotation_schemas"].assert_called_once_with(tenant_id="t1")

    async def test_internal_error(self, bundle):
        bundle.db["list_annotation_schemas"].side_effect = RuntimeError("boom")
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.list_schemas_api()
        assert exc.value.code == bundle.ErrorCode.SYSTEM_INTERNAL_ERROR

    async def test_app_exception_propagates(self, bundle):
        bundle.db["list_annotation_schemas"].side_effect = bundle.AppException(
            "BIZ_CODE", "inner"
        )
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.list_schemas_api()
        assert exc.value.code == "BIZ_CODE"


class TestCreateSchema:
    async def test_success(self, bundle):
        payload = bundle.mod.CreateSchemaRequest(
            name="label", description="d", annotation_type="classification",
            options=[{"label": "ok"}],
        )
        bundle.db["create_annotation_schema"].return_value = {"schema_id": 3}
        resp = await bundle.mod.create_schema_api(payload=payload)
        assert resp.status_code == 200
        assert _resp_json(resp)["data"] == {"schema_id": 3}
        bundle.db["create_annotation_schema"].assert_called_once_with(
            tenant_id="t1", user_id="u1", name="label", description="d",
            annotation_type="classification", options=[{"label": "ok"}],
        )

    async def test_unauthorized(self, bundle):
        bundle.auth.side_effect = bundle.UnauthorizedError("no")
        payload = bundle.mod.CreateSchemaRequest(name="label")
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.create_schema_api(payload=payload)
        assert exc.value.code == bundle.ErrorCode.COMMON_UNAUTHORIZED

    async def test_internal_error(self, bundle):
        bundle.db["create_annotation_schema"].side_effect = RuntimeError("boom")
        payload = bundle.mod.CreateSchemaRequest(name="label")
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.create_schema_api(payload=payload)
        assert exc.value.code == bundle.ErrorCode.SYSTEM_INTERNAL_ERROR

    async def test_app_exception_propagates(self, bundle):
        bundle.db["create_annotation_schema"].side_effect = bundle.AppException(
            "BIZ_CODE", "inner"
        )
        payload = bundle.mod.CreateSchemaRequest(name="label")
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.create_schema_api(payload=payload)
        assert exc.value.code == "BIZ_CODE"


class TestUpdateSchema:
    async def test_success_filters_none(self, bundle):
        bundle.in_use.return_value = 0
        bundle.db["update_annotation_schema"].return_value = {"schema_id": 1, "name": "new"}
        resp = await bundle.mod.update_schema_api(
            schema_id=1, name="new", description=None, options=[{"label": "x"}]
        )
        assert resp.status_code == 200
        assert _resp_json(resp)["data"]["name"] == "new"
        bundle.db["update_annotation_schema"].assert_called_once_with(
            schema_id=1, tenant_id="t1", name="new", options=[{"label": "x"}]
        )
        bundle.in_use.assert_called_once_with(1, "t1")

    async def test_in_use_blocks(self, bundle):
        bundle.in_use.return_value = 2
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.update_schema_api(schema_id=1, name="new")
        assert exc.value.code == bundle.ErrorCode.AGENT_EVALUATION_ANNOTATION_SCHEMA_IN_USE

    async def test_not_found(self, bundle):
        bundle.in_use.return_value = 0
        bundle.db["update_annotation_schema"].return_value = None
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.update_schema_api(schema_id=1, name="new")
        assert exc.value.code == bundle.ErrorCode.COMMON_RESOURCE_NOT_FOUND

    async def test_internal_error(self, bundle):
        bundle.in_use.return_value = 0
        bundle.db["update_annotation_schema"].side_effect = RuntimeError("boom")
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.update_schema_api(schema_id=1, name="new")
        assert exc.value.code == bundle.ErrorCode.SYSTEM_INTERNAL_ERROR

    async def test_unauthorized(self, bundle):
        bundle.auth.side_effect = bundle.UnauthorizedError("no")
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.update_schema_api(schema_id=1, name="new")
        assert exc.value.code == bundle.ErrorCode.COMMON_UNAUTHORIZED

    async def test_app_exception_propagates(self, bundle):
        bundle.in_use.return_value = 0
        bundle.db["update_annotation_schema"].side_effect = bundle.AppException(
            "BIZ_CODE", "inner"
        )
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.update_schema_api(schema_id=1, name="new")
        assert exc.value.code == "BIZ_CODE"


class TestDeleteSchema:
    async def test_success(self, bundle):
        bundle.in_use.return_value = 0
        bundle.db["count_annotations_for_schema"].return_value = 0
        bundle.db["delete_annotation_schema"].return_value = True
        resp = await bundle.mod.delete_schema_api(schema_id=1)
        assert resp.status_code == 200
        assert _resp_json(resp) == {"message": "Success", "data": None}

    async def test_in_use_blocks(self, bundle):
        bundle.in_use.return_value = 1
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.delete_schema_api(schema_id=1)
        assert exc.value.code == bundle.ErrorCode.AGENT_EVALUATION_ANNOTATION_SCHEMA_IN_USE

    async def test_annotations_exist_blocks(self, bundle):
        bundle.in_use.return_value = 0
        bundle.db["count_annotations_for_schema"].return_value = 3
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.delete_schema_api(schema_id=1)
        assert exc.value.code == bundle.ErrorCode.AGENT_EVALUATION_ANNOTATION_SCHEMA_IN_USE

    async def test_not_found(self, bundle):
        bundle.in_use.return_value = 0
        bundle.db["count_annotations_for_schema"].return_value = 0
        bundle.db["delete_annotation_schema"].return_value = False
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.delete_schema_api(schema_id=1)
        assert exc.value.code == bundle.ErrorCode.COMMON_RESOURCE_NOT_FOUND

    async def test_unauthorized(self, bundle):
        bundle.auth.side_effect = bundle.UnauthorizedError("no")
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.delete_schema_api(schema_id=1)
        assert exc.value.code == bundle.ErrorCode.COMMON_UNAUTHORIZED

    async def test_app_exception_propagates(self, bundle):
        bundle.in_use.return_value = 0
        bundle.db["count_annotations_for_schema"].return_value = 0
        bundle.db["delete_annotation_schema"].side_effect = bundle.AppException(
            "BIZ_CODE", "inner"
        )
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.delete_schema_api(schema_id=1)
        assert exc.value.code == "BIZ_CODE"

    async def test_internal_error(self, bundle):
        bundle.in_use.return_value = 0
        bundle.db["count_annotations_for_schema"].return_value = 0
        bundle.db["delete_annotation_schema"].side_effect = RuntimeError("boom")
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.delete_schema_api(schema_id=1)
        assert exc.value.code == bundle.ErrorCode.SYSTEM_INTERNAL_ERROR


# ---------------------------------------------------------------------------
# 3. Annotation data endpoint tests
# ---------------------------------------------------------------------------


class TestGetAnnotations:
    async def test_success(self, bundle):
        bundle.db["list_annotations_by_evaluation_id"].return_value = {1: [{"value": "v"}]}
        resp = await bundle.mod.get_annotations_api(agent_evaluation_id=100)
        assert resp.status_code == 200
        # JSON object keys become strings after round-tripping
        assert _resp_json(resp)["data"] == {"1": [{"value": "v"}]}
        bundle.db["list_annotations_by_evaluation_id"].assert_called_once_with(
            tenant_id="t1", agent_evaluation_id=100
        )

    async def test_unauthorized(self, bundle):
        bundle.auth.side_effect = bundle.UnauthorizedError("no")
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.get_annotations_api(agent_evaluation_id=100)
        assert exc.value.code == bundle.ErrorCode.COMMON_UNAUTHORIZED

    async def test_internal_error(self, bundle):
        bundle.db["list_annotations_by_evaluation_id"].side_effect = RuntimeError("boom")
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.get_annotations_api(agent_evaluation_id=100)
        assert exc.value.code == bundle.ErrorCode.SYSTEM_INTERNAL_ERROR

    async def test_app_exception_propagates(self, bundle):
        bundle.db["list_annotations_by_evaluation_id"].side_effect = bundle.AppException(
            "BIZ_CODE", "inner"
        )
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.get_annotations_api(agent_evaluation_id=100)
        assert exc.value.code == "BIZ_CODE"


class TestBatchUpsert:
    async def test_success(self, bundle):
        payload = bundle.mod.BatchUpsertRequest(
            annotations=[{"case_id": 1, "schema_id": 1, "value": "v"}]
        )
        resp = await bundle.mod.batch_upsert_annotations_api(
            agent_evaluation_id=100, payload=payload
        )
        assert resp.status_code == 200
        bundle.db["batch_upsert_annotations"].assert_called_once_with(
            tenant_id="t1", user_id="u1",
            annotations=[{"case_id": 1, "schema_id": 1, "value": "v"}],
        )

    async def test_unauthorized(self, bundle):
        bundle.auth.side_effect = bundle.UnauthorizedError("no")
        payload = bundle.mod.BatchUpsertRequest()
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.batch_upsert_annotations_api(
                agent_evaluation_id=100, payload=payload
            )
        assert exc.value.code == bundle.ErrorCode.COMMON_UNAUTHORIZED

    async def test_internal_error(self, bundle):
        bundle.db["batch_upsert_annotations"].side_effect = RuntimeError("boom")
        payload = bundle.mod.BatchUpsertRequest()
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.batch_upsert_annotations_api(
                agent_evaluation_id=100, payload=payload
            )
        assert exc.value.code == bundle.ErrorCode.SYSTEM_INTERNAL_ERROR

    async def test_app_exception_propagates(self, bundle):
        bundle.db["batch_upsert_annotations"].side_effect = bundle.AppException(
            "BIZ_CODE", "inner"
        )
        payload = bundle.mod.BatchUpsertRequest()
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.batch_upsert_annotations_api(
                agent_evaluation_id=100, payload=payload
            )
        assert exc.value.code == "BIZ_CODE"


class TestDeleteAnnotations:
    async def test_success(self, bundle):
        bundle.db["delete_annotations_by_evaluation_schema"].return_value = 4
        resp = await bundle.mod.delete_annotations_api(
            agent_evaluation_id=100, schema_id=1
        )
        assert resp.status_code == 200
        assert _resp_json(resp)["data"] == {"deleted": 4}
        bundle.db["delete_annotations_by_evaluation_schema"].assert_called_once_with(
            tenant_id="t1", agent_evaluation_id=100, schema_id=1
        )

    async def test_unauthorized(self, bundle):
        bundle.auth.side_effect = bundle.UnauthorizedError("no")
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.delete_annotations_api(agent_evaluation_id=100, schema_id=1)
        assert exc.value.code == bundle.ErrorCode.COMMON_UNAUTHORIZED

    async def test_internal_error(self, bundle):
        bundle.db["delete_annotations_by_evaluation_schema"].side_effect = RuntimeError("boom")
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.delete_annotations_api(agent_evaluation_id=100, schema_id=1)
        assert exc.value.code == bundle.ErrorCode.SYSTEM_INTERNAL_ERROR

    async def test_app_exception_propagates(self, bundle):
        bundle.db["delete_annotations_by_evaluation_schema"].side_effect = bundle.AppException(
            "BIZ_CODE", "inner"
        )
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.delete_annotations_api(agent_evaluation_id=100, schema_id=1)
        assert exc.value.code == "BIZ_CODE"


class TestAnnotationStats:
    async def test_success_with_data(self, bundle):
        bundle.db["get_annotation_values"].return_value = ["pass", "pass", "fail"]
        resp = await bundle.mod.get_annotation_stats_api(
            agent_evaluation_id=100, schema_id=1
        )
        assert resp.status_code == 200
        data = _resp_json(resp)["data"]
        assert data == [
            {"value": "pass", "count": 2, "ratio": 0.67},
            {"value": "fail", "count": 1, "ratio": 0.33},
        ]

    async def test_success_empty(self, bundle):
        bundle.db["get_annotation_values"].return_value = []
        resp = await bundle.mod.get_annotation_stats_api(
            agent_evaluation_id=100, schema_id=1
        )
        assert _resp_json(resp)["data"] == []

    async def test_internal_error(self, bundle):
        bundle.db["get_annotation_values"].side_effect = RuntimeError("boom")
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.get_annotation_stats_api(
                agent_evaluation_id=100, schema_id=1
            )
        assert exc.value.code == bundle.ErrorCode.SYSTEM_INTERNAL_ERROR

    async def test_unauthorized(self, bundle):
        bundle.auth.side_effect = bundle.UnauthorizedError("no")
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.get_annotation_stats_api(
                agent_evaluation_id=100, schema_id=1
            )
        assert exc.value.code == bundle.ErrorCode.COMMON_UNAUTHORIZED

    async def test_app_exception_propagates(self, bundle):
        bundle.db["get_annotation_values"].side_effect = bundle.AppException(
            "BIZ_CODE", "inner"
        )
        with pytest.raises(bundle.AppException) as exc:
            await bundle.mod.get_annotation_stats_api(
                agent_evaluation_id=100, schema_id=1
            )
        assert exc.value.code == "BIZ_CODE"
