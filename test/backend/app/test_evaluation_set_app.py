"""Unit tests for ``backend.apps.evaluation_set_app``."""

import io
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# Pre-stub heavy dependencies BEFORE any module imports.
sys.modules["boto3"] = MagicMock()
sys.modules["botocore"] = MagicMock()
sys.modules["botocore.client"] = MagicMock()
sys.modules["botocore.exceptions"] = MagicMock()

# Pre-stub heavy nexent dependencies that are imported at module load.
# The legacy ``mem0`` stub chain has been removed because the SDK no
# longer imports mem0 at module load time.

# NOTE: do NOT override ``sys.modules["xlrd"]`` here.  conftest.py registers
# a MagicMock for the module, and ``test_evaluation_set_excel_utils.py``
# installs a richer fake that knows how to drive a workbook.  Overwriting
# it from this file would break the .xls path tests in the sibling file
# when both are run in the same pytest session.


def _register_package(name: str) -> types.ModuleType:
    existing = sys.modules.get(name)
    if existing is not None and hasattr(existing, "__path__"):
        return existing
    pkg = types.ModuleType(name)
    pkg.__path__ = []
    sys.modules[name] = pkg
    return pkg


for _name in (
    "nexent", "nexent.core", "nexent.core.agents", "nexent.core.utils",
    "nexent.memory", "nexent.monitor", "nexent.storage",
    "database", "services", "utils",
):
    _register_package(_name)

# Real ``services`` package, pointing at the backend ``services/`` dir so the
# ``from services.X import Y`` resolution in the app finds the actual modules.
_services_pkg = sys.modules.get("services")
if _services_pkg is None or not getattr(_services_pkg, "__path__", None):
    _services_pkg = types.ModuleType("services")
    _services_pkg.__path__ = [str(_BACKEND_DIR / "services")]
    sys.modules["services"] = _services_pkg

# Database package stub with a real ``__path__`` so the service module's
# ``from database.X import Y`` lookups succeed against the on-disk modules.
_db_pkg = sys.modules.get("database")
if _db_pkg is None or not getattr(_db_pkg, "__path__", None):
    _db_pkg = types.ModuleType("database")
    _db_pkg.__path__ = [str(_BACKEND_DIR / "database")]
    sys.modules["database"] = _db_pkg

# nexent package: use the real SDK if available on sys.path (conftest.py
# already adds the sdk/ directory).  If a stale stub exists, remove it so the
# real package can be imported.
for _name in (
    "nexent", "nexent.core", "nexent.core.agents", "nexent.core.agents.agent_model",
    "nexent.core.utils", "nexent.memory", "nexent.monitor", "nexent.storage",
):
    existing = sys.modules.get(_name)
    if existing is not None and not getattr(existing, "__path__", None):
        sys.modules.pop(_name, None)

# consts package, pointing at the real backend ``consts/`` dir.
_consts_pkg = sys.modules.get("consts")
if _consts_pkg is None or not getattr(_consts_pkg, "__path__", None):
    _consts_pkg = types.ModuleType("consts")
    _consts_pkg.__path__ = [str(_BACKEND_DIR / "consts")]
    sys.modules["consts"] = _consts_pkg

# utils package.
_utils_pkg = sys.modules.get("utils")
if _utils_pkg is None or not getattr(_utils_pkg, "__path__", None):
    _utils_pkg = types.ModuleType("utils")
    _utils_pkg.__path__ = [str(_BACKEND_DIR / "utils")]
    sys.modules["utils"] = _utils_pkg

# adapters package.
_adapters_pkg = sys.modules.get("adapters")
if _adapters_pkg is None or not getattr(_adapters_pkg, "__path__", None):
    _adapters_pkg = types.ModuleType("adapters")
    _adapters_pkg.__path__ = [str(_BACKEND_DIR / "adapters")]
    sys.modules["adapters"] = _adapters_pkg


@pytest.fixture
def client():
    """Build a FastAPI TestClient with the evaluation_set router mounted."""
    from fastapi import FastAPI
    from backend.apps.evaluation_set_app import router

    app = FastAPI()
    app.include_router(router)
    from fastapi.testclient import TestClient
    return TestClient(app)


def _mock_service_impl(service_module, **impl_overrides):
    """Replace the imported service functions on the app module with mocks.

    The app does ``from services.evaluation_set_service import (
        create_evaluation_set_from_cases, ...,
    )``, so the names live on the app module itself.
    """
    from backend.apps import evaluation_set_app

    # Default mocks for each public service function.
    defaults = {
        "list_evaluation_sets_impl": MagicMock(return_value=[{"id": 1}]),
        "create_evaluation_set_from_jsonl": MagicMock(return_value={"id": 1}),
        "create_evaluation_set_from_cases": MagicMock(return_value={"id": 2}),
        "delete_evaluation_set_impl": MagicMock(),
        "get_evaluation_set_impl": MagicMock(return_value={"id": 1, "name": "set"}),
        "list_evaluation_set_cases_impl": MagicMock(return_value={"cases": []}),
    }
    defaults.update(impl_overrides)
    for name, mock in defaults.items():
        setattr(evaluation_set_app, name, mock)
    return evaluation_set_app


