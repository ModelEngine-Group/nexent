"""D1 backend policy tests for repository, sharing, runtime and memory."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


STAGE = pytest.mark.stage("D1")


@STAGE
@pytest.mark.case_id("UT-BE-013")
def test_repository_precheck_extracts_and_deduplicates_dependencies() -> None:
    from services.repository_import_precheck import (
        _extract_mcp_server_names,
        _extract_skill_names,
        _tool_lookup_key,
    )

    snapshot = SimpleNamespace(
        skills=[{"skill_name": "alpha"}, {"skill_name": "alpha"}, {"skill_name": "beta"}],
        mcp_info=[{"mcp_server_name": "mcp-a"}, {"mcp_server_name": "mcp-a"}],
        agent_info={},
    )
    assert _extract_skill_names(snapshot) == ["alpha", "beta"]
    assert _extract_mcp_server_names(snapshot) == {"mcp-a"}
    assert _tool_lookup_key("SearchTool", "local") == "SearchTool&local"
























