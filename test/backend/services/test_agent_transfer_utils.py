"""Regression coverage for platform AIDP agent transfers."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))

from utils.agent_transfer_utils import (
    AgentToolImportError,
    portable_tool_params,
    validate_import_tool_params,
)


def test_aidp_runtime_fields_are_removed_without_mutating_snapshot():
    params = {"api_key": "secret", "server_url": "private", "tenant_id": "old",
              "kds_list": ["kb"], "top_k": 5}
    result = validate_import_tool_params(
        "AidpSearchTool", "local", params,
        {"params": [{"name": "kds_list"}, {"name": "top_k"}]},
    )
    assert result == {"kds_list": ["kb"], "top_k": 5}
    result["kds_list"].append("another")
    assert params["kds_list"] == ["kb"]
    assert params["api_key"] == "secret"


@pytest.mark.parametrize("class_name", ["IndependentAidpSearchTool", "OtherTool"])
def test_other_tools_keep_their_own_credentials(class_name):
    assert portable_tool_params(class_name, {"api_key": "own"}) == {"api_key": "own"}


def test_unknown_business_parameter_is_not_silently_dropped():
    with pytest.raises(AgentToolImportError, match="unexpected"):
        validate_import_tool_params("AidpSearchTool", "local", {"unexpected": 1}, {"params": []})


def test_missing_tool_reports_domain_error():
    with pytest.raises(AgentToolImportError, match="Cannot find tool"):
        validate_import_tool_params("AidpSearchTool", "local", {}, None)
