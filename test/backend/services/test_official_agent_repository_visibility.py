from unittest.mock import patch

from services import agent_repository_service as repository_service


def _record(repository_id: int, tenant_id: str, status: str = "shared") -> dict:
    return {
        "agent_repository_id": repository_id,
        "agent_id": repository_id,
        "publisher_tenant_id": tenant_id,
        "status": status,
        "name": f"agent_{repository_id}",
        "display_name": f"Agent {repository_id}",
        "description": "description",
        "tags": [],
        "tool_count": 0,
        "downloads": 0,
        "content": "",
    }


def test_repository_list_merges_selected_official_shared_entries():
    with patch.object(repository_service, "OFFICIAL_AGENT_PROFILES", "medical"), \
         patch.object(repository_service, "list_agent_repository_summaries", side_effect=[
             [_record(1, "tenant-a")],
             [_record(2, "__nexent_official__")],
         ]), patch.object(
             repository_service,
             "sum_agent_repository_downloads_by_agent_ids",
             return_value={1: 0, 2: 0},
         ):
        result = repository_service.list_agent_repository_listings_impl("tenant-a")

    assert [item["agent_repository_id"] for item in result["items"]] == [1, 2]
    assert result["items"][1]["is_official"] is True


def test_official_detail_is_readable_but_is_marked_official():
    record = _record(2, "__nexent_official__")
    record["agent_info_json"] = {"agent_id": 2, "agent_info": {}, "mcp_info": []}
    with patch.object(repository_service, "OFFICIAL_AGENT_PROFILES", "medical"), \
         patch.object(repository_service, "get_agent_repository_by_id", side_effect=[None, record]), \
         patch.object(repository_service, "sum_agent_repository_downloads_by_agent_ids", return_value={2: 0}):
        result = repository_service.get_agent_repository_listing_detail_impl(2, "tenant-a")

    assert result["is_official"] is True
