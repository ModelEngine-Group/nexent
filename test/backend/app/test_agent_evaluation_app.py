"""Unit tests for ``backend.apps.agent_evaluation_app``."""

import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# Pre-stub heavy SDK dependencies BEFORE any module imports.
sys.modules["boto3"] = MagicMock()
sys.modules["botocore"] = MagicMock()
sys.modules["botocore.client"] = MagicMock()
sys.modules["botocore.exceptions"] = MagicMock()


def _register_package(name: str) -> types.ModuleType:
    existing = sys.modules.get(name)
    if existing is not None and hasattr(existing, "__path__"):
        return existing
    pkg = types.ModuleType(name)
    pkg.__path__ = []
    sys.modules[name] = pkg
    return pkg


# consts / middleware use the REAL backend packages; services / database /
# utils submodules that the app imports are stubbed so heavy SDK
# dependencies never load.
_consts_pkg = _register_package("consts")
_consts_pkg.__path__ = [str(_BACKEND_DIR / "consts")]
_middleware_pkg = _register_package("middleware")
_middleware_pkg.__path__ = [str(_BACKEND_DIR / "middleware")]

for _name in (
    "services",
    "services.agent_evaluation_service",
    "services.evaluation_report_service",
    "database",
    "database.agent_evaluation_db",
    "utils",
    "utils.auth_utils",
):
    _register_package(_name)
sys.modules["services.agent_evaluation_service"] = MagicMock(name="agent_eval_svc")
sys.modules["services.evaluation_report_service"] = MagicMock(name="report_svc")
sys.modules["database.agent_evaluation_db"] = MagicMock(name="agent_eval_db")
sys.modules["utils.auth_utils"] = MagicMock(name="auth_utils")

# Load the target module via spec so its ``from X import Y`` lookups hit the
# stubs above.
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "backend.apps.agent_evaluation_app",
    str(_BACKEND_DIR / "apps" / "agent_evaluation_app.py"),
)
agent_evaluation_app = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = agent_evaluation_app
_spec.loader.exec_module(agent_evaluation_app)


def _exc(error_code, message):
    from consts.exceptions import AppException

    return AppException(error_code, message)


def _code(name):
    from consts.error_code import ErrorCode

    return getattr(ErrorCode, name)


@pytest.fixture
def client():
    """Build a FastAPI TestClient with the agent-evaluation router mounted."""
    from fastapi import FastAPI
    from middleware.exception_handler import ExceptionHandlerMiddleware

    app = FastAPI()
    app.add_middleware(ExceptionHandlerMiddleware)
    app.include_router(agent_evaluation_app.router)
    from fastapi.testclient import TestClient

    return TestClient(app)


def _mock_impls(**overrides):
    """Replace the imported service/auth names on the app module with mocks."""
    defaults = {
        "get_current_user_id": MagicMock(return_value=("u1", "t1")),
        "get_current_user_info": MagicMock(return_value=("u1", "t1", "zh")),
        "create_agent_evaluation_run_impl": MagicMock(
            return_value={"agent_evaluation_id": 1}
        ),
        "delete_agent_evaluation_run_impl": MagicMock(),
        "generate_analysis_report_impl": MagicMock(return_value={"analysis": "ok"}),
        "get_agent_evaluation_run_impl": MagicMock(
            return_value={"agent_evaluation_id": 1, "status": "COMPLETED"}
        ),
        "get_evaluation_stats_impl": MagicMock(
            return_value={"per_evaluator": [], "histogram": []}
        ),
        "list_agent_evaluation_cases_impl": MagicMock(
            return_value={"items": [], "total": 0}
        ),
        "list_agent_evaluations_by_agent_impl": MagicMock(return_value=[{"id": 1}]),
        "trial_run_evaluator_impl": AsyncMock(return_value={"result": "ok"}),
        "generate_agent_evaluation_report_impl": MagicMock(
            return_value=(b"%PDF-1.4 fake", 0)
        ),
        "update_annotation_schema_ids": MagicMock(return_value=1),
    }
    defaults.update(overrides)
    for name, mock in defaults.items():
        setattr(agent_evaluation_app, name, mock)
    return agent_evaluation_app


