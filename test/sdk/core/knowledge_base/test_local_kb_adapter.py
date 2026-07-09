"""
Unit tests for LocalKBAdapter (sdk/nexent/core/knowledge_base/platform_adapters.py).

Verifies that LocalKBAdapter correctly implements the ExternalKBAdapter ABC contract
and routes calls through the backend service pipeline (ElasticSearchService,
file_management_service, document_db).

Strategy:
  - Mock ElasticSearchCore for ES-level paths (search, list_knowledge_bases fallback).
  - Patch backend services used by the bridge implementations (create/delete/upload).
  - Follow pytest fixture + pytest-mock conventions per project rules.
"""
import os
import sys
import pytest
from unittest.mock import MagicMock

# Ensure backend + sdk are importable in test runner
_test_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
for _p in [os.path.join(_test_root, "backend"), os.path.join(_test_root, "sdk")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nexent.core.knowledge_base.platform_adapters import (
    LocalKBAdapter,
    ExternalKBAdapter,
    ExternalKBAdapterRegistry,
    AdapterCapabilities,
    KnowledgeBaseInfo,
    SearchRequest,
    SearchResponse,
    SearchResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_es_core():
    """Mock ElasticSearchCore used by fallback (no-PG) paths."""
    core = MagicMock()
    core.client.cluster.health.return_value = {"status": "ok", "external_kb_reachable": True}
    core.get_user_indices.return_value = ["idx-1", "idx-2"]
    core.count_documents.return_value = 5
    core.get_documents_detail.return_value = [
        {"document_id": "doc-1", "name": "doc1.pdf", "file_size": 1024, "chunk_count": 10}
    ]
    core.check_index_exists.return_value = True
    core.create_index.return_value = None
    core.delete_index.return_value = None
    core.hybrid_search.return_value = [
        {
            "score": 0.95,
            "document": {
                "id": "seg-1",
                "content": "chunk-content",
                "title": "Doc Title",
                "filename": "doc.pdf",
                "path_or_url": "/doc.pdf",
            },
            "index": "idx-1",
            "scores": {"accurate": 0.8, "semantic": 0.95},
        }
    ]
    return core


@pytest.fixture
def local_adapter(mock_es_core):
    """LocalKBAdapter with injected mock ElasticSearchCore."""
    return LocalKBAdapter(
        config={"tenant_id": "tenant-A", "es_host": "http://mock-es:9200"},
        vdb_core=mock_es_core,
    )


# ---------------------------------------------------------------------------
# ABC contract tests
# ---------------------------------------------------------------------------

def test_local_adapter_is_external_kb_adapter(local_adapter):
    assert isinstance(local_adapter, ExternalKBAdapter)
    assert local_adapter.platform == "local"


def test_local_adapter_registered_in_registry():
    adapter_cls = ExternalKBAdapterRegistry.get("local")
    assert adapter_cls is LocalKBAdapter


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------

def test_health_check_ok(local_adapter, mock_es_core):
    result = local_adapter.health_check()
    assert result["status"] == "ok"
    mock_es_core.client.cluster.health.assert_called_once()


def test_health_check_handles_exception(local_adapter, mock_es_core):
    mock_es_core.client.cluster.health.side_effect = Exception("ES down")
    result = local_adapter.health_check()
    assert result["status"] == "error"
    assert "message" in result
    assert result["platform"] == "local"
    assert "version" in result


# ---------------------------------------------------------------------------
# get_capabilities
# ---------------------------------------------------------------------------

def test_get_capabilities(local_adapter):
    caps = local_adapter.get_capabilities()
    assert isinstance(caps, AdapterCapabilities)
    assert caps.create_knowledge_base is True
    assert caps.delete_knowledge_base is True
    assert caps.update_knowledge_base is True
    assert caps.upload_document is True
    assert caps.delete_document is True
    assert caps.list_documents is True
    assert caps.query_document_status is True
    assert caps.download_document is True
    assert "hybrid" in caps.search_modes
    assert "semantic" in caps.search_modes
    assert "accurate" in caps.search_modes
    # Local adapter resolves its own embedding model — caller NOT required to supply one
    assert caps.requires_embedding_model is False
    assert caps.supports_custom_embedding_model is False


def test_capabilities_property_delegates_to_get_capabilities(local_adapter):
    """The `capabilities` property must return the same AdapterCapabilities
    the explicit `get_capabilities()` method does — this is what dispatcher
    code reads (`impl.capabilities.create_knowledge_base`)."""
    from_prop = local_adapter.capabilities
    from_method = local_adapter.get_capabilities()
    assert isinstance(from_prop, AdapterCapabilities)
    assert from_prop.create_knowledge_base == from_method.create_knowledge_base
    assert from_prop.delete_knowledge_base == from_method.delete_knowledge_base
    assert from_prop.upload_document == from_method.upload_document
    assert from_prop.search_modes == from_method.search_modes


# ---------------------------------------------------------------------------
# list_knowledge_bases — ES fallback path (PG mock raises)
# ---------------------------------------------------------------------------

def test_list_knowledge_bases_falls_back_to_es_when_pg_unavailable(
    local_adapter, mock_es_core, monkeypatch
):
    """When database.knowledge_db.get_knowledge_info_by_tenant_id is unavailable/raises,
    the adapter falls back to ElasticSearchCore enumeration."""
    def _raise_pg(*args, **kwargs):
        raise RuntimeError("PG down")
    monkeypatch.setattr(
        "database.knowledge_db.get_knowledge_info_by_tenant_id", _raise_pg
    )

    mock_es_core.get_user_indices.return_value = ["idx-1", "idx-2"]
    mock_es_core.count_documents.return_value = 10
    mock_es_core.get_documents_detail.return_value = [{"document_id": "d1", "name": "doc.pdf"}]

    results = local_adapter.list_knowledge_bases(keyword="idx-1", page=1, page_size=10)
    assert len(results) == 1
    assert isinstance(results[0], KnowledgeBaseInfo)
    assert results[0].id == "idx-1"
    assert results[0].name == "idx-1"


def test_list_knowledge_bases_uses_pg_when_available(local_adapter, monkeypatch):
    """When PG is reachable, list_knowledge_bases returns rows with human-readable names."""
    def _fake_rows(tenant_id):
        return [
            {
                "knowledge_id": 42,
                "knowledge_name": "产品手册",
                "knowledge_describe": "doc description",
                "document_count": 3,
                "chunk_count": 9,
                "embedding_model_name": "text-embedding-v3",
                "index_name": "42-abc",
                "create_time": "2026-01-01",
            }
        ]
    monkeypatch.setattr(
        "database.knowledge_db.get_knowledge_info_by_tenant_id", _fake_rows
    )

    results = local_adapter.list_knowledge_bases(page=1, page_size=10)
    assert len(results) == 1
    assert results[0].id == "42"
    assert results[0].name == "产品手册"
    assert results[0].embedding_model == "text-embedding-v3"


def test_list_knowledge_bases_pagination(local_adapter, mock_es_core, monkeypatch):
    def _raise_pg(*args, **kwargs):
        raise RuntimeError("PG down")
    monkeypatch.setattr(
        "database.knowledge_db.get_knowledge_info_by_tenant_id", _raise_pg
    )
    mock_es_core.get_user_indices.return_value = [f"idx-{i}" for i in range(30)]
    mock_es_core.count_documents.return_value = 1
    mock_es_core.get_documents_detail.return_value = []

    page1 = local_adapter.list_knowledge_bases(page=1, page_size=10)
    assert len(page1) == 10
    page2 = local_adapter.list_knowledge_bases(page=2, page_size=10)
    assert len(page2) == 10


# ---------------------------------------------------------------------------
# get_knowledge_base
# ---------------------------------------------------------------------------

def test_get_knowledge_base_uses_pg_when_available(local_adapter, monkeypatch):
    monkeypatch.setattr(
        "database.knowledge_db.get_knowledge_record",
        lambda query: {
            "knowledge_id": 7,
            "knowledge_name": "FAQ",
            "knowledge_describe": "frequently asked",
            "document_count": 2,
            "chunk_count": 12,
            "embedding_model_name": "text-embedding-v3",
            "index_name": "7-xyz",
            "is_multimodal": False,
        },
    )
    kb = local_adapter.get_knowledge_base("7")
    assert isinstance(kb, KnowledgeBaseInfo)
    assert kb.id == "7"
    assert kb.name == "FAQ"
    assert kb.document_count == 2


def test_get_knowledge_base_falls_back_to_es_when_pg_unavailable(
    local_adapter, mock_es_core, monkeypatch
):
    monkeypatch.setattr(
        "database.knowledge_db.get_knowledge_record",
        lambda query: None,
    )
    mock_es_core.count_documents.return_value = 42
    mock_es_core.get_documents_detail.return_value = []

    kb = local_adapter.get_knowledge_base("idx-1")
    assert isinstance(kb, KnowledgeBaseInfo)
    assert kb.id == "idx-1"
    assert kb.chunk_count == 42


def test_get_knowledge_base_not_found(local_adapter, mock_es_core, monkeypatch):
    monkeypatch.setattr(
        "database.knowledge_db.get_knowledge_record",
        lambda query: None,
    )
    mock_es_core.check_index_exists.return_value = False
    with pytest.raises(ValueError, match="does not exist"):
        local_adapter.get_knowledge_base("nonexistent")


# ---------------------------------------------------------------------------
# create_knowledge_base — delegates to ElasticSearchService.create_knowledge_base
# ---------------------------------------------------------------------------

def test_create_knowledge_base_success(local_adapter, monkeypatch):
    fake = MagicMock()
    fake.create_knowledge_base.return_value = {
        "status": "success",
        "knowledge_id": 101,
        "id": "101-abc",
        "name": "new-kb",
        "embedding_model_name": "text-embedding-v3",
    }
    monkeypatch.setattr(
        "services.vectordatabase_service.ElasticSearchService", fake
    )
    monkeypatch.setattr(
        "services.vectordatabase_service.get_vector_db_core",
        lambda: MagicMock(),
    )

    result = local_adapter.create_knowledge_base(
        name="new-kb", description="desc", embedding_model="text-embedding-v3"
    )
    assert isinstance(result, KnowledgeBaseInfo)
    assert result.id == "101"
    assert result.name == "new-kb"
    assert result.embedding_model == "text-embedding-v3"
    fake.create_knowledge_base.assert_called_once()


def test_create_knowledge_base_failure_raises(local_adapter, monkeypatch):
    fake = MagicMock()
    fake.create_knowledge_base.return_value = {
        "status": "error",
        "message": "index already exists",
    }
    monkeypatch.setattr(
        "services.vectordatabase_service.ElasticSearchService", fake
    )
    monkeypatch.setattr(
        "services.vectordatabase_service.get_vector_db_core",
        lambda: MagicMock(),
    )

    with pytest.raises(RuntimeError, match="already exists"):
        local_adapter.create_knowledge_base(name="dup")


# ---------------------------------------------------------------------------
# delete_knowledge_base — delegates to ElasticSearchService.full_delete_knowledge_base
# ---------------------------------------------------------------------------

def test_delete_knowledge_base_calls_full_delete(local_adapter, monkeypatch):
    fake = MagicMock()

    async def _fake_full_delete(index_name, vdb_core, user_id):
        return True

    fake.full_delete_knowledge_base = _fake_full_delete
    monkeypatch.setattr(
        "services.vectordatabase_service.ElasticSearchService", fake
    )
    monkeypatch.setattr(
        "services.vectordatabase_service.get_vector_db_core",
        lambda: MagicMock(),
    )
    monkeypatch.setattr(
        "nexent.core.knowledge_base.platform_adapters._resolve_index_name",
        lambda kb_id, tenant_id: "42-abc",
    )

    # Should not raise
    local_adapter.delete_knowledge_base("42")


# ---------------------------------------------------------------------------
# search (search_mode dispatch)
# ---------------------------------------------------------------------------

def test_search_hybrid(local_adapter, mock_es_core):
    req = SearchRequest(query="hello", kb_ids=["idx-1"], top_k=5, search_mode="hybrid")
    resp = local_adapter.search(req)
    assert isinstance(resp, SearchResponse)
    assert len(resp.results) == 1
    assert isinstance(resp.results[0], SearchResult)
    assert resp.results[0].content == "chunk-content"
    assert resp.results[0].score == 0.95
    mock_es_core.hybrid_search.assert_called_once()


def test_search_semantic(local_adapter, mock_es_core):
    req = SearchRequest(query="hello", kb_ids=["idx-1"], top_k=5, search_mode="semantic")
    local_adapter.search(req)
    mock_es_core.semantic_search.assert_called_once()
    mock_es_core.accurate_search.assert_not_called()


def test_search_accurate(local_adapter, mock_es_core):
    req = SearchRequest(query="hello", kb_ids=["idx-1"], top_k=5, search_mode="accurate")
    local_adapter.search(req)
    mock_es_core.accurate_search.assert_called_once()


def test_search_empty_kb_ids_returns_empty(local_adapter, mock_es_core):
    """When both kb_ids is empty AND get_user_indices() returns [], adapter returns
    an empty SearchResponse without delegating to ES search methods."""
    mock_es_core.get_user_indices.return_value = []
    req = SearchRequest(query="hello", kb_ids=[], top_k=5)
    resp = local_adapter.search(req)
    assert resp.results == []
    mock_es_core.hybrid_search.assert_not_called()


# ---------------------------------------------------------------------------
# V4 standard → canonical search_mode mapping
# ---------------------------------------------------------------------------

def test_search_v4_hybrid_search_maps_to_hybrid(local_adapter, mock_es_core):
    """V4 standard 'hybrid_search' must dispatch to core.hybrid_search."""
    req = SearchRequest(query="q", kb_ids=["idx-1"], top_k=5, search_mode="hybrid_search")
    local_adapter.search(req)
    mock_es_core.hybrid_search.assert_called_once()
    mock_es_core.semantic_search.assert_not_called()
    mock_es_core.accurate_search.assert_not_called()


def test_search_v4_semantic_search_maps_to_semantic(local_adapter, mock_es_core):
    """V4 standard 'semantic_search' must dispatch to core.semantic_search."""
    req = SearchRequest(query="q", kb_ids=["idx-1"], top_k=5, search_mode="semantic_search")
    local_adapter.search(req)
    mock_es_core.semantic_search.assert_called_once()
    mock_es_core.hybrid_search.assert_not_called()
    mock_es_core.accurate_search.assert_not_called()


def test_search_v4_keyword_search_maps_to_accurate(local_adapter, mock_es_core):
    """V4 standard 'keyword_search' must dispatch to core.accurate_search."""
    req = SearchRequest(query="q", kb_ids=["idx-1"], top_k=5, search_mode="keyword_search")
    local_adapter.search(req)
    mock_es_core.accurate_search.assert_called_once()
    mock_es_core.hybrid_search.assert_not_called()
    mock_es_core.semantic_search.assert_not_called()


# ---------------------------------------------------------------------------
# list_documents — dict response contract
# ---------------------------------------------------------------------------

def test_list_documents_returns_dict_with_items(local_adapter, mock_es_core, monkeypatch):
    monkeypatch.setattr(
        "database.document_db.list_document_records",
        lambda **kwargs: {
            "records": [
                {
                    "document_uuid": "u-1",
                    "filename": "doc1.pdf",
                    "status": "success",
                    "chunk_count": 5,
                    "file_size": 1024,
                    "create_time": None,
                    "error_message": None,
                }
            ],
            "total": 1,
        },
    )
    # _normalize_doc_status maps "success" → "completed" via _DOC_STATUS_MAP
    result = local_adapter.list_documents("42")
    assert isinstance(result, dict)
    assert "list" in result and "total" in result
    assert result["list"][0]["id"] == "u-1"
    assert result["list"][0]["status"] == "completed"


# ---------------------------------------------------------------------------
# upload_documents delegates to file_management_service pipeline
# ---------------------------------------------------------------------------

def test_upload_documents_pipeline(local_adapter, monkeypatch):
    captured = {}

    async def _fake_upload(**kwargs):
        captured.update(kwargs)
        return [], ["/m/file1.pdf"], ["file1.pdf"]

    async def _fake_trigger(**kwargs):
        return {"tasks": 1}

    monkeypatch.setattr(
        "services.file_management_service.upload_files_impl", _fake_upload
    )
    monkeypatch.setattr(
        "utils.file_management_utils.trigger_data_process", _fake_trigger
    )
    monkeypatch.setattr(
        "utils.auth_utils.generate_session_jwt", lambda user_id, **kw: "jwt"
    )
    monkeypatch.setattr(
        "nexent.core.knowledge_base.platform_adapters._resolve_index_name",
        lambda kb_id, tenant_id: "42-abc",
    )
    monkeypatch.setattr(
        "database.document_db.create_document_record",
        lambda data: {"document_uuid": "uuid-1"},
    )

    result = local_adapter.upload_documents(
        "42", upload_files=[MagicMock(filename="file1.pdf")]
    )
    assert "document_ids" in result
    assert "uuid-1" in result["document_ids"]


def test_upload_documents_with_custom_chunking_strategy(local_adapter, monkeypatch):
    """Custom chunking_strategy is forwarded to ProcessParams and then to trigger_data_process."""
    captured = {}

    async def _fake_upload(**kwargs):
        return [], ["/m/file1.pdf"], ["file1.pdf"]

    async def _fake_trigger(**kwargs):
        captured["process_params"] = kwargs.get("process_params")
        return {"tasks": 1}

    monkeypatch.setattr(
        "services.file_management_service.upload_files_impl", _fake_upload
    )
    monkeypatch.setattr(
        "utils.file_management_utils.trigger_data_process", _fake_trigger
    )
    monkeypatch.setattr(
        "utils.auth_utils.generate_session_jwt", lambda user_id, **kw: "jwt"
    )
    monkeypatch.setattr(
        "nexent.core.knowledge_base.platform_adapters._resolve_index_name",
        lambda kb_id, tenant_id: "42-abc",
    )
    monkeypatch.setattr(
        "database.document_db.create_document_record",
        lambda data: {"document_uuid": "uuid-1"},
    )

    result = local_adapter.upload_documents(
        "42", upload_files=[MagicMock(filename="file1.pdf")], chunking_strategy="table"
    )
    assert captured["process_params"].chunking_strategy == "table"
    assert isinstance(result, dict)
    assert "document_ids" in result


def test_upload_documents_default_chunking_strategy_is_basic(local_adapter, monkeypatch):
    """When chunking_strategy is not provided, it defaults to 'basic'."""
    captured = {}

    async def _fake_upload(**kwargs):
        return [], ["/m/file1.pdf"], ["file1.pdf"]

    async def _fake_trigger(**kwargs):
        captured["process_params"] = kwargs.get("process_params")
        return {"tasks": 1}

    monkeypatch.setattr(
        "services.file_management_service.upload_files_impl", _fake_upload
    )
    monkeypatch.setattr(
        "utils.file_management_utils.trigger_data_process", _fake_trigger
    )
    monkeypatch.setattr(
        "utils.auth_utils.generate_session_jwt", lambda user_id, **kw: "jwt"
    )
    monkeypatch.setattr(
        "nexent.core.knowledge_base.platform_adapters._resolve_index_name",
        lambda kb_id, tenant_id: "42-abc",
    )
    monkeypatch.setattr(
        "database.document_db.create_document_record",
        lambda data: {"document_uuid": "uuid-1"},
    )

    result = local_adapter.upload_documents(
        "42", upload_files=[MagicMock(filename="file1.pdf")]
    )
    assert captured["process_params"].chunking_strategy == "basic"
    assert isinstance(result, dict)
    assert "document_ids" in result


def test_upload_documents_empty_files_returns_error(local_adapter):
    result = local_adapter.upload_documents("42", upload_files=[])
    assert "errors" in result and result["documents"] == []


# ---------------------------------------------------------------------------
# delete_document — ES + PG soft-delete
# ---------------------------------------------------------------------------

def test_delete_document_calls_es_and_pg(local_adapter, monkeypatch):
    captured = {}

    async def _fake_delete_by_scope(index_name, path_or_url, scope, vdb_core):
        captured["path"] = path_or_url
        return {"deleted_es_count": 3, "message": "done"}

    fake_es = MagicMock()
    fake_es.delete_document_by_scope = _fake_delete_by_scope
    monkeypatch.setattr(
        "services.vectordatabase_service.ElasticSearchService", fake_es
    )
    monkeypatch.setattr(
        "services.vectordatabase_service.get_vector_db_core",
        lambda: MagicMock(),
    )
    monkeypatch.setattr(
        "nexent.core.knowledge_base.platform_adapters._resolve_index_name",
        lambda kb_id, tenant_id: "42-abc",
    )
    monkeypatch.setattr(
        "database.document_db.get_document_record_by_uuid",
        lambda doc_id: {"source_uri": "/m/file.pdf"},
    )
    monkeypatch.setattr(
        "database.document_db.soft_delete_document_record",
        lambda kb_id, path, user_id: True,
    )

    assert local_adapter.delete_document("42", "doc-1") is True
    assert captured["path"] == "/m/file.pdf"


# ---------------------------------------------------------------------------
# get_document_status — PG primary, raises on total miss
# ---------------------------------------------------------------------------

def test_get_document_status_pg_primary(local_adapter, monkeypatch):
    monkeypatch.setattr(
        "database.document_db.get_document_record_by_uuid",
        lambda doc_id: {
            "filename": "doc.pdf",
            "status": "success",
            "chunk_count": 7,
            "error_message": None,
        },
    )
    result = local_adapter.get_document_status("42", "doc-1")
    assert result["id"] == "doc-1"
    assert result["status"] == "success"
    assert result["chunk_count"] == 7


def test_get_document_status_not_found_raises(local_adapter, monkeypatch):
    monkeypatch.setattr(
        "database.document_db.get_document_record_by_uuid",
        lambda doc_id: None,
    )
    monkeypatch.setattr(
        "nexent.core.knowledge_base.platform_adapters._decode_doc_id",
        lambda doc_id: None,
    )
    with pytest.raises(ValueError, match="not found"):
        local_adapter.get_document_status("42", "ghost-doc")


# ---------------------------------------------------------------------------
# get_document_download_url
# ---------------------------------------------------------------------------

def test_get_document_download_url_via_pg(local_adapter, monkeypatch):
    monkeypatch.setattr(
        "database.document_db.get_document_record_by_uuid",
        lambda doc_id: {"source_uri": "/m/file.pdf", "filename": "file.pdf"},
    )

    async def _fake_url(object_name, expires):
        return {"url": "https://minio/file?sig=xyz"}

    monkeypatch.setattr(
        "services.file_management_service.get_file_url_impl", _fake_url
    )

    result = local_adapter.get_document_download_url("42", "doc-1")
    assert result["download_url"] == "https://minio/file?sig=xyz"
    assert result["filename"] == "file.pdf"
    assert "expires_at" in result


def test_get_document_download_url_unknown_doc_raises(local_adapter, monkeypatch):
    monkeypatch.setattr(
        "database.document_db.get_document_record_by_uuid",
        lambda doc_id: None,
    )
    monkeypatch.setattr(
        "nexent.core.knowledge_base.platform_adapters._decode_doc_id",
        lambda doc_id: None,
    )
    with pytest.raises(ValueError, match="Cannot resolve"):
        local_adapter.get_document_download_url("42", "ghost-doc")


# ---------------------------------------------------------------------------
# Contract assertions (dataclass types)
# ---------------------------------------------------------------------------

def test_list_knowledge_bases_returns_dataclass(local_adapter, monkeypatch):
    monkeypatch.setattr(
        "database.knowledge_db.get_knowledge_info_by_tenant_id",
        lambda tenant_id: [
            {"knowledge_id": 1, "knowledge_name": "n", "knowledge_describe": "",
             "document_count": 0, "chunk_count": 0, "embedding_model_name": "",
             "index_name": "1-x", "create_time": ""}
        ],
    )
    results = local_adapter.list_knowledge_bases(page=1, page_size=10)
    assert all(isinstance(r, KnowledgeBaseInfo) for r in results)


def test_search_returns_search_response_dataclass(local_adapter, mock_es_core):
    req = SearchRequest(query="q", kb_ids=["idx-1"], top_k=5, search_mode="accurate")
    resp = local_adapter.search(req)
    assert isinstance(resp, SearchResponse)
    assert all(isinstance(r, SearchResult) for r in resp.results)
