# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""One business prompt at the SDK and Backend context assembly boundary."""

import inspect

import pytest

from nexent.core.agents.prompt import AgentPromptBundle, AgentPromptComposer
from backend.management.services.agent.context import build_context_inputs


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("role", ["manager", "managed"])
def test_complete_business_prompt_is_one_item_with_platform_rules(language, role):
    bundle = AgentPromptBundle.from_resource(role=role, language=language)
    composer = AgentPromptComposer(bundle)
    prompt = "# Responsibilities\n职责 <&>\n# Constraints\nUse only evidence.\n# Examples\n<code>\n  run()\n</code>"
    items = composer.compose_context_inputs(duty_prompt=prompt, language=language, is_manager=role == "manager")
    configured = next(item for item in items if item.id == "system:duty")
    assert prompt in configured.content["text"]
    assert configured.content["text"].count("Use only evidence.") == 1
    assert configured.metadata["authority"] == "agent"
    assert {item.id for item in items}.isdisjoint({"system:constraint", "system:footer"})
    assert set(bundle.system_sections).isdisjoint({"constraint", "footer"})
    assert "{{duty_prompt}}" in bundle.system_sections["duty"]
    platform = [item for item in items if item.id == "system:code_norms"]
    assert len(platform) == 1
    assert platform[0].metadata["authority"] == "platform"
    assert platform[0].content["text"].count(bundle.system_sections["outline_constraints"]) == 1


@pytest.mark.parametrize("parameter", ["duty", "constraint", "few_shots", "constraint_prompt", "few_shots_prompt"])
def test_removed_prompt_parameters_are_rejected_by_every_context_entry(parameter):
    bundle = AgentPromptBundle.from_resource(role="manager", language="en")
    composer = AgentPromptComposer(bundle)
    for entry, extras in ((composer.compose_context_inputs, {}), (build_context_inputs, {"prompt_bundle": bundle})):
        signature = inspect.signature(entry).parameters
        assert "duty_prompt" in signature
        assert parameter not in signature
        with pytest.raises(TypeError, match=parameter):
            entry(language="en", is_manager=True, **extras, **{parameter: "Legacy content"})


@pytest.mark.parametrize("prompt", [None, ""])
def test_empty_prompt_emits_no_business_item_but_keeps_platform_guidance(prompt):
    bundle = AgentPromptBundle.from_resource(role="managed", language="en")
    items = AgentPromptComposer(bundle).compose_context_inputs(duty_prompt=prompt, language="en", is_manager=False)
    ids = {item.id for item in items}
    assert "system:duty" not in ids
    assert "system:code_norms" in ids
    assert ids.isdisjoint({"system:constraint", "system:footer"})


@pytest.mark.parametrize("section,variable", [("constraint", "constraint"), ("footer", "few_shots")])
def test_custom_templates_cannot_reintroduce_segmented_prompt_sections(section, variable):
    bundle = AgentPromptBundle.from_resource(role="manager", language="en")
    template = {**bundle.template, "system_sections": {**bundle.system_sections, section: "{{" + variable + "}}"}}
    with pytest.raises(ValueError, match="system_sections"):
        AgentPromptBundle.from_mapping(role="manager", language="en", template=template)