# ---------------------------------------------------------------------------
# POST /agent-evaluations
# ---------------------------------------------------------------------------


class TestCreateEvaluation:
    def test_creates_run_with_set(self, client):
        app = _mock_impls()
        response = client.post(
            "/agent-evaluations",
            json={"agent_id": 1, "judge_model_id": 2, "evaluation_set_id": 3},
        )
        assert response.status_code == 200
        assert response.json()["data"] == {"agent_evaluation_id": 1}
        app.create_agent_evaluation_run_impl.assert_called_once()
        assert (
            app.create_agent_evaluation_run_impl.call_args.kwargs["evaluation_set_id"]
            == 3
        )

    def test_creates_run_no_set(self, client):
        app = _mock_impls()
        response = client.post(
            "/agent-evaluations",
            json={"agent_id": 1, "judge_model_id": 2, "query_count": 5},
        )
        assert response.status_code == 200
        assert app.create_agent_evaluation_run_impl.call_args.kwargs["query_count"] == 5

    def test_401_on_unauthorized(self, client):
        from consts.exceptions import UnauthorizedError

        _mock_impls(get_current_user_info=MagicMock(side_effect=UnauthorizedError()))
        response = client.post(
            "/agent-evaluations",
            json={"agent_id": 1, "judge_model_id": 2},
        )
        assert response.status_code == 401

    def test_500_on_exception(self, client):
        _mock_impls(
            create_agent_evaluation_run_impl=MagicMock(
                side_effect=RuntimeError("boom")
            )
        )
        response = client.post(
            "/agent-evaluations",
            json={"agent_id": 1, "judge_model_id": 2},
        )
        assert response.status_code == 500

    def test_app_exception_propagates(self, client):
        _mock_impls(
            create_agent_evaluation_run_impl=MagicMock(
                side_effect=_exc(_code("COMMON_RESOURCE_NOT_FOUND"), "missing")
            )
        )
        response = client.post(
            "/agent-evaluations",
            json={"agent_id": 1, "judge_model_id": 2},
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /agent-evaluations
# ---------------------------------------------------------------------------


class TestListEvaluations:
    def test_returns_list(self, client):
        _mock_impls()
        response = client.get("/agent-evaluations?agent_id=1&limit=10&offset=0")
        assert response.status_code == 200
        assert response.json()["data"] == [{"id": 1}]

    def test_500_on_exception(self, client):
        _mock_impls(
            list_agent_evaluations_by_agent_impl=MagicMock(
                side_effect=RuntimeError("boom")
            )
        )
        response = client.get("/agent-evaluations?agent_id=1")
        assert response.status_code == 500

    def test_401_on_unauthorized(self, client):
        from consts.exceptions import UnauthorizedError

        _mock_impls(get_current_user_id=MagicMock(side_effect=UnauthorizedError()))
        response = client.get("/agent-evaluations?agent_id=1")
        assert response.status_code == 401

    def test_app_exception_propagates(self, client):
        _mock_impls(
            list_agent_evaluations_by_agent_impl=MagicMock(
                side_effect=_exc(_code("COMMON_RESOURCE_NOT_FOUND"), "missing")
            )
        )
        response = client.get("/agent-evaluations?agent_id=1")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /agent-evaluations/{id}
# ---------------------------------------------------------------------------


class TestGetEvaluation:
    def test_returns_run(self, client):
        _mock_impls()
        response = client.get("/agent-evaluations/1")
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "COMPLETED"

    def test_404_when_not_found(self, client):
        _mock_impls(
            get_agent_evaluation_run_impl=MagicMock(
                side_effect=_exc(_code("COMMON_RESOURCE_NOT_FOUND"), "missing")
            )
        )
        response = client.get("/agent-evaluations/99")
        assert response.status_code == 404

    def test_500_on_exception(self, client):
        _mock_impls(
            get_agent_evaluation_run_impl=MagicMock(
                side_effect=RuntimeError("boom")
            )
        )
        response = client.get("/agent-evaluations/1")
        assert response.status_code == 500

    def test_401_on_unauthorized(self, client):
        from consts.exceptions import UnauthorizedError

        _mock_impls(get_current_user_id=MagicMock(side_effect=UnauthorizedError()))
        response = client.get("/agent-evaluations/1")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /agent-evaluations/{id}/cases
# ---------------------------------------------------------------------------


class TestListCases:
    def test_returns_paginated_cases(self, client):
        app = _mock_impls()
        response = client.get(
            "/agent-evaluations/1/cases?limit=10&sort_by=accuracy&pass_filter=pass"
        )
        assert response.status_code == 200
        kwargs = app.list_agent_evaluation_cases_impl.call_args.kwargs
        assert kwargs["sort_by"] == "accuracy"
        assert kwargs["pass_filter"] == "pass"

    def test_500_on_exception(self, client):
        _mock_impls(
            list_agent_evaluation_cases_impl=MagicMock(
                side_effect=RuntimeError("boom")
            )
        )
        response = client.get("/agent-evaluations/1/cases")
        assert response.status_code == 500

    def test_401_on_unauthorized(self, client):
        from consts.exceptions import UnauthorizedError

        _mock_impls(get_current_user_id=MagicMock(side_effect=UnauthorizedError()))
        response = client.get("/agent-evaluations/1/cases")
        assert response.status_code == 401

    def test_app_exception_propagates(self, client):
        _mock_impls(
            list_agent_evaluation_cases_impl=MagicMock(
                side_effect=_exc(_code("COMMON_RESOURCE_NOT_FOUND"), "missing")
            )
        )
        response = client.get("/agent-evaluations/1/cases")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /agent-evaluations/{id}/stats
# ---------------------------------------------------------------------------


class TestStats:
    def test_returns_stats(self, client):
        _mock_impls()
        response = client.get("/agent-evaluations/1/stats")
        assert response.status_code == 200
        assert response.json()["data"]["per_evaluator"] == []

    def test_500_on_exception(self, client):
        _mock_impls(get_evaluation_stats_impl=MagicMock(side_effect=RuntimeError("x")))
        response = client.get("/agent-evaluations/1/stats")
        assert response.status_code == 500

    def test_401_on_unauthorized(self, client):
        from consts.exceptions import UnauthorizedError

        _mock_impls(get_current_user_id=MagicMock(side_effect=UnauthorizedError()))
        response = client.get("/agent-evaluations/1/stats")
        assert response.status_code == 401

    def test_app_exception_propagates(self, client):
        _mock_impls(
            get_evaluation_stats_impl=MagicMock(
                side_effect=_exc(_code("COMMON_RESOURCE_NOT_FOUND"), "missing")
            )
        )
        response = client.get("/agent-evaluations/1/stats")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /agent-evaluations/{id}/report
# ---------------------------------------------------------------------------


class TestDownloadReport:
    def test_streams_pdf(self, client):
        _mock_impls()
        response = client.get("/agent-evaluations/1/report")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert "evaluation_report_1.pdf" in response.headers["content-disposition"]
        assert response.content == b"%PDF-1.4 fake"

    def test_500_on_exception(self, client):
        _mock_impls(
            generate_agent_evaluation_report_impl=MagicMock(
                side_effect=RuntimeError("boom")
            )
        )
        response = client.get("/agent-evaluations/1/report")
        assert response.status_code == 500

    def test_401_on_unauthorized(self, client):
        from consts.exceptions import UnauthorizedError

        _mock_impls(
            get_current_user_info=MagicMock(side_effect=UnauthorizedError())
        )
        response = client.get("/agent-evaluations/1/report")
        assert response.status_code == 401

    def test_app_exception_propagates(self, client):
        _mock_impls(
            generate_agent_evaluation_report_impl=MagicMock(
                side_effect=_exc(_code("COMMON_RESOURCE_NOT_FOUND"), "missing")
            )
        )
        response = client.get("/agent-evaluations/1/report")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /agent-evaluations/{id}/analyze
# ---------------------------------------------------------------------------


class TestAnalyze:
    def test_generates_report(self, client):
        app = _mock_impls()
        response = client.post("/agent-evaluations/1/analyze?force=true")
        assert response.status_code == 200
        assert app.generate_analysis_report_impl.call_args.kwargs["force"] is True

    def test_400_when_not_ready(self, client):
        _mock_impls(
            generate_analysis_report_impl=MagicMock(
                side_effect=_exc(
                    _code("AGENT_EVALUATION_ANALYSIS_NOT_READY"), "not ready"
                )
            )
        )
        response = client.post("/agent-evaluations/1/analyze")
        assert response.status_code == 400

    def test_500_on_exception(self, client):
        _mock_impls(
            generate_analysis_report_impl=MagicMock(side_effect=RuntimeError("x"))
        )
        response = client.post("/agent-evaluations/1/analyze")
        assert response.status_code == 500

    def test_401_on_unauthorized(self, client):
        from consts.exceptions import UnauthorizedError

        _mock_impls(get_current_user_id=MagicMock(side_effect=UnauthorizedError()))
        response = client.post("/agent-evaluations/1/analyze")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# PUT /agent-evaluations/{id}/annotation-schemas
# ---------------------------------------------------------------------------


class TestUpdateAnnotationSchemas:
    def test_updates_schemas(self, client):
        app = _mock_impls()
        response = client.put(
            "/agent-evaluations/1/annotation-schemas",
            json={"schema_ids": [1, 2]},
        )
        assert response.status_code == 200
        assert response.json()["data"] == [1, 2]
        app.update_annotation_schema_ids.assert_called_once_with(1, "t1", [1, 2])

    def test_500_on_exception(self, client):
        _mock_impls(update_annotation_schema_ids=MagicMock(side_effect=RuntimeError("x")))
        response = client.put(
            "/agent-evaluations/1/annotation-schemas",
            json={"schema_ids": [1]},
        )
        assert response.status_code == 500

    def test_401_on_unauthorized(self, client):
        from consts.exceptions import UnauthorizedError

        _mock_impls(get_current_user_id=MagicMock(side_effect=UnauthorizedError()))
        response = client.put(
            "/agent-evaluations/1/annotation-schemas",
            json={"schema_ids": [1]},
        )
        assert response.status_code == 401

    def test_app_exception_propagates(self, client):
        _mock_impls(
            update_annotation_schema_ids=MagicMock(
                side_effect=_exc(_code("COMMON_RESOURCE_NOT_FOUND"), "missing")
            )
        )
        response = client.put(
            "/agent-evaluations/1/annotation-schemas",
            json={"schema_ids": [1]},
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /agent-evaluations/{id}
# ---------------------------------------------------------------------------


class TestDeleteEvaluation:
    def test_deletes_run(self, client):
        app = _mock_impls()
        response = client.delete("/agent-evaluations/1")
        assert response.status_code == 200
        kwargs = app.delete_agent_evaluation_run_impl.call_args.kwargs
        assert kwargs["agent_evaluation_id"] == 1
        assert kwargs["user_id"] == "u1"

    def test_500_on_exception(self, client):
        _mock_impls(
            delete_agent_evaluation_run_impl=MagicMock(
                side_effect=RuntimeError("boom")
            )
        )
        response = client.delete("/agent-evaluations/1")
        assert response.status_code == 500

    def test_401_on_unauthorized(self, client):
        from consts.exceptions import UnauthorizedError

        _mock_impls(get_current_user_id=MagicMock(side_effect=UnauthorizedError()))
        response = client.delete("/agent-evaluations/1")
        assert response.status_code == 401

    def test_app_exception_propagates(self, client):
        _mock_impls(
            delete_agent_evaluation_run_impl=MagicMock(
                side_effect=_exc(_code("COMMON_RESOURCE_NOT_FOUND"), "missing")
            )
        )
        response = client.delete("/agent-evaluations/1")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /agent-evaluations/trial-run
# ---------------------------------------------------------------------------


class TestTrialRun:
    def test_runs_trial(self, client):
        app = _mock_impls()
        response = client.post(
            "/agent-evaluations/trial-run",
            json={
                "agent_id": 1,
                "query": "hello",
                "judge_model_id": 2,
                "evaluator_ids": [1],
            },
        )
        assert response.status_code == 200
        assert response.json()["data"] == {"result": "ok"}
        assert app.trial_run_evaluator_impl.call_args.kwargs["query"] == "hello"

    def test_401_on_unauthorized(self, client):
        from consts.exceptions import UnauthorizedError

        _mock_impls(get_current_user_id=MagicMock(side_effect=UnauthorizedError()))
        response = client.post(
            "/agent-evaluations/trial-run",
            json={"agent_id": 1, "query": "q", "judge_model_id": 2},
        )
        assert response.status_code == 401

    def test_500_on_exception(self, client):
        _mock_impls(
            trial_run_evaluator_impl=AsyncMock(side_effect=RuntimeError("boom"))
        )
        response = client.post(
            "/agent-evaluations/trial-run",
            json={"agent_id": 1, "query": "q", "judge_model_id": 2},
        )
        assert response.status_code == 500

    def test_app_exception_propagates(self, client):
        _mock_impls(
            trial_run_evaluator_impl=AsyncMock(
                side_effect=_exc(_code("COMMON_RESOURCE_NOT_FOUND"), "missing")
            )
        )
        response = client.post(
            "/agent-evaluations/trial-run",
            json={"agent_id": 1, "query": "q", "judge_model_id": 2},
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# safe-extract helpers
# ---------------------------------------------------------------------------


class TestSafeExtractors:
    def test_tenant_unknown_on_failure(self, monkeypatch):
        monkeypatch.setattr(
            agent_evaluation_app,
            "get_current_user_id",
            MagicMock(side_effect=RuntimeError("bad auth")),
        )
        assert agent_evaluation_app._safe_extract_tenant("token") == "<unknown>"

    def test_user_unknown_on_failure(self, monkeypatch):
        monkeypatch.setattr(
            agent_evaluation_app,
            "get_current_user_id",
            MagicMock(side_effect=RuntimeError("bad auth")),
        )
        assert agent_evaluation_app._safe_extract_user("token") == "<unknown>"

    def test_extract_tenant_with_value(self, monkeypatch):
        monkeypatch.setattr(
            agent_evaluation_app,
            "get_current_user_id",
            MagicMock(return_value=("u1", "t1")),
        )
        assert agent_evaluation_app._safe_extract_tenant("token") == "t1"

    def test_language_default_when_no_request(self):
        assert agent_evaluation_app._safe_extract_language(None) == "zh"

    def test_language_from_request(self, monkeypatch):
        request = MagicMock()
        monkeypatch.setattr(
            sys.modules["utils.auth_utils"],
            "parse_language_from_request",
            MagicMock(return_value="en"),
        )
        assert agent_evaluation_app._safe_extract_language(request) == "en"

    def test_language_fallback_on_error(self, monkeypatch):
        request = MagicMock()
        monkeypatch.setattr(
            sys.modules["utils.auth_utils"],
            "parse_language_from_request",
            MagicMock(side_effect=RuntimeError("boom")),
        )
        assert agent_evaluation_app._safe_extract_language(request) == "zh"
