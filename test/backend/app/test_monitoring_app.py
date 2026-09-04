"""
Unit tests for backend monitoring API endpoints.

Verifies that:
- _query_model_metrics_from_db does not filter by model_type
- list_models_endpoint does not accept a model_type query parameter
"""

import sys
import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "../../..")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

BACKEND_ROOT = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

storage_client_mock = MagicMock()
minio_client_mock = MagicMock()
patch(
    "nexent.storage.storage_client_factory.create_storage_client_from_config",
    return_value=storage_client_mock,
).start()
patch(
    "nexent.storage.minio_config.MinIOStorageConfig.validate", lambda self: None
).start()
patch("backend.database.client.MinioClient",
      return_value=minio_client_mock).start()


class TestQueryModelMetrics:
    """Verify _query_model_metrics_from_db does not filter by model_type."""

    @patch("apps.monitoring_app.get_monitoring_db_session")
    def test_sql_has_no_model_type_filter(self, mock_session_fn):
        """Generated SQL must not contain 'model_type' as a WHERE condition."""
        from apps.monitoring_app import _query_model_metrics_from_db

        mock_session = MagicMock()
        mock_session_fn.return_value.__enter__ = MagicMock(
            return_value=mock_session)
        mock_session_fn.return_value.__exit__ = MagicMock(return_value=None)
        mock_session.execute.return_value.fetchall.return_value = []

        _query_model_metrics_from_db("24h", tenant_id="t-1")

        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0])

        assert "model_type" not in sql_text.lower().split("where")[
            1].split("group")[0]

    @patch("apps.monitoring_app.get_monitoring_db_session")
    def test_return_format(self, mock_session_fn):
        """Returned dicts contain expected keys with correct types."""
        from apps.monitoring_app import _query_model_metrics_from_db

        mock_row = MagicMock()
        mock_row.model_id = 1
        mock_row.model_name = "test-model"
        mock_row.model_type = "llm"
        mock_row.display_name = "Test Model"
        mock_row.request_count = 42
        mock_row.error_rate = 0.5
        mock_row.avg_duration = 120.3
        mock_row.avg_ttft = 50.1
        mock_row.token_generation_rate = 15.2
        mock_row.total_tokens = 1000

        mock_session = MagicMock()
        mock_session_fn.return_value.__enter__ = MagicMock(
            return_value=mock_session)
        mock_session_fn.return_value.__exit__ = MagicMock(return_value=None)
        mock_session.execute.return_value.fetchall.return_value = [mock_row]

        result = _query_model_metrics_from_db("24h", tenant_id="t-1")

        assert len(result) == 1
        record = result[0]
        assert record["model_name"] == "test-model"
        assert isinstance(record["error_rate"], float)
        assert isinstance(record["total_tokens"], int)


class TestContextBudgetMetrics:
    @patch("apps.monitoring_app.get_monitoring_db_session")
    def test_rates_and_null_denominators(self, mock_session_fn):
        from apps.monitoring_app import _query_context_budget_metrics_from_db

        row = MagicMock()
        row.provider_protocol = "dashscope"
        row.model_name = "qwen3.7-plus"
        row.capability_profile_version = "dashscope/qwen3.7-plus@1"
        row.request_count = 4
        row.overflow_count = 1
        row.compacted_count = 2
        row.avg_compression_ratio = 0.25
        row.estimate_sample_count = 4
        row.mean_absolute_estimate_error = 0.08
        row.recovery_attempt_count = 1
        row.recovery_success_count = 1
        session = MagicMock()
        mock_session_fn.return_value.__enter__ = MagicMock(return_value=session)
        mock_session_fn.return_value.__exit__ = MagicMock(return_value=None)
        session.execute.return_value.fetchall.return_value = [row]

        result = _query_context_budget_metrics_from_db("24h", tenant_id="tenant-a")[0]

        assert result["overflow_rate"] == 0.25
        assert result["compaction_incidence"] == 0.5
        assert result["recovery_success_rate"] == 1.0
        sql, params = session.execute.call_args.args
        assert "tenant_id = :tenant_id" in str(sql)
        assert "compression_attempted')::boolean" in str(sql)
        assert params == {"tenant_id": "tenant-a"}

    @patch("apps.monitoring_app.get_monitoring_db_session")
    def test_non_applicable_recovery_rate_is_null(self, mock_session_fn):
        from apps.monitoring_app import _query_context_budget_metrics_from_db

        row = MagicMock(provider_protocol="test", model_name="m", capability_profile_version="unknown")
        row.request_count = 1
        row.overflow_count = row.compacted_count = row.estimate_sample_count = 0
        row.avg_compression_ratio = row.mean_absolute_estimate_error = None
        row.recovery_attempt_count = row.recovery_success_count = 0
        session = MagicMock()
        mock_session_fn.return_value.__enter__ = MagicMock(return_value=session)
        mock_session_fn.return_value.__exit__ = MagicMock(return_value=None)
        session.execute.return_value.fetchall.return_value = [row]
        result = _query_context_budget_metrics_from_db("7d", tenant_id="t")[0]
        assert result["recovery_success_rate"] is None


