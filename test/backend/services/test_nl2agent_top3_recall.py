# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Strict route quotas, bilingual vector union and terminal uncovered results."""
import ast
import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from contracts.constants import environment
from contracts.configuration import parse_positive_float
from contracts.nl2agent_resources import RequirementDiscoveryInput, VerificationCheck
from services import nl2agent_resource_flow as flow


def resource(index, installed=True):
    return {"candidate_ref": f"tool:{index}" if installed else f"tenant_mcp_repository:{index}",
            "name": f"named_tool_{index}", "names": [f"named_tool_{index}"],
            "description": "search", "descriptions": ["search"], "labels": [], "interfaces": [],
            "installed": installed, "quality": 1., "resource_type": "tool" if installed else "mcp_server",
            "source": "LOCAL_TOOL" if installed else "TENANT_MCP_REPOSITORY"}


@pytest.mark.parametrize("score,count", [(0.4999, 0), (0.5, 3), (0.9, 3)])
def test_each_pool_has_strict_top3_without_name_or_tie_bypass(mocker, score, count):
    mocker.patch.object(flow.legacy, "_score_resource_requirement", return_value=score)
    installed = [resource(i) for i in range(8)]
    installable = [resource(i, False) for i in range(8)]
    result = flow._text_candidates({"r": {"query": "named_tool_7", "search_queries": {
        "zh": "检索", "en": "search"}}}, installed, installable)["r"]
    for label, prefix in (("installed", "tool:"), ("installable", "tenant_mcp_repository:")):
        assert [item["candidate_ref"] for item in result[label]] == [f"{prefix}{i}" for i in range(count)]


@pytest.mark.parametrize("value,expected", [(None, .5), ("0.7", .7), ("1", 1),
                                         ("0", None), ("-1", None), ("1.01", None),
                                         ("nan", None), ("inf", None), ("bad", None)])
def test_embedding_threshold_configuration(mocker, value, expected):
    name = "NL2AGENT_EMBEDDING_MIN_SIMILARITY"
    if value is None:
        mocker.patch.dict(os.environ, {}, clear=True)
    else:
        mocker.patch.dict(os.environ, {name: value})
    tree = ast.parse(Path(environment.__file__).read_text(encoding="utf-8"))
    nodes = [node for node in tree.body if isinstance(node, ast.Assign)
             and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)]
    nodes += [node for node in tree.body if isinstance(node, ast.If)
              and name in ast.unparse(node.test)]
    assert nodes
    code = compile(ast.Module(body=nodes, type_ignores=[]), environment.__file__, "exec")
    namespace = {"os": os, "parse_positive_float": parse_positive_float}
    if expected is None:
        with pytest.raises(ValueError):
            exec(code, namespace)
    else:
        exec(code, namespace)
        assert namespace[name] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", [False, True])
async def test_hybrid_unique_verification_then_uncovered_without_recall(mocker, empty):
    from services.nl2agent_state_service import ResourceScope

    scope = ResourceScope("tenant", "user", 1, "2", "run")
    saved = {}
    async def update(_scope, change):
        value = change(dict(saved) if saved else None)
        saved.clear()
        saved.update(value)
        return dict(saved)
    async def inline(_name, fn, *args, **kwargs):
        kwargs.pop("owner", None)
        return fn(*args, **kwargs)
    mocker.patch.object(flow, "update_resource_state", side_effect=update)
    mocker.patch.object(flow, "read_resource_state", side_effect=lambda _: dict(saved))
    mocker.patch.object(flow, "run_blocking", side_effect=inline)
    mocker.patch.object(flow, "_progress", new=AsyncMock())
    catalog = [resource(i) for i in range(8)]
    mocker.patch.object(flow.legacy, "_load_installed_resource_catalog", new=AsyncMock(return_value=catalog))
    mocker.patch.object(flow.legacy, "_load_internal_uninstalled_resource_catalog", new=AsyncMock(return_value=[]))
    mocker.patch.object(flow.legacy, "_score_resource_requirement", return_value=.1 if empty else .8)
    text = mocker.patch.object(flow, "_text_candidates", wraps=flow._text_candidates)
    mocker.patch.object(flow.semantic, "resolve_model", new=AsyncMock(return_value=object()))
    vector_rows = [] if empty else [(.9, resource(0)), (.8, resource(3)), (.7, resource(4))]
    vector = mocker.patch.object(flow.semantic, "retrieve", new=AsyncMock(return_value={
        key: {"installed": vector_rows, "installable": []} for key in ("r1", "r2")}))
    pair = {"zh": "检索", "en": "search"}
    result = await flow.discover(scope, [RequirementDiscoveryInput(query=query, search_queries=pair)
                                       for query in ("检索公开网页", "检索实时网页")], "generate")
    assert vector.call_args.args[2] == {"r1": pair, "r2": pair}
    for key in ("r1", "r2"):
        refs = [item["candidate_ref"] for item in saved["requirements"][key]["installed"]]
        assert refs == ([] if empty else [f"tool:{i}" for i in range(5)])
    checks = [VerificationCheck(requirement_id=key, accepted=[], assessments=[
        {"candidate_ref": item["candidate_ref"], "satisfies": False, "reason": "Missing required capability"}
        for item in flow._candidates_in_batch(saved["requirements"][key])]) for key in ("r1", "r2")]
    result = await flow.verify(scope, result["verification_batch_id"], checks)
    assert result["verification_batch_id"] is None
    assert all(row["coverage_status"] == "uncovered" for row in result["requirements"])
    await flow.discover(scope, None, "generate")
    assert text.call_count == vector.await_count == 1
    if not empty:
        assert all(len(row["candidate_assessments"]) == 5 for row in saved["requirements"].values())