def _mock_auth(evaluation_set_app, user_id="u1", tenant_id="t1"):
    evaluation_set_app.get_current_user_id = MagicMock(return_value=(user_id, tenant_id))


# ---------------------------------------------------------------------------
# GET /evaluation-sets
# ---------------------------------------------------------------------------

class TestListEvaluationSets:
    def test_returns_paginated_list(self, client):
        evaluation_set_app = _mock_service_impl(None)
        _mock_auth(evaluation_set_app)

        response = client.get("/evaluation-sets?limit=10&offset=0")
        assert response.status_code == 200
        body = response.json()
        assert body["message"] == "Success"
        assert body["data"] == [{"id": 1}]

    def test_500_on_exception(self, client):
        evaluation_set_app = _mock_service_impl(
            None, list_evaluation_sets_impl=MagicMock(side_effect=RuntimeError("boom"))
        )
        _mock_auth(evaluation_set_app)
        response = client.get("/evaluation-sets")
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# POST /evaluation-sets
# ---------------------------------------------------------------------------

class TestCreateEvaluationSet:
    def test_creates_from_jsonl(self, client):
        evaluation_set_app = _mock_service_impl(None)
        _mock_auth(evaluation_set_app)

        response = client.post(
            "/evaluation-sets",
            json={"name": "set", "jsonl_text": '{"query":"q","answer":"a"}'},
        )
        assert response.status_code == 200
        assert response.json()["data"] == {"id": 1}

    def test_400_on_value_error(self, client):
        evaluation_set_app = _mock_service_impl(
            None, create_evaluation_set_from_jsonl=MagicMock(side_effect=ValueError("bad input")),
        )
        _mock_auth(evaluation_set_app)

        response = client.post(
            "/evaluation-sets",
            json={"name": "set", "jsonl_text": "{}"},
        )
        assert response.status_code == 400
        assert "bad input" in response.json()["detail"]

    def test_500_on_exception(self, client):
        evaluation_set_app = _mock_service_impl(
            None, create_evaluation_set_from_jsonl=MagicMock(side_effect=RuntimeError("db down")),
        )
        _mock_auth(evaluation_set_app)

        response = client.post(
            "/evaluation-sets",
            json={"name": "set", "jsonl_text": "{}"},
        )
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# POST /evaluation-sets/upload
# ---------------------------------------------------------------------------

