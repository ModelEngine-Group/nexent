"""Unit tests for the new DELETE endpoints on agent_evaluation_app
and evaluation_set_app.

These tests run in their own subprocess via ``conftest.py`` (see
``test/conftest_app_delete.py``) so the heavy stubbing required to load
``apps.agent_evaluation_app`` and ``apps.evaluation_set_app`` does not
pollute the in-process test environment for other service tests.
"""
import os
import sys
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../../backend"))
sys.path.insert(0, backend_dir)


# ---------------------------------------------------------------------------
# Stub heavy / optional modules before they are imported.
# ---------------------------------------------------------------------------
from unittest.mock import MagicMock as _MagicMock  # noqa: E402

# boto3 / botocore (imported transitively by the SDK chain).
sys.modules.setdefault("boto3", _MagicMock())
sys.modules.setdefault("botocore", _MagicMock())
sys.modules.setdefault("botocore.client", _MagicMock())
sys.modules.setdefault("botocore.exceptions", _MagicMock())

# xlrd is an optional dep used by utils.evaluation_set_excel_utils.
sys.modules.setdefault("xlrd", _MagicMock())

# openjiuwen is an optional SDK used by adapters.jiuwen_sdk_adapter.
sys.modules.setdefault("openjiuwen", _MagicMock())


# ---------------------------------------------------------------------------
# Pre-import the modules we patch so they are present in ``sys.modules``
# and survive any test pollution from sibling test files.
# ---------------------------------------------------------------------------
import importlib  # noqa: E402


def _safe_import(name):
    try:
        return importlib.import_module(name)
    except Exception:  # noqa: BLE001
        return None


def _ensure_attr(parent_name: str, child_name: str):
    parent = sys.modules.get(parent_name)
    if parent is None:
        return
    if not hasattr(parent, child_name):
        child = _safe_import(f"{parent_name}.{child_name}")
        if child is not None:
            setattr(parent, child_name, child)


for _name in ("services", "utils", "apps"):
    _safe_import(_name)

for _parent, _children in (
    ("services", ("agent_evaluation_service", "evaluation_set_service")),
    ("utils", ("auth_utils", "evaluation_set_excel_utils")),
):
    for _child in _children:
        _ensure_attr(_parent, _child)


_PATCH_TARGETS = [
    "services.agent_evaluation_service.delete_agent_evaluation_run_impl",
    "services.evaluation_set_service.delete_evaluation_set_impl",
    "utils.auth_utils.get_current_user_id",
    "services.agent_evaluation_service.create_agent_evaluation_run_impl",
    "services.agent_evaluation_service.generate_agent_evaluation_report_impl",
    "services.agent_evaluation_service.get_agent_evaluation_run_impl",
    "services.agent_evaluation_service.list_agent_evaluation_cases_impl",
    "services.agent_evaluation_service.list_agent_evaluations_by_agent_impl",
    "services.evaluation_set_service.create_evaluation_set_from_cases",
    "services.evaluation_set_service.create_evaluation_set_from_jsonl",
    "services.evaluation_set_service.get_evaluation_set_impl",
    "services.evaluation_set_service.list_evaluation_set_cases_impl",
    "services.evaluation_set_service.list_evaluation_sets_impl",
]


