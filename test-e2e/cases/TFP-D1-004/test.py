"""TFP-D1-004: preserved fast-path acceptance checks."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from shared.tool_fastpath import make_wrapper
from shared.tool_fastpath_aidp import aidp_runtime as aidp_runtime
from smolagents.default_tools import FinalAnswerTool

from nexent.core.agents.agent_model import ToolConfig
from nexent.core.agents.tool_fastpath import (
    OFFICIAL_FASTPATH_TOOL_CLASSES,
    DeferredToolExecutor,
    is_simple_whitelisted_action,
    official_fastpath_tools,
)
from nexent.core.ext_components.aidp.aidp_search_tool import AidpSearchTool
from nexent.core.tools.ind_aidp_search_tool import IndependentAidpSearchTool
from nexent.core.tools.read_skill_config_tool import ReadSkillConfigTool
from nexent.core.utils.observer import MessageObserver


pytestmark = [pytest.mark.case_id("TFP-D1-004"), pytest.mark.stage("D1")]

def test_tfp_d1_004(monkeypatch):
    """TFP-D1-004: exact official identity and trusted factory source are required."""
    wrapper, ordinary, _, acquisitions, _ = make_wrapper(monkeypatch, execute=False)
    official = wrapper._tools["read_skill_config"]
    from nexent.core.tools.knowledge_base_search_tool import KnowledgeBaseSearchTool
    from nexent.core.tools.read_skill_md_tool import ReadSkillMdTool

    for tool in (
        official, ReadSkillMdTool(),
        KnowledgeBaseSearchTool(index_names=[], observer=MessageObserver()),
    ):
        trusted = ToolConfig(class_name=type(tool).__name__, name=tool.name, source="local")
        assert official_fastpath_tools([trusted], [tool], [trusted.class_name]) == {tool.name: tool}
    config = ToolConfig(class_name="ReadSkillConfigTool", name=official.name, source="builtin")
    assert official_fastpath_tools([config], [official], [config.class_name]) == {official.name: official}
    config.source = "mcp"
    assert official_fastpath_tools([config], [official], [config.class_name]) == {}
    config.source = "builtin"
    custom = SimpleNamespace(name=official.name)
    assert official_fastpath_tools([config], [custom], [config.class_name]) == {}

    class UnknownSubclass(ReadSkillConfigTool):
        pass

    subclass = UnknownSubclass(config_overrides={})
    assert official_fastpath_tools([config], [subclass], [config.class_name]) == {}
    with pytest.raises(ValueError, match="Unknown official"):
        official_fastpath_tools([config], [official], ["UnregisteredTool"])
    assert official_fastpath_tools([config], [official], []) == {}
    assert not is_simple_whitelisted_action("alias = read_skill_config\nalias()", {official.name}, {})
    assert not is_simple_whitelisted_action("print = 1", {official.name}, {})
    assert not is_simple_whitelisted_action("_print_outputs = 1", {official.name}, {})
    wrapper.send_tools({official.name: custom, "final_answer": FinalAnswerTool()})
    wrapper('read_skill_config(skill_name="demo")')
    assert wrapper.remote is not None
    assert acquisitions == [True]
    assert ordinary.calls == ['read_skill_config(skill_name="demo")']
    wrapper, ordinary, _, acquisitions, _ = make_wrapper(monkeypatch, execute=False)
    wrapper.send_tools({"final_answer": lambda answer: pytest.fail("Forged final answer ran locally")})
    wrapper('final_answer("demo")')
    assert acquisitions == [True]
    assert ordinary.calls == ['final_answer("demo")']

@pytest.mark.parametrize("identity", ["mcp", "custom", "subclass", "independent", "omitted"])
def test_tfp_d1_004_aidp(aidp_runtime, identity):
    """TFP-D1-004: same-name AIDP variants and explicit omission cannot qualify."""
    config = aidp_runtime.config.model_copy()
    tool = aidp_runtime.runtime.create_tool(config)
    allowed_classes = OFFICIAL_FASTPATH_TOOL_CLASSES
    if identity == "mcp":
        config.source = "mcp"
    elif identity == "custom":
        tool = SimpleNamespace(name="aidp_search")
    elif identity == "subclass":
        class DerivedAidp(AidpSearchTool):
            pass

        tool = object.__new__(DerivedAidp)
    elif identity == "independent":
        tool = object.__new__(IndependentAidpSearchTool)
        tool.name = "aidp_search"
    else:
        allowed_classes = [name for name in allowed_classes if name != "AidpSearchTool"]
    allowed = official_fastpath_tools([config], [tool], allowed_classes)
    assert allowed == {}
    acquisitions = []

    def acquire():
        acquisitions.append(True)
        return aidp_runtime.ordinary

    wrapper = DeferredToolExecutor(acquire, aidp_runtime.releases.append, allowed)
    wrapper.send_tools({"aidp_search": tool, "final_answer": FinalAnswerTool()})
    source = 'aidp_search(query="rules")'
    wrapper(source)
    assert acquisitions == [True]
    assert aidp_runtime.ordinary.calls == [source]
    assert aidp_runtime.requests == []
    wrapper.cleanup()
