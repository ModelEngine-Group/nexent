# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Regression coverage for platform AIDP agent transfers."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))

from consts.exceptions import (
    AgentToolImportError,
)
from management.services.agent.policy import portable_tool_params, validate_import_tool_params


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


def test_advanced_policy_roundtrip_against_old_catalog():
    config={"top_k":7,"vector_candidates":None,"full_text_candidates":30,
            "graph_top_k":0,"query_expansion_enable":False,"reranking_mode":"jargon_coverage"}
    result=validate_import_tool_params("AidpSearchTool","local",config,{"params":[]})
    assert result==config
    assert result is not config
    with pytest.raises(AgentToolImportError,match="graph_reranking_enable"):
        validate_import_tool_params("IndependentAidpSearchTool","local",{"reranking_enable":False,"graph_reranking_enable":True},{"params":[]})