def _build_app():
    app = FastAPI()
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

    def test_delete_agent_evaluation_success(self):
        resp = self.client.delete("/agent-evaluations/42")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"message": "Success"})
        _DELETE_EVAL_MOCK.assert_called_once_with(
            agent_evaluation_id=42,
            tenant_id="t1",
            user_id="u1",
        )

    def test_delete_agent_evaluation_forbidden_returns_400(self):
        _DELETE_EVAL_MOCK.side_effect = ValueError(
            "Only the creator can delete this evaluation run"
        )
        resp = self.client.delete("/agent-evaluations/42")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Only the creator", resp.json()["detail"])

    def test_delete_agent_evaluation_internal_error_returns_500(self):
        _DELETE_EVAL_MOCK.side_effect = RuntimeError("db boom")
        resp = self.client.delete("/agent-evaluations/42")
        self.assertEqual(resp.status_code, 500)

    def test_delete_evaluation_set_success(self):
        resp = self.client.delete("/evaluation-sets/9")
        self.assertEqual(resp.status_code, 200)
        _DELETE_SET_MOCK.assert_called_once_with(9, "t1", "u1")

    def test_delete_evaluation_set_blocked_by_referenced_runs(self):
        _DELETE_SET_MOCK.side_effect = ValueError(
            "evaluation set is referenced by 3 evaluation run(s); cannot delete"
        )
        resp = self.client.delete("/evaluation-sets/9")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("referenced by 3", resp.json()["detail"])

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
            evaluation_set_id=9,
            judge_model_id=3,
        )

    def test_create_agent_evaluation_value_error_returns_400(self):
        self.mocks[3].side_effect = ValueError("evaluation set has no cases")
        resp = self.client.post(
            "/agent-evaluations",
            json={"agent_id": 7, "evaluation_set_id": 9, "judge_model_id": 3},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("no cases", resp.json()["detail"])

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
            "/agent-evaluations", params={"agent_id": 7, "limit": 10, "offset": 5},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"], [{"agent_evaluation_id": 1}])
        list_mock.assert_called_once_with(
            agent_id=7, tenant_id="t1", limit=10, offset=5,
        )

    def test_list_agent_evaluations_default_pagination(self):
        list_mock = self.mocks[7]
        list_mock.return_value = []
        resp = self.client.get("/agent-evaluations", params={"agent_id": 7})
        self.assertEqual(resp.status_code, 200)
        list_mock.assert_called_once_with(
            agent_id=7, tenant_id="t1", limit=50, offset=0,
        )

    def test_list_agent_evaluations_invalid_pagination_returns_422(self):
        resp = self.client.get(
            "/agent-evaluations", params={"agent_id": 7, "limit": 0},
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
            agent_evaluation_id=1, tenant_id="t1",
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
            "/agent-evaluations/1/cases", params={"limit": 5, "offset": 2},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json()["data"], [{"agent_evaluation_case_id": 1}],
        )
        cases_mock.assert_called_once_with(
            agent_evaluation_id=1, tenant_id="t1", limit=5, offset=2,
        )

    def test_list_agent_evaluation_cases_invalid_pagination_returns_422(self):
        resp = self.client.get(
            "/agent-evaluations/1/cases", params={"limit": 0},
        )
        self.assertEqual(resp.status_code, 422)

    # ------------------------------------------------------------------
    # ``GET /agent-evaluations/{id}/report`` — download Excel
    # ------------------------------------------------------------------
    def test_download_report_failed_cases_uses_failed_suffix(self):
        report_mock = self.mocks[4]  # generate_agent_evaluation_report_impl
        report_mock.return_value = (b"xlsx-bytes", 4)
        resp = self.client.get("/agent-evaluations/1/report")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b"xlsx-bytes")
        self.assertIn(
            "evaluation_report_1_failed.xlsx",
            resp.headers["Content-Disposition"],
        )
        report_mock.assert_called_once_with(
            agent_evaluation_id=1, tenant_id="t1",
        )

    def test_download_report_clean_run_uses_all_suffix(self):
        self.mocks[4].return_value = (b"xlsx-bytes", 0)
        resp = self.client.get("/agent-evaluations/1/report")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(
            "evaluation_report_1_all.xlsx",
            resp.headers["Content-Disposition"],
        )

    def test_download_report_value_error_returns_404(self):
        self.mocks[4].side_effect = ValueError("agent evaluation not found")
        resp = self.client.get("/agent-evaluations/1/report")
        self.assertEqual(resp.status_code, 404)
        self.assertIn("not found", resp.json()["detail"])

    def test_download_report_internal_error_returns_500(self):
        self.mocks[4].side_effect = RuntimeError("disk full")
        resp = self.client.get("/agent-evaluations/1/report")
        self.assertEqual(resp.status_code, 500)


if __name__ == "__main__":
    unittest.main()