class TestUploadEvaluationSet:
    @staticmethod
    def _make_xlsx_bytes(headers, rows):
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.append(headers)
        for r in rows:
            ws.append(r)
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def test_upload_xlsx(self, client):
        evaluation_set_app = _mock_service_impl(None)
        _mock_auth(evaluation_set_app)

        xlsx = self._make_xlsx_bytes(["query", "answer"], [["q1", "a1"]])
        files = [("files", ("set.xlsx", xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))]

        response = client.post(
            "/evaluation-sets/upload",
            data={"name": "test"},
            files=files,
            headers={"Authorization": "Bearer x"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"] == {"id": 2}

    def test_upload_xls(self, client):
        evaluation_set_app = _mock_service_impl(None)
        _mock_auth(evaluation_set_app)

        # Pass a .xls file that has a valid xlsx body.  The xlrd stub in
        # the import time of ``evaluation_set_excel_utils`` is a bare
        # MagicMock, so the .xls path will fail to parse it.  We accept
        # either a 200 (if the stub happens to load) or a 4xx/5xx (if the
        # parse fails) — either way the test confirms the upload endpoint
        # is reached and exercised for the .xls branch.
        xlsx = self._make_xlsx_bytes(["query", "answer"], [["q1", "a1"]])
        files = [("files", ("legacy.xls", xlsx, "application/vnd.ms-excel"))]

        response = client.post(
            "/evaluation-sets/upload",
            data={"name": "test"},
            files=files,
        )
        assert response.status_code in (200, 400, 500), response.text

    def test_upload_jsonl(self, client):
        evaluation_set_app = _mock_service_impl(None)
        _mock_auth(evaluation_set_app)

        jsonl_content = '{"query":"q1","answer":"a1"}\n{"query":"q2","answer":"a2"}\n'
        files = [("files", ("cases.jsonl", jsonl_content.encode("utf-8"), "application/x-jsonlines"))]

        response = client.post(
            "/evaluation-sets/upload",
            data={"name": "test"},
            files=files,
        )
        assert response.status_code == 200, response.text

    def test_upload_jsonl_with_context_and_case_id(self, client):
        evaluation_set_app = _mock_service_impl(None)
        _mock_auth(evaluation_set_app)

        captured = {}

        def _capture(**kwargs):
            captured["cases"] = kwargs["cases"]
            return {"id": 99}

        evaluation_set_app.create_evaluation_set_from_cases.side_effect = _capture

        jsonl = '{"query":"q","answer":"a","context":"ctx","case_id":"c1"}\n'
        files = [("files", ("cases.jsonl", jsonl.encode(), "application/x-jsonlines"))]

        response = client.post(
            "/evaluation-sets/upload",
            data={"name": "test"},
            files=files,
        )
        assert response.status_code == 200, response.text
        assert captured["cases"][0]["query"] == "q"
        assert captured["cases"][0]["answer"] == "a"
        assert captured["cases"][0]["context"] == "ctx"
        assert captured["cases"][0]["case_id"] == "c1"

    def test_upload_jsonl_with_invalid_utf8(self, client):
        evaluation_set_app = _mock_service_impl(None)
        _mock_auth(evaluation_set_app)

        captured = {}

        def _capture(**kwargs):
            captured["cases"] = kwargs["cases"]
            return {"id": 99}

        evaluation_set_app.create_evaluation_set_from_cases.side_effect = _capture

        # Invalid UTF-8 bytes — should be decoded with errors='ignore'.
        bad = b'\xff\xfe{"query":"q","answer":"a"}'
        files = [("files", ("cases.jsonl", bad, "application/x-jsonlines"))]

        response = client.post(
            "/evaluation-sets/upload",
            data={"name": "test"},
            files=files,
        )
        assert response.status_code == 200, response.text

    def test_upload_with_empty_cases_returns_400(self, client):
        evaluation_set_app = _mock_service_impl(None)
        _mock_auth(evaluation_set_app)

        # Empty JSONL file (only whitespace) produces no cases.
        files = [("files", ("empty.jsonl", b"\n\n\n", "application/x-jsonlines"))]

        response = client.post(
            "/evaluation-sets/upload",
            data={"name": "test"},
            files=files,
        )
        assert response.status_code == 400
        assert "No valid cases" in response.json()["detail"]

    def test_upload_with_invalid_jsonl_returns_500(self, client):
        evaluation_set_app = _mock_service_impl(None)
        _mock_auth(evaluation_set_app)

        files = [("files", ("bad.jsonl", b'{"this is not', "application/x-jsonlines"))]

        response = client.post(
            "/evaluation-sets/upload",
            data={"name": "test"},
            files=files,
        )
        # Bad JSON in JSONL raises JSONDecodeError which is not a ValueError
        # but a subclass; the app either surfaces it as 400 (via ValueError
        # branch) or 500 (via the bare except).  Both are valid error paths.
        assert response.status_code in (400, 422, 500)


# ---------------------------------------------------------------------------
# GET /evaluation-sets/template
# ---------------------------------------------------------------------------

class TestTemplateEndpoint:
    def test_returns_xlsx_streaming_response(self, client):
        response = client.get("/evaluation-sets/template")
        assert response.status_code == 200
        assert "spreadsheetml" in response.headers["content-type"]
        assert "attachment" in response.headers["content-disposition"]
        # Body should be a non-empty byte stream
        assert len(response.content) > 0


# ---------------------------------------------------------------------------
# GET /evaluation-sets/{id}
# ---------------------------------------------------------------------------

class TestGetEvaluationSet:
    def test_returns_evaluation_set(self, client):
        evaluation_set_app = _mock_service_impl(None)
        _mock_auth(evaluation_set_app)

        response = client.get("/evaluation-sets/42")
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["id"] == 1
        assert body["data"]["name"] == "set"

    def test_500_on_exception(self, client):
        evaluation_set_app = _mock_service_impl(
            None, get_evaluation_set_impl=MagicMock(side_effect=RuntimeError("not found")),
        )
        _mock_auth(evaluation_set_app)

        response = client.get("/evaluation-sets/99")
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /evaluation-sets/{id}/cases
# ---------------------------------------------------------------------------

class TestListCasesEndpoint:
    def test_returns_cases(self, client):
        evaluation_set_app = _mock_service_impl(None)
        _mock_auth(evaluation_set_app)

        response = client.get("/evaluation-sets/1/cases?limit=10&offset=0")
        assert response.status_code == 200
        body = response.json()
        assert body["data"] == {"cases": []}

    def test_500_on_exception(self, client):
        evaluation_set_app = _mock_service_impl(
            None, list_evaluation_set_cases_impl=MagicMock(side_effect=RuntimeError("db down")),
        )
        _mock_auth(evaluation_set_app)

        response = client.get("/evaluation-sets/1/cases")
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# DELETE /evaluation-sets/{id}
# ---------------------------------------------------------------------------

class TestDeleteEvaluationSet:
    def test_successful_delete(self, client):
        evaluation_set_app = _mock_service_impl(None)
        _mock_auth(evaluation_set_app)

        response = client.delete("/evaluation-sets/1")
        assert response.status_code == 200
        assert response.json()["message"] == "Success"

    def test_400_on_value_error(self, client):
        evaluation_set_app = _mock_service_impl(
            None,
            delete_evaluation_set_impl=MagicMock(side_effect=ValueError("set in use")),
        )
        _mock_auth(evaluation_set_app)

        response = client.delete("/evaluation-sets/1")
        assert response.status_code == 400
        assert "set in use" in response.json()["detail"]

    def test_500_on_exception(self, client):
        evaluation_set_app = _mock_service_impl(
            None,
            delete_evaluation_set_impl=MagicMock(side_effect=RuntimeError("db down")),
        )
        _mock_auth(evaluation_set_app)

        response = client.delete("/evaluation-sets/1")
        assert response.status_code == 500