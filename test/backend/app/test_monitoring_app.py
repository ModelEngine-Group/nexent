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


class TestListModelsEndpoint:
    """Verify list_models_endpoint does not accept model_type parameter."""

    @pytest.fixture
    def client(self, mocker):
        mocker.patch("boto3.client")
        mocker.patch("backend.database.client.MinioClient")

        import types

        if "services.vectordatabase_service" not in sys.modules:
            mod = types.ModuleType("services.vectordatabase_service")
            mod.get_vector_db_core = lambda: object()
            sys.modules["services.vectordatabase_service"] = mod

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
