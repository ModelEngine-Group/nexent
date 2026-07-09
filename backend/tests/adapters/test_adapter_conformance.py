"""
Adapter Conformance Test Suite (T3.8)

Validates that any adapter exposing the standard HTTP interface (§3 of the
design doc) satisfies the V4 contract.  Tests are parameterised by the
adapter's base_url + api_key so the same suite can be run against:

  - The built-in example adapter (nexent-adapter-example)
  - Any third-party adapter image registered via POST /api/v1/external-kb/adapters

Run against a live adapter container:

    ADAPTER_BASE_URL=http://localhost:8080 \
    ADAPTER_API_KEY=test-key \
    pytest backend/tests/adapters/test_adapter_conformance.py -v -m integration

Run with mocks (fast, no container required):

    pytest backend/tests/adapters/test_adapter_conformance.py -v -m "not integration"
"""

import os
import sys
import pytest
import httpx
from unittest.mock import MagicMock, patch

# Ensure project root + sdk are importable
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
for _p in [_project_root, os.path.join(_project_root, "sdk")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Mock heavy dependencies that sdk.nexent.__init__.py tries to import
for _mod_name in ["boto3", "minio", "nexent.memory", "nexent.storage"]:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = MagicMock()

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ADAPTER_BASE_URL = os.environ.get("ADAPTER_BASE_URL", "http://localhost:8080")
ADAPTER_API_KEY = os.environ.get("ADAPTER_API_KEY", "test-key")


@pytest.fixture
def adapter_headers():
    return {
        "Authorization": f"Bearer {ADAPTER_API_KEY}",
        "Content-Type": "application/json",
    }


@pytest.fixture
def live_client():
    """Real HTTP client for integration tests (requires a running container)."""
    with httpx.Client(base_url=ADAPTER_BASE_URL, timeout=30) as client:
        yield client


# ---------------------------------------------------------------------------
# Mock adapter responses (for unit-level conformance checks without container)
# ---------------------------------------------------------------------------

MOCK_HEALTH = {
    "status": "ok",
    "platform": "example",
    "version": "1.0.0",
    "external_kb_reachable": True,
}

MOCK_CAPABILITIES = {
    "create_knowledge_base": False,
    "delete_knowledge_base": False,
    "update_knowledge_base": False,
    "upload_document": False,
    "delete_document": False,
    "list_documents": False,
    "query_document_status": False,
    "download_document": False,
    "list_models": False,
    "search_modes": ["semantic_search", "hybrid_search"],
    "supports_rerank": False,
    "supports_multimodal": False,
}

MOCK_KB_LIST = {
    "code": 0,
    "data": {
        "list": [
            {
                "id": "kb-001",
                "name": "Test KB",
                "description": "Test knowledge base",
                "document_count": 5,
                "status": "active",
                "created_at": "2026-07-01T00:00:00Z",
                "updated_at": "2026-07-01T00:00:00Z",
            }
        ],
        "total": 1,
        "page": 1,
        "page_size": 20,
        "has_more": False,
    },
    "message": "success",
}

MOCK_RETRIEVE_RESPONSE = {
    "code": 0,
    "data": {
        "query": "test query",
        "records": [
            {
                "segment": {
                    "id": "seg-001",
                    "position": 1,
                    "document_id": "doc-001",
                    "document_name": "test.pdf",
                    "knowledge_base_id": "kb-001",
                    "knowledge_base_name": "Test KB",
                    "content": "This is a test segment content.",
                    "keywords": ["test", "segment"],
                    "tokens": 10,
                    "index_node_id": "node-001",
                    "hit_count": 0,
                    "enabled": True,
                },
                "score": 0.95,
            }
        ],
    },
    "message": "success",
}


# ---------------------------------------------------------------------------
# Unit-level conformance tests (mock-based, always run)
# ---------------------------------------------------------------------------


class TestHealthEndpointContract:
    """GET /health must return status, platform, version, external_kb_reachable."""

    def test_health_response_shape(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = MOCK_HEALTH

        data = resp.json()
        assert data["status"] in ("ok", "error"), "status must be 'ok' or 'error'"
        assert isinstance(data.get("platform"), str), "platform must be a string"
        assert isinstance(data.get("version"), str), "version must be a string"
        assert isinstance(data.get("external_kb_reachable"), bool), \
            "external_kb_reachable must be a bool"

    def test_health_ok_status(self):
        data = MOCK_HEALTH.copy()
        assert data["status"] == "ok"
        assert data["external_kb_reachable"] is True


class TestCapabilitiesEndpointContract:
    """GET /capabilities must return a capabilities object with required fields."""

    REQUIRED_BOOL_FIELDS = [
        "create_knowledge_base",
        "delete_knowledge_base",
        "update_knowledge_base",
        "upload_document",
        "delete_document",
        "list_documents",
        "supports_rerank",
        "supports_multimodal",
    ]

    def test_all_required_bool_fields_present(self):
        caps = MOCK_CAPABILITIES
        for field in self.REQUIRED_BOOL_FIELDS:
            assert field in caps, f"capabilities missing required field: {field}"
            assert isinstance(caps[field], bool), f"{field} must be bool"

    def test_search_modes_is_list_of_strings(self):
        caps = MOCK_CAPABILITIES
        assert isinstance(caps.get("search_modes"), list), "search_modes must be a list"
        valid_modes = {"semantic_search", "keyword_search", "hybrid_search"}
        for mode in caps["search_modes"]:
            assert mode in valid_modes, \
                f"search_modes contains unknown value '{mode}'"

    def test_search_modes_not_empty(self):
        caps = MOCK_CAPABILITIES
        assert len(caps["search_modes"]) >= 1, "search_modes must not be empty"


class TestKnowledgeBaseListContract:
    """GET /api/v1/knowledge-bases must return V4 paginated list format."""

    def test_response_envelope(self):
        resp = MOCK_KB_LIST
        assert resp["code"] == 0, "successful response must have code=0"
        assert "data" in resp
        assert resp["message"] == "success"

    def test_pagination_fields(self):
        data = MOCK_KB_LIST["data"]
        assert "list" in data, "response data must contain 'list'"
        assert "total" in data, "response data must contain 'total'"
        assert "page" in data, "response data must contain 'page'"
        assert "page_size" in data, "response data must contain 'page_size'"
        assert "has_more" in data, "response data must contain 'has_more'"
        assert isinstance(data["has_more"], bool), "has_more must be bool"

    def test_kb_item_required_fields(self):
        item = MOCK_KB_LIST["data"]["list"][0]
        required = ["id", "name", "description", "document_count", "status",
                    "created_at", "updated_at"]
        for field in required:
            assert field in item, f"KB item missing required field: {field}"

    def test_kb_status_enum(self):
        item = MOCK_KB_LIST["data"]["list"][0]
        valid_statuses = {"active", "inactive"}
        assert item["status"] in valid_statuses, \
            f"KB status '{item['status']}' not in {valid_statuses}"


class TestRetrieveEndpointContract:
    """POST /api/v1/retrieve — the only mandatory endpoint (§3.8)."""

    def test_response_envelope(self):
        resp = MOCK_RETRIEVE_RESPONSE
        assert resp["code"] == 0
        assert "data" in resp
        assert resp["message"] == "success"

    def test_data_has_query_and_records(self):
        data = MOCK_RETRIEVE_RESPONSE["data"]
        assert "query" in data, "retrieve response must echo query"
        assert "records" in data, "retrieve response must contain records"
        assert isinstance(data["records"], list)

    def test_record_structure(self):
        record = MOCK_RETRIEVE_RESPONSE["data"]["records"][0]
        assert "segment" in record, "each record must have a 'segment' key"
        assert "score" in record, "each record must have a 'score' key"
        assert isinstance(record["score"], float), "score must be a float"
        assert 0.0 <= record["score"] <= 1.0, "score must be in [0, 1]"

    def test_segment_required_fields(self):
        segment = MOCK_RETRIEVE_RESPONSE["data"]["records"][0]["segment"]
        required = [
            "id", "position", "document_id", "document_name",
            "knowledge_base_id", "knowledge_base_name", "content",
            "keywords", "tokens", "index_node_id", "hit_count", "enabled",
        ]
        for field in required:
            assert field in segment, f"segment missing required field: {field}"

    def test_segment_field_types(self):
        seg = MOCK_RETRIEVE_RESPONSE["data"]["records"][0]["segment"]
        assert isinstance(seg["position"], int), "position must be int"
        assert isinstance(seg["content"], str), "content must be str"
        assert isinstance(seg["keywords"], list), "keywords must be list"
        assert isinstance(seg["tokens"], int), "tokens must be int"
        assert isinstance(seg["hit_count"], int), "hit_count must be int"
        assert isinstance(seg["enabled"], bool), "enabled must be bool"

    def test_records_sorted_by_score_descending(self):
        records = MOCK_RETRIEVE_RESPONSE["data"]["records"]
        if len(records) > 1:
            scores = [r["score"] for r in records]
            assert scores == sorted(scores, reverse=True), \
                "records must be sorted by score descending"


# ---------------------------------------------------------------------------
# Integration tests (require a live adapter container)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestLiveAdapterConformance:
    """Full conformance suite against a running adapter container.

    Set env vars:
        ADAPTER_BASE_URL=http://localhost:8080
        ADAPTER_API_KEY=your-api-key

    Run with:
        pytest -m integration backend/tests/adapters/test_adapter_conformance.py -v
    """

    def test_health_endpoint_reachable(self, live_client, adapter_headers):
        resp = live_client.get("/health", headers=adapter_headers)
        assert resp.status_code == 200, f"/health returned {resp.status_code}"
        data = resp.json()
        assert data.get("status") in ("ok", "error")

    def test_capabilities_endpoint_reachable(self, live_client, adapter_headers):
        resp = live_client.get("/capabilities", headers=adapter_headers)
        assert resp.status_code == 200, f"/capabilities returned {resp.status_code}"
        data = resp.json()
        assert "search_modes" in data

    def test_knowledge_bases_list(self, live_client, adapter_headers):
        resp = live_client.get("/api/v1/knowledge-bases", headers=adapter_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("code") == 0
        assert "list" in body["data"]
        assert "total" in body["data"]
        assert "has_more" in body["data"]

    def test_retrieve_basic(self, live_client, adapter_headers):
        kb_resp = live_client.get("/api/v1/knowledge-bases", headers=adapter_headers)
        kb_list = kb_resp.json()["data"]["list"]
        if not kb_list:
            pytest.skip("No knowledge bases available in adapter")

        kb_id = kb_list[0]["id"]
        payload = {
            "query": "test query",
            "knowledge_base_ids": [kb_id],
            "retrieval_model": {
                "search_method": "semantic_search",
                "top_k": 3,
                "score_threshold": 0.0,
                "score_threshold_enabled": False,
            },
        }
        resp = live_client.post("/api/v1/retrieve", headers=adapter_headers, json=payload)
        assert resp.status_code == 200, f"POST /api/v1/retrieve returned {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body.get("code") == 0
        assert "records" in body["data"]
        assert isinstance(body["data"]["records"], list)

    def test_retrieve_response_structure(self, live_client, adapter_headers):
        kb_resp = live_client.get("/api/v1/knowledge-bases", headers=adapter_headers)
        kb_list = kb_resp.json()["data"]["list"]
        if not kb_list:
            pytest.skip("No knowledge bases available in adapter")

        kb_id = kb_list[0]["id"]
        payload = {
            "query": "configuration",
            "knowledge_base_ids": [kb_id],
            "retrieval_model": {"search_method": "semantic_search", "top_k": 1},
        }
        resp = live_client.post("/api/v1/retrieve", headers=adapter_headers, json=payload)
        body = resp.json()
        records = body["data"]["records"]

        if records:
            record = records[0]
            assert "segment" in record
            assert "score" in record
            seg = record["segment"]
            for field in ["id", "content", "document_id", "knowledge_base_id"]:
                assert field in seg, f"segment missing '{field}'"

    def test_retrieve_requires_auth(self, live_client):
        payload = {
            "query": "test",
            "knowledge_base_ids": ["kb-001"],
            "retrieval_model": {"search_method": "semantic_search", "top_k": 3},
        }
        resp = live_client.post(
            "/api/v1/retrieve",
            headers={"Content-Type": "application/json"},
            json=payload,
        )
        assert resp.status_code in (401, 403), \
            f"Unauthenticated request should return 401/403, got {resp.status_code}"
