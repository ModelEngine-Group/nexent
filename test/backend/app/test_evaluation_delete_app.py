"""HTTP endpoint tests for agent evaluations and evaluation sets.

The project runner executes each file in a separate process. Service and
persistence stubs keep these tests focused on real routers and error mapping.
"""

import importlib
import os
import sys
import types
import unittest
from unittest.mock import MagicMock as _MagicMock
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../../backend"))
sys.path.insert(0, backend_dir)


# Isolate service and persistence boundaries before loading the real routers.
_STUB_SYMBOLS = {
    "services.agent_evaluation_service": (
        "create_agent_evaluation_run_impl", "delete_agent_evaluation_run_impl",
        "generate_analysis_report_impl", "get_agent_evaluation_run_impl",
        "get_evaluation_stats_impl", "list_agent_evaluation_cases_impl",
        "list_agent_evaluations_by_agent_impl", "trial_run_evaluator_impl",
    ),
    "services.evaluation_report_service": ("generate_agent_evaluation_report_impl",),
    "services.evaluation_set_service": (
        "_generate_cases_async", "_update_generation_status", "add_evaluation_set_case_impl",
        "batch_delete_evaluation_set_cases_impl", "count_active_runs_using_set",
        "count_evaluation_sets_impl", "create_empty_evaluation_set", "create_evaluation_set_from_cases",
        "delete_evaluation_set_case_impl", "delete_evaluation_set_impl", "export_evaluation_set_impl",
        "get_evaluation_set_impl", "list_evaluation_set_cases_impl", "list_evaluation_sets_impl",
        "update_evaluation_set_case_impl",
    ),
    "database.agent_evaluation_db": ("update_annotation_schema_ids",),
    "utils.auth_utils": ("get_current_user_id", "get_current_user_info"),
    "utils.evaluation_set_excel_utils": (
        "build_evaluation_set_excel_template_bytes", "parse_evaluation_cases_from_excel",
    ),
    "utils.thread_utils": ("pool",),
}
for _module_name, _symbols in _STUB_SYMBOLS.items():
    _module = types.ModuleType(_module_name)
    for _symbol in _symbols:
        setattr(_module, _symbol, _MagicMock())
    sys.modules[_module_name] = _module
    _parent_name, _child_name = _module_name.rsplit(".", 1)
    setattr(importlib.import_module(_parent_name), _child_name, _module)


# Patched symbol index map (kept in sync with ``_PATCH_TARGETS``):
#  0  delete_agent_evaluation_run_impl
#  1  delete_evaluation_set_impl
#  2  get_current_user_id            → ("u1", "t1")
#  3  create_agent_evaluation_run_impl
#  4  generate_agent_evaluation_report_impl  (PDF report builder)
#  5  get_agent_evaluation_run_impl
#  6  list_agent_evaluation_cases_impl
#  7  list_agent_evaluations_by_agent_impl
#  8  create_evaluation_set_from_cases
#  9  create_empty_evaluation_set
# 10  get_evaluation_set_impl
# 11  list_evaluation_set_cases_impl
# 12  list_evaluation_sets_impl
# 13  get_current_user_info          → ("u1", "t1", "zh")
_PATCH_TARGETS = [
    "services.agent_evaluation_service.delete_agent_evaluation_run_impl",
    "services.evaluation_set_service.delete_evaluation_set_impl",
    "utils.auth_utils.get_current_user_id",
    "services.agent_evaluation_service.create_agent_evaluation_run_impl",
    "services.evaluation_report_service.generate_agent_evaluation_report_impl",
    "services.agent_evaluation_service.get_agent_evaluation_run_impl",
    "services.agent_evaluation_service.list_agent_evaluation_cases_impl",
    "services.agent_evaluation_service.list_agent_evaluations_by_agent_impl",
    "services.evaluation_set_service.create_evaluation_set_from_cases",
    "services.evaluation_set_service.create_empty_evaluation_set",
    "services.evaluation_set_service.get_evaluation_set_impl",
    "services.evaluation_set_service.list_evaluation_set_cases_impl",
    "services.evaluation_set_service.list_evaluation_sets_impl",
    "utils.auth_utils.get_current_user_info",
]


