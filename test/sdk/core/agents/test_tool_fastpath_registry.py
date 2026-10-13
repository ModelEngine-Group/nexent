"""Official class identity and trusted sources determine host tool eligibility."""

from types import SimpleNamespace

import pytest

from nexent.core.agents.tool_fastpath import OFFICIAL_FASTPATH_TOOL_CLASSES, official_fastpath_tools
from nexent.core.ext_components.aidp.aidp_search_tool import AidpSearchTool
from nexent.core.tools.knowledge_base_search_tool import KnowledgeBaseSearchTool
from nexent.core.tools.read_skill_config_tool import ReadSkillConfigTool
from nexent.core.tools.read_skill_md_tool import ReadSkillMdTool


OFFICIAL_CLASSES = (KnowledgeBaseSearchTool, ReadSkillMdTool, ReadSkillConfigTool, AidpSearchTool)


@pytest.mark.parametrize("implementation", OFFICIAL_CLASSES)
@pytest.mark.parametrize("source", ["local", "builtin", "mcp", "langchain", "custom"])
def test_only_exact_official_implementations_from_trusted_sources_are_admitted(implementation, source):
    tool = object.__new__(implementation)
    config = SimpleNamespace(source=source, class_name=implementation.__name__)
    expected = {tool.name: tool} if source in {"local", "builtin"} else {}
    assert official_fastpath_tools([config], [tool], OFFICIAL_FASTPATH_TOOL_CLASSES) == expected


@pytest.mark.parametrize("implementation", OFFICIAL_CLASSES)
def test_same_name_custom_and_subclass_tools_cannot_impersonate_official_tools(implementation):
    class CustomTool:
        name = implementation.name

    class DerivedTool(implementation):
        pass

    config = SimpleNamespace(source="local", class_name=implementation.__name__)
    for forged in (CustomTool(), object.__new__(DerivedTool)):
        assert official_fastpath_tools([config], [forged], OFFICIAL_FASTPATH_TOOL_CLASSES) == {}


def test_explicit_empty_allowlist_and_mismatched_class_identity_are_excluded():
    tool = object.__new__(ReadSkillConfigTool)
    config = SimpleNamespace(source="local", class_name="ReadSkillConfigTool")
    assert official_fastpath_tools([config], [tool], []) == {}
    config.class_name = "ReadSkillMdTool"
    assert official_fastpath_tools([config], [tool], OFFICIAL_FASTPATH_TOOL_CLASSES) == {}


def test_unknown_classes_fail_with_deterministic_diagnostic():
    with pytest.raises(ValueError, match="Unknown official fast-path tool classes: ACustomTool, ZCustomTool"):
        official_fastpath_tools([], [], ["ZCustomTool", "ACustomTool"])


@pytest.mark.parametrize("config_count,tool_count", [(0, 1), (1, 0)])
def test_tool_configuration_length_mismatch_fails_closed(config_count, tool_count):
    config = SimpleNamespace(source="local", class_name="ReadSkillConfigTool")
    with pytest.raises(ValueError, match="zip"):
        official_fastpath_tools([config] * config_count, [object.__new__(ReadSkillConfigTool)] * tool_count, [])
