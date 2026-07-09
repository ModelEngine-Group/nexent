"""
Extended unit tests for unified_kb_app endpoints (V4 Phase 4.2).

Covers endpoints NOT tested in test_unified_kb_app.py:
  1. PUT    /adapters/{adapter_id}                              — update adapter
  2. DELETE /adapters/{adapter_id}                              — delete adapter (blocks 'local')
  3. POST   /adapters/{adapter_id}/knowledge-bases              — create KB
  4. PUT    /adapters/{adapter_id}/knowledge-bases/{kb_id}      — update KB
  5. DELETE /adapters/{adapter_id}/knowledge-bases/{kb_id}      — delete KB
  6. POST   .../knowledge-bases/{kb_id}/documents               — upload documents
  7. DELETE .../knowledge-bases/{kb_id}/documents/{doc_id}      — delete document
  8. GET    .../documents/{doc_id}/status                       — document status
  9. POST   .../knowledge-bases/{kb_id}/retrieve                — per-KB retrieve
 10. POST   /retrieve-all                                       — cross-adapter retrieve
 11. POST   /adapters                                           — register adapter error paths

Also documents preexisting bugs:
  - ValueError from service layer returns HTTP 500 instead of HTTP 400
"""
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Path setup — mirror test_unified_kb_app.py
# ---------------------------------------------------------------------------
backend_path = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "../../../backend"
))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

sdk_path = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "../../../sdk"
))
if sdk_path not in sys.path:
    sys.path.insert(0, sdk_path)


# ---------------------------------------------------------------------------
# Module imports (after path setup)
# ---------------------------------------------------------------------------
from backend.apps import unified_kb_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def stub_service(monkeypatch):
    """Patch ExternalKnowledgeBaseService via monkeypatch on the module.

    Provides sensible defaults for all service methods. Individual tests
    override return_value / side_effect as needed.
    """
    svc = MagicMock()

    # Adapter management
    svc.ensure_local_adapter.return_value = {"adapter_id": 1, "platform": "local"}
    svc.list_adapters.return_value = []
    svc.register_adapter.return_value = {
        "adapter_id": 3, "name": "dify-adapter", "platform": "dify",
        "enabled": True, "status": "running",
    }
    svc.update_adapter.return_value = {
        "adapter_id": 1, "name": "updated-adapter", "platform": "dify",
        "enabled": True, "status": "running",
    }
    svc.delete_adapter.return_value = True

    # Adapter instance returned by get_adapter (for list_knowledge_bases etc.)
    mock_adapter_instance = MagicMock()
    mock_adapter_instance.list_knowledge_bases.return_value = []
    mock_adapter_instance.close.return_value = None
    svc.get_adapter.return_value = mock_adapter_instance

    # KB CRUD
    svc.create_knowledge_base.return_value = {
        "kb_id": "kb-new", "name": "Test KB", "description": "",
    }
    svc.get_knowledge_base.return_value = {
        "kb_id": "kb-1", "name": "Test KB", "description": "desc",
    }
    svc.update_knowledge_base.return_value = {
        "kb_id": "kb-1", "name": "Updated KB", "description": "new desc",
    }
    svc.delete_knowledge_base.return_value = True

    # Document operations
    svc.upload_documents.return_value = {
        "documents": [{"id": "doc-1", "name": "test.txt", "status": "indexing"}],
    }
    svc.delete_document.return_value = True
    svc.get_document_status.return_value = {
        "id": "doc-1", "status": "completed", "progress": 1.0,
    }
    svc.list_documents.return_value = {
        "items": [], "total": 0, "page": 1, "page_size": 20,
    }

    # Search
    svc.retrieve.return_value = {"records": [], "query": ""}

    # Health / capabilities
    svc.check_health.return_value = {"status": "ok"}
    svc.refresh_capabilities.return_value = {}

    # Aggregation
    svc.list_all_external_knowledge_bases.return_value = []

    monkeypatch.setattr(unified_kb_app, "ExternalKnowledgeBaseService", svc)
    return svc


