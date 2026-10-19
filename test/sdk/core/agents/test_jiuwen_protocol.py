"""Unit contracts for the controlled text execution grammar."""

import pytest
from nexent.core.agents.core_adapters.jiuwen_protocol import (
    JiuwenProtocolError,
    parse_execution_blocks,
)


@pytest.mark.parametrize("text,code", [
    ("<code>add(a=2,b=3)</code>", "add(a=2,b=3)"),
    ("Prose\n<code>\nx=2\n</code>\n<code>print(x)</code>", "x=2\n\nprint(x)"),
    ("```<run>\nprint(2)\n```", "print(2)"),
])
def test_registered_complete_blocks(text, code):
    assert parse_execution_blocks(text).code == code


@pytest.mark.parametrize("text", ["Answer", "```python\nadd(2,3)\n```", "<example>add(2,3)</example>"])
def test_reference_text_is_not_executable(text):
    assert parse_execution_blocks(text) is None


@pytest.mark.parametrize("text", [
    "<code>add(2,3)", "</code>", "<code>print(1)</code><code>print(2)",
    "<code><code>print(1)</code></code>", "```<run>print(1)",
    "<code>print(1)</code>```<run>print(2)```", "<code> </code>",
    "<code>print(</code>", "<code>print(1)</code><final_answer>done</final_answer>",
    "```python\n<code>print(1)</code>\n```",
])
def test_incomplete_ambiguous_or_invalid_blocks_fail_closed(text):
    with pytest.raises(JiuwenProtocolError, match="JIUWEN_") as error:
        parse_execution_blocks(text)
    assert text not in str(error.value)



@pytest.mark.parametrize("text,category", [
    ("<code><code>print(1)</code></code>", "JIUWEN_NESTED_EXECUTION_BLOCK"),
    ("<code><code>print(1)</code>", "JIUWEN_NESTED_EXECUTION_BLOCK"),
    ("<code>print(1)", "JIUWEN_INCOMPLETE_EXECUTION_BLOCK"),
    ("```python\n<code><code>print(1)</code></code>\n```", "JIUWEN_AMBIGUOUS_EXECUTION_BLOCK"),
])
def test_invalid_code_classification_preserves_execution_boundary(text, category):
    with pytest.raises(JiuwenProtocolError, match=category):
        parse_execution_blocks(text)
