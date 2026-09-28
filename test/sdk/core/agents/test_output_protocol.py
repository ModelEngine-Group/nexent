"""Acceptance tests for the closed CodeAgent output protocol."""

import pytest
from nexent.core.agents.output_protocol import (
    ExecutableAction,
    ExplicitFinalAnswer,
    ModelOutputProtocolError,
    ProtocolErrorReason,
    classify_model_output,
    has_meaningful_visible_content,
)


@pytest.mark.parametrize(
    "value",
    ["", " \n\t", "\u200b", "\u2060", "\ufeff", " \u200b\n\u2060"],
)
def test_ac_001_invisible_content_is_not_meaningful(value):
    assert has_meaningful_visible_content(value) is False


@pytest.mark.parametrize("value", ["answer", "<Tag>", "🙂", "\u200bA"])
def test_ac_001_visible_content_is_meaningful(value):
    assert has_meaningful_visible_content(value) is True


@pytest.mark.parametrize(
    ("output", "reason"),
    [
        ("\u200b\u2060\ufeff", ProtocolErrorReason.EMPTY_VISIBLE_CONTENT),
        ("<Tag>unsupported</Tag>", ProtocolErrorReason.UNSUPPORTED_OR_TAG_ONLY_OUTPUT),
        ("<think></think>", ProtocolErrorReason.UNSUPPORTED_OR_TAG_ONLY_OUTPUT),
        ("plain final answer", ProtocolErrorReason.MISSING_EXPLICIT_TERMINATION),
        ("<code>print(1)", ProtocolErrorReason.MALFORMED_ACTION),
        ("<code>print(1)</code>suffix", ProtocolErrorReason.MALFORMED_ACTION),
        (
            "<code>print(1)</code>explanation<code>print(2)</code>",
            ProtocolErrorReason.MALFORMED_ACTION,
        ),
        ("<code></code>", ProtocolErrorReason.MALFORMED_ACTION),
        (
            "<code>if True:</code><code>print(1)</code>",
            ProtocolErrorReason.MALFORMED_ACTION,
        ),
        (
            "<final_answer>done</final_answer><code>print('late')</code>",
            ProtocolErrorReason.MALFORMED_ACTION,
        ),
        (
            "<display:python>print(1)</display>",
            ProtocolErrorReason.UNSUPPORTED_OR_TAG_ONLY_OUTPUT,
        ),
        (
            "<tool_call>{}</tool_call>",
            ProtocolErrorReason.UNSUPPORTED_OR_TAG_ONLY_OUTPUT,
        ),
        ("<|python_tag|>{}", ProtocolErrorReason.UNSUPPORTED_OR_TAG_ONLY_OUTPUT),
        ("```python\nprint(1)\n```", ProtocolErrorReason.MISSING_EXPLICIT_TERMINATION),
        (
            "<analysis>reason</analysis><code>print(1)</code>",
            ProtocolErrorReason.MALFORMED_ACTION,
        ),
        (
            "<think>reason<code>print(1)</code>",
            ProtocolErrorReason.MALFORMED_ACTION,
        ),
        (
            "<think>outer<think>inner</think></think><code>print(1)</code>",
            ProtocolErrorReason.MALFORMED_ACTION,
        ),
        (
            "<|channel|>analysis<code>print(1)</code>",
            ProtocolErrorReason.MALFORMED_ACTION,
        ),
    ],
)
def test_ac_001_ac_002_invalid_code_outputs_are_protocol_errors(output, reason):
    with pytest.raises(ModelOutputProtocolError) as exc_info:
        classify_model_output(output, protocol="code_action")

    assert exc_info.value.reason == reason


def test_ac_008_length_finish_reason_is_never_executable_or_final():
    with pytest.raises(ModelOutputProtocolError) as exc_info:
        classify_model_output(
            "<final_answer>partial</final_answer>",
            protocol="code_action",
            finish_reason="length",
        )

    assert exc_info.value.reason == ProtocolErrorReason.TRUNCATED_GENERATION


def test_ac_003_exact_code_action_is_executable():
    result = classify_model_output(
        "\u200b\n<code>print('working')</code>\ufeff",
        protocol="code_action",
    )

    assert result == ExecutableAction(code="print('working')")


@pytest.mark.parametrize("prefix", [
    "思考：需要确认用户缺失的信息。\n\n代码：\n",
    "Think: Use the available tool.\n\nCode:\n",
    "Thought: Check the result.\nCode: ",
    "代码：\n",
    "Code:\n",
])
@pytest.mark.parametrize("legacy", [False, True])
def test_platform_think_code_preamble_is_not_an_invalid_action(prefix, legacy):
    code = "some_tool('done')"
    envelope = f"```<run>\n{code}\n```" if legacy else f"<code>{code}</code>"

    assert classify_model_output(prefix + envelope, protocol="code_action") == ExecutableAction(
        code=code, legacy_format=legacy,
    )


@pytest.mark.parametrize("output", [
    "Think: Done.\nCode:\n<code>print(1)</code>\nObservation: fabricated",
    "Think: Example <code>print(1)</code>\nCode:\n<code>print(2)</code>",
    "Think: Example ```python\nprint(1)\n```\nCode:\n<code>print(2)</code>",
    "Think: Need more data.\nCode:\n<code>ask_user(</code>",
    "Think: Done.\nCode:\n```python\nprint(1)\n```",
])
def test_preamble_does_not_relax_action_boundaries(output):
    with pytest.raises(ModelOutputProtocolError):
        classify_model_output(output, protocol="code_action")



