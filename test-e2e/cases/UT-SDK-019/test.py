"""D1 contracts for tags, HITL, model catalog, logging and sandbox cleanup."""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError


STAGE = pytest.mark.stage("D1")










@STAGE
@pytest.mark.case_id("UT-SDK-019")
def test_sandbox_tool_bridge_uses_managed_thread_and_closes_it() -> None:
    import nexent.core.agents.sandbox as sandbox

    source = Path(sandbox.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    bridge = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "_ToolBridge")
    methods = {node.name: node for node in bridge.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert {"__init__", "register", "proxy_code", "close"}.issubset(methods)
    startup_calls = {
        node.func.attr
        for node in ast.walk(methods["__init__"])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    close_calls = {
        node.func.attr
        for node in ast.walk(methods["close"])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert {"register_service", "start_service"}.issubset(startup_calls), (
        "bridge server must be registered and started through the managed ThreadManager"
    )
    assert "cancel" in close_calls, "bridge close must cancel and join its managed execution"
