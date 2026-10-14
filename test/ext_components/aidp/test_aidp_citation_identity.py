from test.ext_components.aidp.test_aidp_search_tool import aidp_module as aidp_module
from test.ext_components.aidp.test_aidp_search_tool import aidp_tool as aidp_tool
from test.ext_components.aidp.test_aidp_search_tool import mock_observer as mock_observer


def test_aidp_tools_sharing_run_observer_have_distinct_citations(aidp_module, aidp_tool):
    """A filename cannot disambiguate duplicate markers from separate tool instances."""
    observer = aidp_module.MessageObserver()
    aidp_tool.observer = observer
    second = aidp_module.AidpSearchTool(
        server_url="https://aidp.example.com", api_key="test-key",
        tenant_id="aidp", kds_list='["kb1"]', observer=observer,
        search_method="hybrid_search", reranking_mode="performance",
    )
    first_ui, first_model, _ = aidp_tool._process_records([
        {"id": "chunk-first", "title": "same.pdf", "text": "first", "metadata": {"section": 0}}
    ])
    second_ui, second_model, _ = second._process_records([
        {"id": "chunk-second", "title": "same.pdf", "text": "second", "metadata": {"section": False}}
    ])
    first_key = f"{first_ui[0]['tool_sign']}{first_ui[0]['cite_index']}"
    second_key = f"{second_ui[0]['tool_sign']}{second_ui[0]['cite_index']}"
    assert first_key != second_key
    assert first_model[0]["reference_mark"] == f"[[{first_key}]]"
    assert second_model[0]["reference_mark"] == f"[[{second_key}]]"


def test_aidp_hit_preserves_metadata_without_inventing_file_identity(aidp_tool):
    metadata = {"自定义": 0, "enabled": False, "tags": [0, False, "中文"], "standards": {"code": {"level": "E"}}}
    message = aidp_tool._build_chunk_message({
        "id": "chunk-is-not-file-uuid", "title": "same.pdf", "metadata": metadata,
        "retrieval_source": "vector", "file_url": "/md_image/chunk.png",
    }, 0).to_dict()
    assert message["score_details"]["metadata"] == metadata
    assert message["score_details"]["retrieval_source"] == "vector"
    assert message["score_details"]["chunk_id"] == "chunk-is-not-file-uuid"
    assert "download_locator" not in message["score_details"]
