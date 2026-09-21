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
        (
            "<code>print(1)</code><code>print(2)</code>",
            ProtocolErrorReason.MALFORMED_ACTION,
        ),
        ("prefix<code>print(1)</code>", ProtocolErrorReason.MALFORMED_ACTION),
    ],
)
def test_ac_001_ac_002_invalid_code_outputs_are_protocol_errors(output, reason):
    with pytest.raises(ModelOutputProtocolError) as exc_info:
        classify_model_output(output, protocol="code_action")

    assert exc_info.value.reason == reason


def test_ac_008_length_finish_reason_is_never_executable_or_final():
    with pytest.raises(ModelOutputProtocolError) as exc_info:
        classify_model_output(
            "<code>final_answer('partial')</code>",
            protocol="code_action",
            finish_reason="length",
        )

    assert exc_info.value.reason == ProtocolErrorReason.TRUNCATED_GENERATION


def test_ac_003_exact_code_action_is_executable():
    result = classify_model_output(
        "\u200b\n<code>final_answer('done')</code>\ufeff",
        protocol="code_action",
    )

    assert result == ExecutableAction(code="final_answer('done')")


def test_ac_004_code_action_preserves_protocol_like_text_inside_final_answer():
    code = '''final_answer("""Markdown: ```python\nprint(1)\n```\nHTML: <code>x</code>\nXML: <node>值🙂</node>""")'''

    result = classify_model_output(
        f"<code>{code}</code>",
        protocol="code_action",
    )

    assert result == ExecutableAction(code=code)


def test_legacy_run_action_remains_executable_only():
    result = classify_model_output(
        "```<RUN>\nprint('legacy')\n```",
        protocol="code_action",
    )

    assert result == ExecutableAction(code="print('legacy')", legacy_format=True)


def test_ac_004_final_envelope_preserves_arbitrary_payload():
    payload = "\n<SKILL># Skill\n```python\nprint('<xml/>')\n```\n🙂</SKILL>\n"
    result = classify_model_output(
        f"<FINAL_ANSWER>{payload}</FINAL_ANSWER>",
        protocol="final_answer_envelope",
    )

    assert result == ExplicitFinalAnswer(answer=payload)


@pytest.mark.parametrize(
    "output",
    [
        "<FINAL_ANSWER></FINAL_ANSWER>",
        "outside<FINAL_ANSWER>inside</FINAL_ANSWER>",
        "<FINAL_ANSWER>one</FINAL_ANSWER><FINAL_ANSWER>two</FINAL_ANSWER>",
        "<FINAL_ANSWER><FINAL_ANSWER>nested</FINAL_ANSWER></FINAL_ANSWER>",
        "<FINAL_ANSWER>unfinished",
    ],
)
def test_ac_010_invalid_final_envelopes_are_rejected(output):
    with pytest.raises(ModelOutputProtocolError) as exc_info:
        classify_model_output(output, protocol="final_answer_envelope")

    assert exc_info.value.reason == ProtocolErrorReason.INVALID_FINAL_ENVELOPE
