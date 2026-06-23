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


if __name__ == "__main__":
    unittest.main()
