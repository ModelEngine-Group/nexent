# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Contracts between NL2Agent generation and the single prompt editor."""

import ast
import re

import pytest

from agents.nl2agent_agent import build_nl2agent_system_prompt


@pytest.mark.parametrize("language", ["zh", "en"])
def test_prompt_examples_save_only_visible_content(language):
    prompt = build_nl2agent_system_prompt(language)
    saves = []
    for source in re.findall(r"<code>\n(.*?)\n</code>", prompt, re.DOTALL):
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg == "fields":
                    assert isinstance(keyword.value, ast.Dict)
                    fields = dict(zip(
                        [ast.literal_eval(key) for key in keyword.value.keys],
                        keyword.value.values,
                    ))
                    if "duty_prompt" in fields:
                        saves.append(fields)
                    elif {"constraint_prompt", "few_shots_prompt"} & fields.keys():
                        pytest.fail("An example still saves a separate hidden prompt")
    assert len(saves) == 2
    for fields in saves:
        assert set(fields) == {"duty_prompt"}
    assert "constraint_prompt" not in prompt
    assert "few_shots_prompt" not in prompt
    assert ('`updated_fields` 是 `["duty_prompt"]`' in prompt
            or 'equal to `["duty_prompt"]`' in prompt)
    assert ('只生成并同时保存 `greeting_message` 和 `example_questions`' in prompt
            or 'save only `greeting_message` and `example_questions` together' in prompt)
    assert ('限制、运行规则、演示或示例均对应单输入框' in prompt
            or 'restrictions, operating rules, demonstrations, or examples to the single complete prompt' in prompt)
    assert ('没有绑定资源时不编造资源规则或调用示例' in prompt
            or 'With no bound resources, omit resource-specific rules and invocation examples' in prompt)
