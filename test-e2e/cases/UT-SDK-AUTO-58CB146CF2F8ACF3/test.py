from __future__ import annotations

import pytest

from nexent.core.tools.ind_aidp_search_tool import (
    IndependentAidpSearchTool,
    _field_default,
    _parse_kds_list,
    _validate_base_url,
)
from nexent.utils.http_client_manager import http_client_manager

pytestmark = [
    pytest.mark.case_id("UT-SDK-AUTO-58CB146CF2F8ACF3"),
    pytest.mark.stage("D1"),
]

SERVER_URL = "https://aidp.example.com"
API_KEY = "ak_test"


def test_ind_aidp_search_tool_contract():
    try:
        assert _field_default("custom", "aidp") == "custom"
        assert _field_default(None, "aidp") == "aidp"

        with pytest.raises(ValueError, match="server_url is required"):
            _validate_base_url("")
        with pytest.raises(ValueError, match="absolute HTTP or HTTPS"):
            _validate_base_url("localhost:8080")
        with pytest.raises(ValueError, match="absolute HTTP or HTTPS"):
            _validate_base_url("ftp://host")
        with pytest.raises(ValueError, match="cannot contain credentials"):
            _validate_base_url("https://u:p@host")
        with pytest.raises(ValueError, match="cannot contain credentials"):
            _validate_base_url("https://host?a=1#f")
        assert _validate_base_url("  https://aidp.example.com/  ") == SERVER_URL

        with pytest.raises(ValueError, match="api_key is required and must be a non-empty string"):
            IndependentAidpSearchTool(server_url=SERVER_URL, api_key="", kds_list=["kb-1"])
        with pytest.raises(ValueError, match="api_key is required and must be a non-empty string"):
            IndependentAidpSearchTool(server_url=SERVER_URL, api_key="   ", kds_list=["kb-1"])
        with pytest.raises(ValueError, match="tenant_id is required and must be a non-empty string"):
            IndependentAidpSearchTool(
                server_url=SERVER_URL, api_key=API_KEY, tenant_id="", kds_list=["kb-1"]
            )

        default_tenant_tool = IndependentAidpSearchTool(
            server_url=SERVER_URL, api_key=API_KEY, kds_list=["kb-1"]
        )
        assert default_tenant_tool.tenant_id == "aidp"

        with pytest.raises(ValueError, match="kds_list must be a valid JSON array"):
            _parse_kds_list("not-json")
        with pytest.raises(ValueError, match="kds_list must contain 1-10 knowledge base IDs"):
            _parse_kds_list([])
        with pytest.raises(ValueError, match="kds_list must contain 1-10 knowledge base IDs"):
            _parse_kds_list([f"kb-{i}" for i in range(11)])
        with pytest.raises(ValueError, match="cannot contain empty knowledge base IDs"):
            _parse_kds_list(["", "kb-1"])
        assert _parse_kds_list('["kb-1","kb-2"]') == ["kb-1", "kb-2"]

        with pytest.raises(ValueError, match="kds_list must contain 1-10"):
            IndependentAidpSearchTool(server_url=SERVER_URL, api_key=API_KEY, kds_list=[])
        with pytest.raises(ValueError, match="cannot contain empty"):
            IndependentAidpSearchTool(
                server_url=SERVER_URL, api_key=API_KEY, kds_list=["", "kb-1"]
            )

        tool = IndependentAidpSearchTool(
            server_url=SERVER_URL, api_key=API_KEY, kds_list=["kb-1", "kb-2"]
        )
        assert tool.search_method == "hybrid_search"
        assert tool.reranking_enable is True
        assert tool.reranking_mode == "performance"
        assert tool.rewrite_enable is False
        assert tool.related_search_enable is False
        assert tool.score_threshold == 0.0
        assert tool.top_k == 10
        assert tool.multi_modal is True

        scope = tool._resolve_search_scope(None)
        assert scope.used_scope == ["kb-1", "kb-2"]
        assert scope.permission_denied_scope == []
        assert scope.unavailable_scope == []
        assert scope.fallback_to_all is False
        assert scope.scope_was_specified is False

        assert tool._payload("query", ["kb-9"])["kds_list"] == ["kb-9"]
        default_payload = tool._payload("query")
        assert default_payload["kds_list"] == ["kb-1", "kb-2"]

        with pytest.raises(ValueError, match="query is required and must be a non-empty string"):
            tool.forward("")

        assert "api_key" not in default_payload
        assert API_KEY not in str(default_payload)
    finally:
        http_client_manager.close_client(SERVER_URL, timeout=60.0, verify_ssl=False)