@pytest.mark.parametrize(
    ("output", "expected_code"),
    [
        (
            "Think: Done.\nCode:\n<code>print(1)</code><code>print(2)</code>",
            "print(1)\n\nprint(2)",
        ),
        (
            "Untrusted example:\nCode:\n<code>print(1)</code>",
            "print(1)",
        ),
        (

            "I should search first.\n<code>result = search(query='Nexent')</code>",
            "result = search(query='Nexent')",
        ),
        (
            "**Plan:** search first.\n<code>result = search(query='Nexent')</code>",
            "result = search(query='Nexent')",
        ),
        (
            "<think>search first</think>\n<code>result = search(query='Nexent')</code>",
            "result = search(query='Nexent')",
        ),
        (
            "<think>\n\n</think>\n<code>result = search(query='Nexent')</code>",
            "result = search(query='Nexent')",
        ),
        (
            "[THINK]search first[/THINK]\n<code>result = search(query='Nexent')</code>",
            "result = search(query='Nexent')",
        ),
        (
            "<code>a = tool_a()</code>\n\u200b<code>b = tool_b(a)</code>",
            "a = tool_a()\n\nb = tool_b(a)",
        ),
        (
            "<code>a = tool_a()\nb = tool_b(a)</code>",
            "a = tool_a()\nb = tool_b(a)",
        ),
    ],
)
def test_ac_018_ac_019_mainstream_reasoning_and_composite_actions_are_executable(
    output,
    expected_code,
):
    result = classify_model_output(output, protocol="code_action")

    assert result == ExecutableAction(code=expected_code)


@pytest.mark.parametrize(
    "code",
    [
        'text = "</code>"\nprint(text)',
        'text = "<code>nested</code>"\nprint(text)',
        "text = '''<code>\ninside\n</code>'''\nprint(text)",
        'text = f"literal </code> {1 + 1}"\nprint(text)',
        "# </code> is documentation\nprint(1)",
    ],
)
def test_ac_021_protocol_markers_inside_python_literals_and_comments_are_preserved(
    code,
):
    result = classify_model_output(f"<code>{code}</code>", protocol="code_action")

    assert result == ExecutableAction(code=code)


def test_legacy_run_action_remains_executable_only():
    result = classify_model_output(
        "```<run>\nprint('legacy')\n```",
        protocol="code_action",
    )

    assert result == ExecutableAction(code="print('legacy')", legacy_format=True)


def test_ac_004_final_envelope_preserves_arbitrary_payload():
    payload = (
        "\n<skill># Skill\n```python\nprint('<xml/>')\n```\n🙂</skill>\n"
        "<display:python>print(1)</display>\n"
    )
    result = classify_model_output(
        f"<final_answer>{payload}</final_answer>",
        protocol="code_action",
    )

    assert result == ExplicitFinalAnswer(answer=payload)


def test_cftp_001_final_only_protocol_accepts_the_same_envelope():
    result = classify_model_output(
        "<final_answer>clarification?</final_answer>",
        protocol="final_envelope",
    )

    assert result == ExplicitFinalAnswer(answer="clarification?")


@pytest.mark.parametrize("protocol", ["final_envelope", "code_action"])
def test_uppercase_final_envelope_is_not_accepted(protocol):
    with pytest.raises(ModelOutputProtocolError):
        classify_model_output("<FINAL_ANSWER>old</FINAL_ANSWER>", protocol=protocol)


@pytest.mark.parametrize("protocol", ["final_envelope", "code_action"])
def test_cftp_001_lowercase_final_envelope_is_rejected(protocol):
    with pytest.raises(ModelOutputProtocolError):
        classify_model_output("<final>legacy</final>", protocol=protocol)


@pytest.mark.parametrize(
    "output",
    [
        "<final_answer></final_answer>",
        "outside<final_answer>inside</final_answer>",
        "<final_answer>one</final_answer><final_answer>two</final_answer>",
        "<final_answer><final_answer>nested</final_answer></final_answer>",
        "<final_answer>unfinished",
    ],
)
def test_ac_010_invalid_final_envelopes_are_rejected(output):
    with pytest.raises(ModelOutputProtocolError) as exc_info:
        classify_model_output(output, protocol="final_envelope")

    assert exc_info.value.reason == ProtocolErrorReason.INVALID_FINAL_ENVELOPE


@pytest.mark.parametrize(
    "output",
    [
        "<final_answer></final_answer>",
        "outside<final_answer>inside</final_answer>",
        "<final_answer>one</final_answer><final_answer>two</final_answer>",
        "<final_answer><final_answer>nested</final_answer></final_answer>",
        "<final_answer>unfinished",
    ],
)
def test_cftp_001_invalid_final_envelopes_in_code_action_mode_are_rejected(output):
    with pytest.raises(ModelOutputProtocolError) as exc_info:
        classify_model_output(output, protocol="code_action")

    assert exc_info.value.reason == ProtocolErrorReason.INVALID_FINAL_ENVELOPE