def _build_app():
    app = FastAPI()
    # Register the global exception handler middleware so that
    # ``AppException`` raised by endpoints is translated to a JSON HTTP
    # response (matching production behaviour) instead of propagating out
    # of ``TestClient`` as a raw exception.
    from middleware.exception_handler import ExceptionHandlerMiddleware

    app.add_middleware(ExceptionHandlerMiddleware)
    from apps.agent_evaluation_app import router as eval_router
    from apps.evaluation_set_app import router as set_router

    app.include_router(eval_router)
    app.include_router(set_router)
    return app


_DELETE_EVAL_MOCK = None
_DELETE_SET_MOCK = None


class TestEvaluationDeleteEndpoints(unittest.TestCase):
    patchers = None
    mocks = None

    @classmethod
    def setUpClass(cls):
        cls.patchers = []
        cls.mocks = []
        for target in _PATCH_TARGETS:
            p = patch(target)
            cls.patchers.append(p)
            cls.mocks.append(p.start())
        cls.mocks[2].return_value = ("u1", "t1")
        cls.mocks[13].return_value = ("u1", "t1", "zh")
        global _DELETE_EVAL_MOCK, _DELETE_SET_MOCK
        _DELETE_EVAL_MOCK = cls.mocks[0]
        _DELETE_SET_MOCK = cls.mocks[1]
        # Touch the service modules so the patched attribute is observed
        # by any subsequent import that re-resolves the doted path. Without
        # this the module's ``delete_*_impl`` symbol is still bound to the
        # real function in the imported apps modules' namespaces, and
        # patches appear to be ignored.
        import services.agent_evaluation_service as _svc_a
        import services.evaluation_set_service as _svc_b

        assert _svc_a.delete_agent_evaluation_run_impl is _DELETE_EVAL_MOCK
        assert _svc_b.delete_evaluation_set_impl is _DELETE_SET_MOCK

    @classmethod
    def tearDownClass(cls):
        for p in cls.patchers:
            try:
                p.stop()
            except RuntimeError:
                pass

    def setUp(self):
        # Clear any cached apps modules so the fresh import below re-binds
        # the ``*_impl`` symbols to the (already patched) mock objects.
        for mod in [
            "apps.agent_evaluation_app",
            "apps.evaluation_set_app",
        ]:
            sys.modules.pop(mod, None)

        # Reset every mock so a previous test's ``side_effect`` /
        # ``return_value`` does not leak into this one. The first two mocks
        # (``delete_*_impl``) are also kept as module globals below for the
        # existing delete tests; reset them here too.
        for m in self.mocks:
            m.reset_mock(side_effect=True)
            m.side_effect = None
        _DELETE_EVAL_MOCK.reset_mock(side_effect=True)
        _DELETE_EVAL_MOCK.side_effect = None
        _DELETE_SET_MOCK.reset_mock(side_effect=True)
        _DELETE_SET_MOCK.side_effect = None
        self.app = _build_app()
        self.client = TestClient(self.app)

    # ------------------------------------------------------------------
    # Helpers — build the same ``AppException`` the service layer raises.
    # Service code never raises bare ``ValueError`` / ``RuntimeError``; it
    # always raises ``AppException`` with a specific ``ErrorCode``. Using
    # the real exception class keeps these tests faithful to production.
    # ------------------------------------------------------------------
    @staticmethod
    def _exc(error_code, message):
        from consts.exceptions import AppException

        return AppException(error_code, message)

    @staticmethod
    def _code(name):
        from consts.error_code import ErrorCode

        return getattr(ErrorCode, name)

    # ------------------------------------------------------------------
    # ``DELETE /agent-evaluations/{id}``
    # ------------------------------------------------------------------
    def test_delete_agent_evaluation_success(self):
        resp = self.client.delete("/agent-evaluations/42")
        self.assertEqual(resp.status_code, 200)
        # ``_ok()`` wraps the payload as {"message": "Success", "data": ...}
        self.assertEqual(resp.json(), {"message": "Success", "data": None})
        _DELETE_EVAL_MOCK.assert_called_once_with(
            agent_evaluation_id=42,
            tenant_id="t1",
            user_id="u1",
        )

    def test_delete_agent_evaluation_forbidden_returns_403(self):
        # Service raises AGENT_EVALUATION_ONLY_CREATOR_CAN_DELETE (→403).
        _DELETE_EVAL_MOCK.side_effect = self._exc(
            self._code("AGENT_EVALUATION_ONLY_CREATOR_CAN_DELETE"),
            "Only the creator can delete this evaluation run",
        )
        resp = self.client.delete("/agent-evaluations/42")
        self.assertEqual(resp.status_code, 403)
        self.assertIn("Only the creator", resp.json()["message"])

    def test_delete_agent_evaluation_internal_error_returns_500(self):
        _DELETE_EVAL_MOCK.side_effect = RuntimeError("db boom")
        resp = self.client.delete("/agent-evaluations/42")
        self.assertEqual(resp.status_code, 500)

    # ------------------------------------------------------------------
    # ``DELETE /evaluation-sets/{id}``
    # ------------------------------------------------------------------
    def test_delete_evaluation_set_success(self):
        resp = self.client.delete("/evaluation-sets/9")
        self.assertEqual(resp.status_code, 200)
        _DELETE_SET_MOCK.assert_called_once_with(9, "t1", "u1")

    def test_delete_evaluation_set_blocked_by_referenced_runs(self):
        # Service raises AGENT_EVALUATION_SET_IN_USE (→409) when the set
        # is still referenced by evaluation runs.
        exc = self._exc(
            self._code("AGENT_EVALUATION_SET_IN_USE"),
            "evaluation set is referenced by 3 evaluation run(s); cannot delete",
        )
        with patch.object(_DELETE_SET_MOCK, "side_effect", exc):
            resp = self.client.delete("/evaluation-sets/9")
        self.assertEqual(resp.status_code, 409)
        self.assertIn("referenced by 3", resp.json()["message"])

    # ------------------------------------------------------------------
    # ``POST /agent-evaluations`` — create a new evaluation run
    # ------------------------------------------------------------------
    def test_create_agent_evaluation_success(self):
        create_mock = self.mocks[3]  # create_agent_evaluation_run_impl
        create_mock.return_value = {"agent_evaluation_id": 1}
        resp = self.client.post(
            "/agent-evaluations",
            json={"agent_id": 7, "evaluation_set_id": 9, "judge_model_id": 3},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"], {"agent_evaluation_id": 1})
        create_mock.assert_called_once_with(
            tenant_id="t1",
            user_id="u1",
            agent_id=7,
            judge_model_id=3,
            evaluation_set_id=9,
            agent_version_no=None,
            evaluator_ids=None,
            field_mappings=None,
            query_count=10,
            language="zh",
        )

    def test_create_agent_evaluation_value_error_returns_400(self):
        # Service raises COMMON_VALIDATION_ERROR (→400) for bad input.
        self.mocks[3].side_effect = self._exc(
            self._code("COMMON_VALIDATION_ERROR"),
            "evaluation set has no cases",
        )
        resp = self.client.post(
            "/agent-evaluations",
            json={"agent_id": 7, "evaluation_set_id": 9, "judge_model_id": 3},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("no cases", resp.json()["message"])

    def test_create_agent_evaluation_unexpected_error_returns_500(self):
        self.mocks[3].side_effect = RuntimeError("db boom")
        resp = self.client.post(
            "/agent-evaluations",
            json={"agent_id": 7, "evaluation_set_id": 9, "judge_model_id": 3},
        )
        self.assertEqual(resp.status_code, 500)

    # ------------------------------------------------------------------
    # ``GET /agent-evaluations?agent_id=...`` — list runs for an agent
    # ------------------------------------------------------------------
    def test_list_agent_evaluations_forwards_query(self):
        list_mock = self.mocks[7]  # list_agent_evaluations_by_agent_impl
        list_mock.return_value = [{"agent_evaluation_id": 1}]
        resp = self.client.get(
            "/agent-evaluations",
            params={"agent_id": 7, "limit": 10, "offset": 5},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"], [{"agent_evaluation_id": 1}])
        list_mock.assert_called_once_with(
            agent_id=7,
            tenant_id="t1",
            limit=10,
            offset=5,
        )

    def test_list_agent_evaluations_default_pagination(self):
        list_mock = self.mocks[7]
        list_mock.return_value = []
        resp = self.client.get("/agent-evaluations", params={"agent_id": 7})
        self.assertEqual(resp.status_code, 200)
        list_mock.assert_called_once_with(
            agent_id=7,
            tenant_id="t1",
            limit=50,
            offset=0,
        )

    def test_list_agent_evaluations_invalid_pagination_returns_422(self):
        # ``limit`` is clamped to [0, 200]; 0 now means "full result set",
        # so a genuinely out-of-range value is required to trigger 422.
        resp = self.client.get(
            "/agent-evaluations",
            params={"agent_id": 7, "limit": -1},
        )
        self.assertEqual(resp.status_code, 422)

    # ------------------------------------------------------------------
    # ``GET /agent-evaluations/{id}`` — fetch a single run
    # ------------------------------------------------------------------
    def test_get_agent_evaluation_success(self):
        get_mock = self.mocks[5]  # get_agent_evaluation_run_impl
        get_mock.return_value = {"agent_evaluation_id": 1, "status": "RUNNING"}
        resp = self.client.get("/agent-evaluations/1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json()["data"],
            {"agent_evaluation_id": 1, "status": "RUNNING"},
        )
        get_mock.assert_called_once_with(
            agent_evaluation_id=1,
            tenant_id="t1",
        )

    def test_get_agent_evaluation_internal_error_returns_500(self):
        self.mocks[5].side_effect = RuntimeError("db boom")
        resp = self.client.get("/agent-evaluations/1")
        self.assertEqual(resp.status_code, 500)

    # ------------------------------------------------------------------
    # ``GET /agent-evaluations/{id}/cases`` — list cases for a run
    # ------------------------------------------------------------------
    def test_list_agent_evaluation_cases_success(self):
        cases_mock = self.mocks[6]  # list_agent_evaluation_cases_impl
        cases_mock.return_value = [{"agent_evaluation_case_id": 1}]
        resp = self.client.get(
            "/agent-evaluations/1/cases",
            params={"limit": 5, "offset": 2},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json()["data"],
            [{"agent_evaluation_case_id": 1}],
        )
        cases_mock.assert_called_once_with(
            agent_evaluation_id=1,
            tenant_id="t1",
            limit=5,
            offset=2,
            sort_by=None,
            sort_order="asc",
            pass_filter=None,
            anno_schema_ids=[],
            anno_values=[],
            session_id=None,
        )

    def test_list_agent_evaluation_cases_invalid_pagination_returns_422(self):
        resp = self.client.get(
            "/agent-evaluations/1/cases",
            params={"limit": 0},
        )
        self.assertEqual(resp.status_code, 422)

    # ------------------------------------------------------------------
    # ``GET /agent-evaluations/{id}/report`` — download localized PDF
    # The endpoint now streams a PDF (was Excel); the filename no longer
    # distinguishes failed/all suffixes.
    # ------------------------------------------------------------------
    def test_download_report_failed_cases_uses_failed_suffix(self):
        report_mock = self.mocks[4]  # generate_agent_evaluation_report_impl
        report_mock.return_value = (b"pdf-bytes", 4)
        resp = self.client.get("/agent-evaluations/1/report")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b"pdf-bytes")
        self.assertEqual(resp.headers["content-type"], "application/pdf")
        self.assertIn(
            "evaluation_report_1.pdf",
            resp.headers["Content-Disposition"],
        )
        report_mock.assert_called_once_with(
            agent_evaluation_id=1,
            tenant_id="t1",
            language="zh",
        )

    def test_download_report_clean_run_uses_all_suffix(self):
        self.mocks[4].return_value = (b"pdf-bytes", 0)
        resp = self.client.get("/agent-evaluations/1/report")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["content-type"], "application/pdf")
        self.assertIn(
            "evaluation_report_1.pdf",
            resp.headers["Content-Disposition"],
        )

    def test_download_report_value_error_returns_404(self):
        # Service raises COMMON_RESOURCE_NOT_FOUND (→404) when the run
        # does not exist.
        self.mocks[4].side_effect = self._exc(
            self._code("COMMON_RESOURCE_NOT_FOUND"),
            "agent evaluation not found",
        )
        resp = self.client.get("/agent-evaluations/1/report")
        self.assertEqual(resp.status_code, 404)
        self.assertIn("not found", resp.json()["message"])

    def test_download_report_internal_error_returns_500(self):
        self.mocks[4].side_effect = RuntimeError("disk full")
        resp = self.client.get("/agent-evaluations/1/report")
        self.assertEqual(resp.status_code, 500)


if __name__ == "__main__":
    unittest.main()