class TestListModelsEndpoint:
    """Verify list_models_endpoint does not accept model_type parameter."""

    @pytest.fixture
    def client(self, mocker):
        mocker.patch("boto3.client")
        mocker.patch("backend.database.client.MinioClient")

        import types

        if "management.services.knowledge_base.service" not in sys.modules:
            mod = types.ModuleType("management.services.knowledge_base.service")
            mod.get_vector_db_core = lambda: object()
            sys.modules["management.services.knowledge_base.service"] = mod

        from apps.monitoring_app import router

        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_endpoint_signature_has_no_model_type(self):
        """The endpoint function must not declare a model_type Query parameter."""
        from apps.monitoring_app import list_models_endpoint

        import inspect

        sig = inspect.signature(list_models_endpoint)
        assert "model_type" not in sig.parameters

    @patch("apps.monitoring_app._query_model_metrics_from_db", return_value=[])
    @patch("apps.monitoring_app.get_current_user_id", return_value=("u-1", "t-1"))
    def test_endpoint_returns_success(self, mock_auth, mock_query, client):
        """GET /monitoring/models returns code 0 on success."""
        response = client.get(
            "/monitoring/models",
            params={"time_range": "24h"},
            headers={"Authorization": "Bearer test"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0

    @patch("apps.monitoring_app._query_model_metrics_from_db", return_value=[])
    @patch("apps.monitoring_app.get_current_user_id", return_value=("u-1", "t-1"))
    def test_endpoint_returns_empty_data(self, mock_auth, mock_query, client):
        response = client.get(
            "/monitoring/models",
            params={"time_range": "24h"},
            headers={"Authorization": "Bearer test"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        assert body["data"] == []

    @patch("apps.monitoring_app._query_model_metrics_from_db", side_effect=Exception("db down"))
    @patch("apps.monitoring_app.get_current_user_id", return_value=("u-1", "t-1"))
    def test_endpoint_returns_500_on_exception(self, mock_auth, mock_query, client):
        response = client.get(
            "/monitoring/models",
            params={"time_range": "24h"},
            headers={"Authorization": "Bearer test"},
        )
        assert response.status_code == 500


class TestMonitoringStatus:
    """Verify monitoring status endpoint used by the frontend top bar."""

    def test_dashboard_url_comes_from_configuration(self, monkeypatch):
        from apps.monitoring_app import get_monitoring_status

        monkeypatch.setattr("apps.monitoring_app.ENABLE_TELEMETRY", True)
        monkeypatch.setattr("apps.monitoring_app.MONITORING_PROVIDER", "grafana")
        monkeypatch.setattr(
            "apps.monitoring_app.MONITORING_DASHBOARD_URL",
            "http://localhost:3002/d/nexent-llm-agent/nexent-agent-trace-monitoring?orgId=1",
        )

        status = get_monitoring_status()

        assert status["telemetry_enabled"] is True
        assert status["provider"] == "grafana"
        assert (
            status["dashboard_url"]
            == "http://localhost:3002/d/nexent-llm-agent/nexent-agent-trace-monitoring?orgId=1"
        )
        assert status["dashboard_port"] is None
        assert status["dashboard_path"] is None

    def test_otlp_provider_status_has_no_ui(self, monkeypatch):
        from apps.monitoring_app import get_monitoring_status

        monkeypatch.setattr("apps.monitoring_app.ENABLE_TELEMETRY", True)
        monkeypatch.setattr("apps.monitoring_app.MONITORING_PROVIDER", "otlp")
        monkeypatch.setattr("apps.monitoring_app.MONITORING_DASHBOARD_URL", "")

        status = get_monitoring_status()

        assert status["telemetry_enabled"] is True
        assert status["dashboard_url"] is None
        assert status["dashboard_port"] is None
        assert status["dashboard_path"] is None

    def test_zipkin_provider_status_uses_configured_url(self, monkeypatch):
        from apps.monitoring_app import get_monitoring_status

        monkeypatch.setattr("apps.monitoring_app.ENABLE_TELEMETRY", True)
        monkeypatch.setattr("apps.monitoring_app.MONITORING_PROVIDER", "zipkin")
        monkeypatch.setattr(
            "apps.monitoring_app.MONITORING_DASHBOARD_URL",
            "http://localhost:9411",
        )

        status = get_monitoring_status()

        assert status["telemetry_enabled"] is True
        assert status["provider"] == "zipkin"
        assert status["dashboard_url"] == "http://localhost:9411"
        assert status["dashboard_port"] is None
        assert status["dashboard_path"] is None

    def test_langsmith_provider_status_has_no_local_ui(self, monkeypatch):
        from apps.monitoring_app import get_monitoring_status

        monkeypatch.setattr("apps.monitoring_app.ENABLE_TELEMETRY", True)
        monkeypatch.setattr("apps.monitoring_app.MONITORING_PROVIDER", "langsmith")
        monkeypatch.setattr("apps.monitoring_app.MONITORING_DASHBOARD_URL", "")

        status = get_monitoring_status()

        assert status["telemetry_enabled"] is True
        assert status["provider"] == "langsmith"
        assert status["dashboard_url"] is None
        assert status["dashboard_port"] is None
        assert status["dashboard_path"] is None

    def test_unsupported_provider_has_no_ui(self, monkeypatch):
        from apps.monitoring_app import get_monitoring_status

        monkeypatch.setattr("apps.monitoring_app.ENABLE_TELEMETRY", True)
        monkeypatch.setattr("apps.monitoring_app.MONITORING_PROVIDER", "unsupported")
        monkeypatch.setattr("apps.monitoring_app.MONITORING_DASHBOARD_URL", "")

        status = get_monitoring_status()

        assert status["provider"] == "unsupported"
        assert status["dashboard_url"] is None
        assert status["dashboard_port"] is None
        assert status["dashboard_path"] is None

    def test_status_endpoint_returns_success(self, monkeypatch):
        from apps.monitoring_app import router

        monkeypatch.setattr("apps.monitoring_app.ENABLE_TELEMETRY", True)
        monkeypatch.setattr("apps.monitoring_app.MONITORING_PROVIDER", "phoenix")
        monkeypatch.setattr(
            "apps.monitoring_app.MONITORING_DASHBOARD_URL",
            "http://localhost:6006",
        )

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/monitoring/status")

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        assert body["data"]["dashboard_url"] == "http://localhost:6006"

    @patch("apps.monitoring_app.get_current_user_id")
    def test_endpoint_returns_401_on_token_expired(self, mock_auth):
        """Expired token maps to 401 for /monitoring/models."""
        from apps.monitoring_app import router
        from consts.exceptions import TokenExpiredError

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        mock_auth.side_effect = TokenExpiredError("expired")
        response = client.get(
            "/monitoring/models",
            params={"time_range": "24h"},
            headers={"Authorization": "Bearer expired"},
        )
        assert response.status_code == 401