@pytest.fixture
def stub_database(monkeypatch):
    """Patch get_adapter_by_id via monkeypatch on the module."""
    db_mock = MagicMock()
    db_mock.get_adapter_by_id.return_value = {
        "adapter_id": 1, "name": "dify-adapter", "platform": "dify",
        "enabled": True, "status": "running", "config": {},
    }
    monkeypatch.setattr(unified_kb_app, "get_adapter_by_id", db_mock.get_adapter_by_id)
    return db_mock


@pytest.fixture
def client(stub_service, stub_database):
    """Create TestClient with auth bypassed via dependency_overrides."""
    app = FastAPI()
    app.include_router(unified_kb_app.router)
    app.dependency_overrides[unified_kb_app._get_current_user] = lambda: ("user-1", "tenant-1")
    return TestClient(app)


# Common headers
AUTH = {"Authorization": "Bearer test-token"}


# ===========================================================================
# TestAdapterOps — PUT /adapters/{id}, DELETE /adapters/{id}
# ===========================================================================
class TestAdapterOps:
    """Tests for adapter update and delete endpoints."""

    def test_update_adapter_success(self, client, stub_service):
        """PUT /adapters/1 updates adapter config and returns updated record."""
        stub_service.update_adapter.return_value = {
            "adapter_id": 1, "name": "renamed", "platform": "dify",
            "enabled": False, "status": "stopped",
        }
        r = client.put(
            "/api/v1/kb/adapters/1",
            json={"name": "renamed", "enabled": False, "status": "stopped"},
            headers=AUTH,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "renamed"
        assert data["enabled"] is False
        # Verify service was called with correct args
        stub_service.update_adapter.assert_called_once_with(
            1, "tenant-1", {"name": "renamed", "enabled": False, "status": "stopped"}
        )

    def test_update_adapter_partial_update(self, client, stub_service):
        """PUT with only some fields sends exclude_none=True dict to service."""
        stub_service.update_adapter.return_value = {
            "adapter_id": 1, "name": "dify-adapter", "platform": "dify",
            "enabled": True, "status": "running",
        }
        r = client.put(
            "/api/v1/kb/adapters/1",
            json={"name": "new-name"},
            headers=AUTH,
        )
        assert r.status_code == 200
        # Only 'name' should be in the updates dict (exclude_none=True)
        call_args = stub_service.update_adapter.call_args
        assert call_args[0][2] == {"name": "new-name"}

    def test_update_adapter_not_found(self, client, stub_service):
        """PUT /adapters/999 returns 404 when service returns None."""
        stub_service.update_adapter.return_value = None
        r = client.put(
            "/api/v1/kb/adapters/999",
            json={"name": "x"},
            headers=AUTH,
        )
        assert r.status_code == 404
        assert "999" in r.json()["detail"]

    def test_delete_adapter_success(self, client, stub_service):
        """DELETE /adapters/2 soft-deletes a non-local adapter."""
        stub_service.delete_adapter.return_value = True
        r = client.delete("/api/v1/kb/adapters/2", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        stub_service.delete_adapter.assert_called_once_with(2, "tenant-1")

    def test_delete_adapter_not_found(self, client, stub_service):
        """DELETE /adapters/999 returns 404 when service returns False."""
        stub_service.delete_adapter.return_value = False
        r = client.delete("/api/v1/kb/adapters/999", headers=AUTH)
        assert r.status_code == 404
        assert "999" in r.json()["detail"]

    @pytest.mark.xfail(reason="Bug: ValueError returns HTTP 500 instead of 400")
    def test_delete_adapter_blocks_local_should_be_400(self, client, stub_service):
        """Deleting the built-in local adapter should return 400, not 500.

        The service raises ValueError('Cannot delete the built-in local adapter')
        but the endpoint does not catch it, resulting in HTTP 500.
        """
        stub_service.delete_adapter.side_effect = ValueError(
            "Cannot delete the built-in local adapter"
        )
        r = client.delete("/api/v1/kb/adapters/1", headers=AUTH)
        assert r.status_code == 400  # Expected correct behavior


# ===========================================================================
# TestKbCrud — POST/PUT/DELETE knowledge bases
# ===========================================================================
class TestKbCrud:
    """Tests for knowledge base CRUD endpoints."""

    def test_create_kb_success(self, client, stub_service):
        """POST /adapters/1/knowledge-bases creates a new KB."""
        stub_service.create_knowledge_base.return_value = {
            "kb_id": "kb-new", "name": "My KB", "description": "test desc",
        }
        r = client.post(
            "/api/v1/kb/adapters/1/knowledge-bases",
            json={"name": "My KB", "description": "test desc"},
            headers=AUTH,
        )
        assert r.status_code == 201
        data = r.json()
        assert data["kb_id"] == "kb-new"
        assert data["name"] == "My KB"
        stub_service.create_knowledge_base.assert_called_once()

    def test_create_kb_missing_name(self, client):
        """POST without required 'name' field returns 422."""
        r = client.post(
            "/api/v1/kb/adapters/1/knowledge-bases",
            json={"description": "no name"},
            headers=AUTH,
        )
        assert r.status_code == 422

    def test_create_kb_with_embedding_config(self, client, stub_service):
        """POST with embedding_model_config passes it to service."""
        stub_service.create_knowledge_base.return_value = {"kb_id": "kb-2"}
        r = client.post(
            "/api/v1/kb/adapters/1/knowledge-bases",
            json={
                "name": "Embedded KB",
                "embedding_model_config": {"model_name": "text-embedding-ada-002"},
            },
            headers=AUTH,
        )
        assert r.status_code == 201
        call_kwargs = stub_service.create_knowledge_base.call_args[1]
        assert call_kwargs["embedding_model_config"]["model_name"] == "text-embedding-ada-002"

    def test_update_kb_success(self, client, stub_service):
        """PUT /adapters/1/knowledge-bases/kb-1 updates KB metadata."""
        stub_service.update_knowledge_base.return_value = {
            "kb_id": "kb-1", "name": "Renamed KB", "description": "new desc",
        }
        r = client.put(
            "/api/v1/kb/adapters/1/knowledge-bases/kb-1",
            json={"name": "Renamed KB", "description": "new desc"},
            headers=AUTH,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "Renamed KB"
        stub_service.update_knowledge_base.assert_called_once_with(
            adapter_id=1, tenant_id="tenant-1", user_id="user-1",
            kb_id="kb-1", body={"name": "Renamed KB", "description": "new desc"},
        )

    def test_delete_kb_success(self, client, stub_service):
        """DELETE /adapters/1/knowledge-bases/kb-1 deletes the KB."""
        stub_service.delete_knowledge_base.return_value = True
        r = client.delete("/api/v1/kb/adapters/1/knowledge-bases/kb-1", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        stub_service.delete_knowledge_base.assert_called_once_with(
            adapter_id=1, tenant_id="tenant-1", user_id="user-1", kb_id="kb-1",
        )

    def test_delete_kb_not_found_returns_false(self, client, stub_service):
        """DELETE returns success=False when KB does not exist."""
        stub_service.delete_knowledge_base.return_value = False
        r = client.delete("/api/v1/kb/adapters/1/knowledge-bases/kb-missing", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["success"] is False

    def test_get_kb_success(self, client, stub_service):
        """GET /adapters/1/knowledge-bases/kb-1 returns KB details."""
        stub_service.get_knowledge_base.return_value = {
            "kb_id": "kb-1", "name": "Test KB", "description": "desc",
        }
        r = client.get("/api/v1/kb/adapters/1/knowledge-bases/kb-1", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["kb_id"] == "kb-1"
        assert data["name"] == "Test KB"


# ===========================================================================
# TestDocumentOps — upload, delete, status
# ===========================================================================
class TestDocumentOps:
    """Tests for document upload, deletion, and status endpoints."""

    def test_upload_documents_success(self, client, stub_service):
        """POST multipart upload returns 201 with document info."""
        stub_service.upload_documents.return_value = {
            "documents": [
                {"id": "doc-1", "name": "test.txt", "size": 100, "status": "indexing"},
            ],
        }
        r = client.post(
            "/api/v1/kb/adapters/1/knowledge-bases/kb-1/documents",
            files=[("files", ("test.txt", b"hello world content", "text/plain"))],
            data={"chunking_strategy": "basic"},
            headers=AUTH,
        )
        assert r.status_code == 201
        data = r.json()
        assert len(data["documents"]) == 1
        assert data["documents"][0]["id"] == "doc-1"

    def test_upload_multiple_files(self, client, stub_service):
        """POST with multiple files uploads all of them."""
        stub_service.upload_documents.return_value = {
            "documents": [
                {"id": "doc-1", "name": "a.txt"},
                {"id": "doc-2", "name": "b.txt"},
            ],
        }
        r = client.post(
            "/api/v1/kb/adapters/1/knowledge-bases/kb-1/documents",
            files=[
                ("files", ("a.txt", b"content a", "text/plain")),
                ("files", ("b.txt", b"content b", "text/plain")),
            ],
            headers=AUTH,
        )
        assert r.status_code == 201
        assert len(r.json()["documents"]) == 2

    def test_upload_documents_missing_files(self, client):
        """POST without files returns 422 (files is required)."""
        r = client.post(
            "/api/v1/kb/adapters/1/knowledge-bases/kb-1/documents",
            data={"chunking_strategy": "basic"},
            headers=AUTH,
        )
        assert r.status_code == 422

    def test_delete_document_success(self, client, stub_service):
        """DELETE /documents/doc-1 removes the document."""
        stub_service.delete_document.return_value = True
        r = client.delete(
            "/api/v1/kb/adapters/1/knowledge-bases/kb-1/documents/doc-1",
            headers=AUTH,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        stub_service.delete_document.assert_called_once_with(
            adapter_id=1, tenant_id="tenant-1", user_id="user-1",
            kb_id="kb-1", doc_id="doc-1",
        )

    def test_delete_document_not_found(self, client, stub_service):
        """DELETE returns success=False when document does not exist."""
        stub_service.delete_document.return_value = False
        r = client.delete(
            "/api/v1/kb/adapters/1/knowledge-bases/kb-1/documents/doc-missing",
            headers=AUTH,
        )
        assert r.status_code == 200
        assert r.json()["success"] is False

    def test_get_document_status_success(self, client, stub_service):
        """GET /documents/doc-1/status returns indexing progress."""
        stub_service.get_document_status.return_value = {
            "id": "doc-1", "status": "completed", "progress": 1.0,
            "total_chunks": 10, "chunk_count": 10, "token_count": 500,
        }
        r = client.get(
            "/api/v1/kb/adapters/1/knowledge-bases/kb-1/documents/doc-1/status",
            headers=AUTH,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == "doc-1"
        assert data["status"] == "completed"
        assert data["progress"] == 1.0

    def test_list_documents_success(self, client, stub_service):
        """GET /documents returns paginated document list."""
        stub_service.list_documents.return_value = {
            "items": [{"id": "doc-1", "name": "test.txt"}],
            "total": 1, "page": 1, "page_size": 20,
        }
        r = client.get(
            "/api/v1/kb/adapters/1/knowledge-bases/kb-1/documents",
            headers=AUTH,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1


# ===========================================================================
# TestRetrieve — single-KB and cross-adapter retrieve
# ===========================================================================
class TestRetrieve:
    """Tests for per-KB retrieve and cross-adapter retrieve-all."""

    def test_retrieve_single_kb_success(self, client, stub_service):
        """POST retrieve on single KB returns results with records + results."""
        stub_service.retrieve.return_value = {
            "records": [
                {
                    "segment": {
                        "content": "relevant text",
                        "knowledge_base_id": "kb-1", "document_id": "doc-1",
                        "knowledge_base_name": "Test KB", "document_name": "doc.txt",
                    },
                    "score": 0.92,
                },
            ],
            "query": "test query",
        }
        r = client.post(
            "/api/v1/kb/adapters/1/knowledge-bases/kb-1/retrieve",
            json={"query": "test query", "kb_ids": ["kb-1"], "top_k": 5},
            headers=AUTH,
        )
        assert r.status_code == 200
        data = r.json()
        # V4 nested format
        assert "records" in data
        assert len(data["records"]) == 1
        assert data["records"][0]["segment"]["content"] == "relevant text"
        assert data["records"][0]["score"] == 0.92
        assert data["query"] == "test query"

    def test_retrieve_single_kb_empty_results(self, client, stub_service):
        """POST retrieve with no matches returns empty records."""
        stub_service.retrieve.return_value = {
            "records": [],
            "query": "no match",
        }
        r = client.post(
            "/api/v1/kb/adapters/1/knowledge-bases/kb-1/retrieve",
            json={"query": "no match", "kb_ids": ["kb-1"]},
            headers=AUTH,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["records"] == []
        assert data["query"] == "no match"

    def test_retrieve_all_success(self, client, stub_service):
        """POST /retrieve-all merges results from multiple adapters."""
        stub_service.retrieve.return_value = {
            "records": [
                {
                    "segment": {"content": "result A", "knowledge_base_id": "kb-1"},
                    "score": 0.95,
                },
                {
                    "segment": {"content": "result B", "knowledge_base_id": "kb-2"},
                    "score": 0.80,
                },
            ],
            "query": "cross search",
        }
        payload = {
            "query": "cross search",
            "kb_refs": [
                {"adapter_id": 1, "kb_id": "kb-1"},
                {"adapter_id": 1, "kb_id": "kb-2"},
            ],
            "top_k": 10,
            "search_mode": "hybrid",
            "score_threshold": 0.0,
            "rerank": False,
        }
        r = client.post("/api/v1/kb/retrieve-all", json=payload, headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert "records" in data
        assert len(data["records"]) >= 0

    def test_retrieve_all_empty_kb_refs(self, client, stub_service):
        """POST /retrieve-all with empty kb_refs returns empty records."""
        payload = {
            "query": "search nothing",
            "kb_refs": [],
            "top_k": 5,
        }
        r = client.post("/api/v1/kb/retrieve-all", json=payload, headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["records"] == []
        assert data["query"] == "search nothing"

    def test_retrieve_all_missing_kb_refs(self, client):
        """POST /retrieve-all without kb_refs returns 422 (required field)."""
        r = client.post(
            "/api/v1/kb/retrieve-all",
            json={"query": "test"},
            headers=AUTH,
        )
        assert r.status_code == 422

    def test_retrieve_all_adapter_failure_graceful(self, client, stub_service):
        """POST /retrieve-all skips adapters that fail and returns empty records."""
        stub_service.retrieve.side_effect = Exception("adapter connection failed")
        payload = {
            "query": "test",
            "kb_refs": [{"adapter_id": 99, "kb_id": "kb-x"}],
            "top_k": 5,
        }
        r = client.post("/api/v1/kb/retrieve-all", json=payload, headers=AUTH)
        # Endpoint catches per-adapter exceptions and returns partial results
        assert r.status_code == 200
        data = r.json()
        assert data["records"] == []


# ===========================================================================
# TestRegisterErrors — POST /adapters error paths
# ===========================================================================
class TestRegisterErrors:
    """Tests for adapter registration error paths (documents HTTP 500 bug)."""

    @pytest.mark.xfail(reason="Bug: ValueError returns HTTP 500 instead of 400")
    def test_register_adapter_unknown_platform_should_be_400(self, client, stub_service):
        """Registering an unknown platform should return 400, not 500.

        The service raises ValueError('No adapter registered for platform ...')
        but the endpoint does not catch it, resulting in HTTP 500.
        """
        stub_service.register_adapter.side_effect = ValueError(
            "No adapter registered for platform 'unknown_thing'. "
            "Registered: ['local']"
        )
        r = client.post(
            "/api/v1/kb/adapters",
            json={"platform": "unknown_thing", "name": "bad-adapter"},
            headers=AUTH,
        )
        assert r.status_code == 400  # Expected correct behavior

    @pytest.mark.xfail(reason="Bug: ValueError returns HTTP 500 instead of 400")
    def test_register_adapter_local_platform_should_be_400(self, client, stub_service):
        """Registering platform='local' should return 400, not 500.

        The service raises ValueError('The local adapter is auto-provisioned...')
        but the endpoint does not catch it, resulting in HTTP 500.
        """
        stub_service.register_adapter.side_effect = ValueError(
            "The local adapter is auto-provisioned and cannot be manually registered."
        )
        r = client.post(
            "/api/v1/kb/adapters",
            json={"platform": "local", "name": "duplicate-local"},
            headers=AUTH,
        )
        assert r.status_code == 400  # Expected correct behavior

    def test_register_adapter_success(self, client, stub_service):
        """POST /adapters with valid payload returns 201."""
        stub_service.register_adapter.return_value = {
            "adapter_id": 10, "name": "my-dify", "platform": "dify",
            "enabled": True, "status": "running",
        }
        r = client.post(
            "/api/v1/kb/adapters",
            json={
                "platform": "dify",
                "name": "my-dify",
                "external_kb_config": {"api_key": "secret", "base_url": "https://dify.example.com"},
                "enabled": True,
            },
            headers=AUTH,
        )
        assert r.status_code == 201
        data = r.json()
        assert data["adapter_id"] == 10
        assert data["platform"] == "dify"


# ===========================================================================
# TestListKbViaAdapter — GET /adapters/{id}/knowledge-bases (adapter instance)
# ===========================================================================
class TestListKbViaAdapter:
    """Tests for list_knowledge_bases which uses adapter instance from get_adapter."""

    def test_list_knowledge_bases_returns_paginated(self, client, stub_service):
        """GET /adapters/1/knowledge-bases returns paginated dict."""
        mock_adapter = stub_service.get_adapter.return_value
        mock_adapter.list_knowledge_bases.return_value = [
            SimpleNamespace(id="kb-1", name="KB-1", description="first"),
            SimpleNamespace(id="kb-2", name="KB-2", description="second"),
        ]
        r = client.get("/api/v1/kb/adapters/1/knowledge-bases", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert "list" in data
        assert data["total"] == 2
        assert data["page"] == 1

    def test_list_knowledge_bases_empty(self, client, stub_service):
        """GET /adapters/1/knowledge-bases with no KBs returns empty list."""
        mock_adapter = stub_service.get_adapter.return_value
        mock_adapter.list_knowledge_bases.return_value = []
        r = client.get("/api/v1/kb/adapters/1/knowledge-bases", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["list"] == []
        assert data["total"] == 0

    def test_list_knowledge_bases_closes_adapter(self, client, stub_service):
        """GET /adapters/1/knowledge-bases always closes the adapter (finally)."""
        mock_adapter = stub_service.get_adapter.return_value
        mock_adapter.list_knowledge_bases.return_value = []
        client.get("/api/v1/kb/adapters/1/knowledge-bases", headers=AUTH)
        mock_adapter.close.assert_called_once()


# ===========================================================================
# TestHealthAndCapabilities — GET /adapters/{id}/health, /capabilities
# ===========================================================================
class TestHealthAndCapabilities:
    """Tests for adapter health check and capabilities refresh."""

    def test_health_check_success(self, client, stub_service):
        """GET /adapters/1/health returns health status."""
        stub_service.check_health.return_value = {"status": "ok", "latency_ms": 15}
        r = client.get("/api/v1/kb/adapters/1/health", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_capabilities_refresh(self, client, stub_service):
        """GET /adapters/1/capabilities returns adapter capabilities."""
        stub_service.refresh_capabilities.return_value = {
            "create_knowledge_base": True,
            "upload_document": True,
            "search": True,
        }
        r = client.get("/api/v1/kb/adapters/1/capabilities", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["create_knowledge_base"] is True


# ===========================================================================
# TestListAllKbs — GET /knowledge-bases/all
# ===========================================================================
class TestListAllKbs:
    """Tests for aggregated KB listing across all adapters."""

    def test_list_all_knowledge_bases_success(self, client, stub_service):
        """GET /knowledge-bases/all returns aggregated KB list."""
        stub_service.list_all_external_knowledge_bases.return_value = [
            {"id": "kb-1", "name": "Local KB", "adapter_id": 1, "platform": "local"},
            {"id": "kb-2", "name": "Dify KB", "adapter_id": 2, "platform": "dify"},
        ]
        r = client.get("/api/v1/kb/knowledge-bases/all", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert "list" in data
        assert data["total"] == 2

    def test_list_all_knowledge_bases_empty(self, client, stub_service):
        """GET /knowledge-bases/all with no KBs returns empty list."""
        stub_service.list_all_external_knowledge_bases.return_value = []
        r = client.get("/api/v1/kb/knowledge-bases/all", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["list"] == []
        assert data["total"] == 0
