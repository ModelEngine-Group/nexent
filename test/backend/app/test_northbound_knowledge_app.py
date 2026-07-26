"""
Unit tests for northbound_knowledge_app ASSET_OWNER-scoped endpoints.
"""

import os
import sys
import types
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(current_dir, "../../../backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# ---------------------------------------------------------------------------
# Stub services package (mirrors test_northbound_base_app.py)
# ---------------------------------------------------------------------------
services_pkg = types.ModuleType("services")
services_pkg.__path__ = [os.path.join(backend_dir, "services")]
sys.modules["services"] = services_pkg


@dataclass
class NorthboundContext:
    request_id: str
    tenant_id: str
    user_id: str
    authorization: str
    token_id: int = 0


northbound_service_module = types.ModuleType("services.northbound_service")
northbound_service_module.NorthboundContext = NorthboundContext
sys.modules["services.northbound_service"] = northbound_service_module

file_mgmt_module = types.ModuleType("services.file_management_service")
file_mgmt_module.upload_files_impl = AsyncMock()
file_mgmt_module.get_file_url_impl = AsyncMock()
file_mgmt_module.get_file_stream_impl = AsyncMock()
file_mgmt_module.check_file_access = MagicMock(return_value=True)
sys.modules["services.file_management_service"] = file_mgmt_module

redis_service_module = types.ModuleType("services.redis_service")
redis_service_module.get_redis_service = MagicMock()
sys.modules["services.redis_service"] = redis_service_module

vectordb_service_module = types.ModuleType("services.vectordatabase_service")


class KnowledgeBaseNeedsModelConfigError(Exception):
    def __init__(self, index_name: str, message: str = None):
        self.index_name = index_name
        self.message = message or (
            f"Knowledge base '{index_name}' needs an embedding model to be configured"
        )
        super().__init__(self.message)


class _ElasticSearchServiceStub:
    @staticmethod
    def list_indices(*args, **kwargs):
        return {"indices": ["kb1"]}

    @staticmethod
    def get_index_chunks(*args, **kwargs):
        return {"chunks": [{"id": "c1", "content": "hello"}], "total": 1}

    @staticmethod
    def search_hybrid(*args, **kwargs):
        return {
            "results": [{"title": "Doc1", "content": "Content1", "score": 0.9}],
            "total": 1,
        }

    @staticmethod
    async def delete_document_by_scope(index_name, path_or_url, scope, vdb_core):
        return {
            "status": "success",
            "message": "Documents deleted successfully",
            "scope": scope,
            "deleted_es_count": 1,
        }

    @staticmethod
    def delete_documents(index_name, path_or_url, vdb_core):
        return {"message": "Documents deleted successfully", "deleted": 1}


vectordb_service_module.ElasticSearchService = _ElasticSearchServiceStub
vectordb_service_module.KnowledgeBaseNeedsModelConfigError = (
    KnowledgeBaseNeedsModelConfigError
)
vectordb_service_module.get_vector_db_core = MagicMock()
sys.modules["services.vectordatabase_service"] = vectordb_service_module

database_pkg = types.ModuleType("database")
database_pkg.__path__ = [os.path.join(backend_dir, "database")]
sys.modules["database"] = database_pkg

knowledge_db_module = types.ModuleType("database.knowledge_db")
knowledge_db_module.get_index_name_by_knowledge_name = MagicMock(
    side_effect=lambda name, tenant_id: f"resolved_{name}"
)
sys.modules["database.knowledge_db"] = knowledge_db_module

consts_module = types.ModuleType("consts")
consts_module.__path__ = [os.path.join(backend_dir, "consts")]
sys.modules["consts"] = consts_module

consts_exceptions_module = types.ModuleType("consts.exceptions")
consts_exceptions_module.LimitExceededError = type("LimitExceededError", (Exception,), {})
consts_exceptions_module.UnauthorizedError = type("UnauthorizedError", (Exception,), {})
sys.modules["consts.exceptions"] = consts_exceptions_module

from pydantic import BaseModel, Field  # noqa: E402


class HybridSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    index_names: list[str] = Field(..., min_length=1)
    top_k: int = Field(10, ge=1, le=100)
    weight_accurate: float = Field(0.5, ge=0.0, le=1.0)


consts_model_module = types.ModuleType("consts.model")
consts_model_module.ProcessParams = type(
    "ProcessParams",
    (),
    {"__init__": lambda self, **kwargs: None},
)
consts_model_module.HybridSearchRequest = HybridSearchRequest
sys.modules["consts.model"] = consts_model_module

consts_const_module = types.ModuleType("consts.const")
consts_const_module.ASSET_OWNER_TENANT_ID = "asset_owner_tenant_id"


class VectorDatabaseType:
    ELASTICSEARCH = "elasticsearch"


consts_const_module.VectorDatabaseType = VectorDatabaseType
sys.modules["consts.const"] = consts_const_module

utils_auth_module = types.ModuleType("utils.auth_utils")
utils_auth_module.generate_session_jwt = MagicMock(return_value="jwt-token")
sys.modules["utils.auth_utils"] = utils_auth_module

utils_fm_module = types.ModuleType("utils.file_management_utils")
utils_fm_module.trigger_data_process = AsyncMock(return_value={"status": "ok"})
sys.modules["utils.file_management_utils"] = utils_fm_module

northbound_app_module = types.ModuleType("apps.northbound_app")
northbound_app_module._get_northbound_context = AsyncMock()
sys.modules["apps.northbound_app"] = northbound_app_module

file_management_app_module = types.ModuleType("apps.file_management_app")
file_management_app_module.build_content_disposition_header = MagicMock(
    return_value='attachment; filename="file.txt"'
)
sys.modules["apps.file_management_app"] = file_management_app_module

from apps.northbound_knowledge_app import router  # noqa: E402
from consts.const import ASSET_OWNER_TENANT_ID  # noqa: E402
from consts.exceptions import LimitExceededError, UnauthorizedError  # noqa: E402

ASSET_CTX = NorthboundContext(
    request_id="req-1",
    tenant_id=ASSET_OWNER_TENANT_ID,
    user_id="ao_user",
    authorization="Bearer token",
)
REGULAR_CTX = NorthboundContext(
    request_id="req-2",
    tenant_id="regular_tenant",
    user_id="user1",
    authorization="Bearer token",
)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def mock_northbound_context():
    with patch(
        "apps.northbound_knowledge_app._get_northbound_context",
        new_callable=AsyncMock,
    ) as mock_ctx:
        yield mock_ctx


class TestRequireAssetOwnerContext:
    def test_non_asset_owner_tenant_returns_403(self, client, mock_northbound_context):
        mock_northbound_context.return_value = REGULAR_CTX
        response = client.get("/nb/v1/knowledge/indices")
        assert response.status_code == 403
        assert "asset administrators" in response.json()["detail"]


class TestGetListIndices:
    def test_success_for_asset_owner(self, client, mock_northbound_context):
        mock_northbound_context.return_value = ASSET_CTX
        response = client.get("/nb/v1/knowledge/indices")
        assert response.status_code == 200
        assert response.json()["indices"] == ["kb1"]

    def test_rate_limit_returns_429(self, client, mock_northbound_context):
        mock_northbound_context.return_value = ASSET_CTX
        with patch(
            "apps.northbound_knowledge_app.ElasticSearchService.list_indices",
            side_effect=LimitExceededError("too many"),
        ):
            response = client.get("/nb/v1/knowledge/indices")
        assert response.status_code == 429

    def test_generic_error_returns_500(self, client, mock_northbound_context):
        mock_northbound_context.return_value = ASSET_CTX
        with patch(
            "apps.northbound_knowledge_app.get_vector_db_core",
            side_effect=RuntimeError("db down"),
        ):
            response = client.get("/nb/v1/knowledge/indices")
        assert response.status_code == 500
        assert "Error listing knowledge bases" in response.json()["detail"]


class TestUploadFiles:
    def test_missing_file_field_returns_client_error(self, client, mock_northbound_context):
        mock_northbound_context.return_value = ASSET_CTX
        response = client.post(
            "/nb/v1/knowledge/file/upload",
            data={"index_name": "kb1"},
            files=[],
        )
        # FastAPI rejects missing required multipart file field before handler runs
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_empty_file_list_returns_400(self, mock_northbound_context):
        from apps.northbound_knowledge_app import upload_files

        mock_northbound_context.return_value = ASSET_CTX
        request = MagicMock()
        with patch(
            "apps.northbound_knowledge_app._require_asset_owner_context",
            new_callable=AsyncMock,
            return_value=ASSET_CTX,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await upload_files(request=request, file=[], index_name="kb1")
        assert exc_info.value.status_code == 400

    def test_no_valid_uploads_returns_400(self, client, mock_northbound_context):
        mock_northbound_context.return_value = ASSET_CTX
        file_mgmt_module.upload_files_impl.return_value = (["err"], [], [])
        response = client.post(
            "/nb/v1/knowledge/file/upload",
            data={"index_name": "kb1"},
            files=[("file", ("test.txt", b"data", "text/plain"))],
        )
        assert response.status_code == 400
        assert "No valid files" in response.json()["detail"]


class TestGetStorageFile:
    def test_access_denied_returns_403(self, client, mock_northbound_context):
        mock_northbound_context.return_value = ASSET_CTX
        file_mgmt_module.check_file_access.return_value = False
        response = client.get("/nb/v1/knowledge/file/download/some/object")
        assert response.status_code == 403
        assert "permission" in response.json()["detail"].lower()
        file_mgmt_module.check_file_access.return_value = True


class TestDeleteDocuments:
    def test_redis_cleanup_failure_still_returns_200(self, client, mock_northbound_context):
        mock_northbound_context.return_value = ASSET_CTX
        redis_mock = MagicMock()
        redis_mock.delete_document_records.side_effect = RuntimeError("redis down")
        redis_service_module.get_redis_service.return_value = redis_mock

        response = client.delete(
            "/nb/v1/knowledge/indices/kb1/documents",
            params={
                "path_or_url": "minio://path/doc.pdf",
                "scope": "full",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert "Redis cleanup encountered an error" in body["message"]
        assert "redis_cleanup_error" in body


class TestGetIndexChunks:
    def test_non_asset_owner_returns_403(self, client, mock_northbound_context):
        mock_northbound_context.return_value = REGULAR_CTX
        response = client.post("/nb/v1/knowledge/indices/kb1/chunks")
        assert response.status_code == 403
        assert "asset administrators" in response.json()["detail"]

    def test_success_for_asset_owner(self, client, mock_northbound_context):
        mock_northbound_context.return_value = ASSET_CTX
        response = client.post("/nb/v1/knowledge/indices/kb1/chunks")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["chunks"][0]["id"] == "c1"

    def test_path_or_url_forbidden_returns_403(self, client, mock_northbound_context):
        mock_northbound_context.return_value = ASSET_CTX
        file_mgmt_module.check_file_access.return_value = False
        try:
            response = client.post(
                "/nb/v1/knowledge/indices/kb1/chunks",
                params={"path_or_url": "minio://path/doc.pdf"},
            )
            assert response.status_code == 403
            assert "permission" in response.json()["detail"].lower()
        finally:
            file_mgmt_module.check_file_access.return_value = True

    def test_rate_limit_returns_429(self, client, mock_northbound_context):
        mock_northbound_context.return_value = ASSET_CTX
        with patch(
            "apps.northbound_knowledge_app.ElasticSearchService.get_index_chunks",
            side_effect=LimitExceededError("too many"),
        ):
            response = client.post("/nb/v1/knowledge/indices/kb1/chunks")
        assert response.status_code == 429

    def test_value_error_returns_404(self, client, mock_northbound_context):
        mock_northbound_context.return_value = ASSET_CTX
        with patch(
            "apps.northbound_knowledge_app.ElasticSearchService.get_index_chunks",
            side_effect=ValueError("index not found"),
        ):
            response = client.post("/nb/v1/knowledge/indices/kb1/chunks")
        assert response.status_code == 404
        assert "index not found" in response.json()["detail"]

    def test_unauthorized_returns_401(self, client, mock_northbound_context):
        mock_northbound_context.return_value = ASSET_CTX
        with patch(
            "apps.northbound_knowledge_app.ElasticSearchService.get_index_chunks",
            side_effect=UnauthorizedError("bad token"),
        ):
            response = client.post("/nb/v1/knowledge/indices/kb1/chunks")
        assert response.status_code == 401
        assert "bad token" in response.json()["detail"]

    def test_generic_error_returns_500(self, client, mock_northbound_context):
        mock_northbound_context.return_value = ASSET_CTX
        with patch(
            "apps.northbound_knowledge_app.ElasticSearchService.get_index_chunks",
            side_effect=RuntimeError("es down"),
        ):
            response = client.post("/nb/v1/knowledge/indices/kb1/chunks")
        assert response.status_code == 500
        assert "Error getting chunks" in response.json()["detail"]


class TestHybridSearch:
    def test_non_asset_owner_returns_403(self, client, mock_northbound_context):
        mock_northbound_context.return_value = REGULAR_CTX
        response = client.post(
            "/nb/v1/knowledge/indices/search/hybrid",
            json={
                "query": "test",
                "index_names": ["kb1"],
            },
        )
        assert response.status_code == 403
        assert "asset administrators" in response.json()["detail"]

    def test_success_for_asset_owner(self, client, mock_northbound_context):
        mock_northbound_context.return_value = ASSET_CTX
        with patch(
            "apps.northbound_knowledge_app.ElasticSearchService.search_hybrid",
        ) as mock_search:
            mock_search.return_value = {
                "results": [{"title": "Doc1", "score": 0.9}],
                "total": 1,
            }
            response = client.post(
                "/nb/v1/knowledge/indices/search/hybrid",
                json={
                    "query": "test query",
                    "index_names": ["kb1"],
                    "top_k": 5,
                    "weight_accurate": 0.3,
                },
            )
        assert response.status_code == 200
        assert response.json()["total"] == 1
        mock_search.assert_called_once()
        call_kwargs = mock_search.call_args.kwargs
        assert call_kwargs["index_names"] == ["resolved_kb1"]
        assert call_kwargs["query"] == "test query"
        assert call_kwargs["tenant_id"] == ASSET_OWNER_TENANT_ID
        assert call_kwargs["top_k"] == 5
        assert call_kwargs["weight_accurate"] == 0.3

    def test_model_config_conflict_returns_409(self, client, mock_northbound_context):
        mock_northbound_context.return_value = ASSET_CTX
        with patch(
            "apps.northbound_knowledge_app.ElasticSearchService.search_hybrid",
            side_effect=KnowledgeBaseNeedsModelConfigError("kb1", "needs model"),
        ):
            response = client.post(
                "/nb/v1/knowledge/indices/search/hybrid",
                json={
                    "query": "test",
                    "index_names": ["kb1"],
                },
            )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["error_type"] == "KNOWLEDGE_BASE_NEEDS_MODEL_CONFIG"
        assert detail["index_name"] == "kb1"

    def test_rate_limit_returns_429(self, client, mock_northbound_context):
        mock_northbound_context.return_value = ASSET_CTX
        with patch(
            "apps.northbound_knowledge_app.ElasticSearchService.search_hybrid",
            side_effect=LimitExceededError("too many"),
        ):
            response = client.post(
                "/nb/v1/knowledge/indices/search/hybrid",
                json={
                    "query": "test",
                    "index_names": ["kb1"],
                },
            )
        assert response.status_code == 429

    def test_unresolved_index_name_falls_back_to_requested(self, client, mock_northbound_context):
        mock_northbound_context.return_value = ASSET_CTX
        with patch(
            "apps.northbound_knowledge_app.get_index_name_by_knowledge_name",
            side_effect=RuntimeError("not mapped"),
        ), patch(
            "apps.northbound_knowledge_app.ElasticSearchService.search_hybrid",
        ) as mock_search:
            mock_search.return_value = {"results": [], "total": 0}
            response = client.post(
                "/nb/v1/knowledge/indices/search/hybrid",
                json={
                    "query": "test",
                    "index_names": ["raw_kb"],
                },
            )
        assert response.status_code == 200
        assert mock_search.call_args.kwargs["index_names"] == ["raw_kb"]

    def test_value_error_returns_400(self, client, mock_northbound_context):
        mock_northbound_context.return_value = ASSET_CTX
        with patch(
            "apps.northbound_knowledge_app.ElasticSearchService.search_hybrid",
            side_effect=ValueError("invalid query"),
        ):
            response = client.post(
                "/nb/v1/knowledge/indices/search/hybrid",
                json={
                    "query": "test",
                    "index_names": ["kb1"],
                },
            )
        assert response.status_code == 400
        assert "invalid query" in response.json()["detail"]

    def test_unauthorized_returns_401(self, client, mock_northbound_context):
        mock_northbound_context.return_value = ASSET_CTX
        with patch(
            "apps.northbound_knowledge_app.ElasticSearchService.search_hybrid",
            side_effect=UnauthorizedError("bad token"),
        ):
            response = client.post(
                "/nb/v1/knowledge/indices/search/hybrid",
                json={
                    "query": "test",
                    "index_names": ["kb1"],
                },
            )
        assert response.status_code == 401
        assert "bad token" in response.json()["detail"]

    def test_generic_error_returns_500(self, client, mock_northbound_context):
        mock_northbound_context.return_value = ASSET_CTX
        with patch(
            "apps.northbound_knowledge_app.ElasticSearchService.search_hybrid",
            side_effect=RuntimeError("search failed"),
        ):
            response = client.post(
                "/nb/v1/knowledge/indices/search/hybrid",
                json={
                    "query": "test",
                    "index_names": ["kb1"],
                },
            )
        assert response.status_code == 500
        assert "Error executing hybrid search" in response.json()["detail"]
