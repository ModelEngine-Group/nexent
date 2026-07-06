"""Verify the tool_call.arguments compaction (core_agent.py port).

Proves the dedup mechanism at the rendering layer:
  - extract_invoked_tool_signatures emits compact, value-bounded signatures and
    returns [] when no tools are registered.
  - With compact arguments, ActionStep.to_messages() keeps the full code in the
    ASSISTANT message (model_output's <code> block) but the TOOL_CALL message
    carries only the compact signature (no full code).
  - Legacy (full-code arguments) still renders the full code into TOOL_CALL
    (the duplication being removed).
The CM-enabled/legacy gating itself is a trivial if/else in core_agent and is
exercised by the regression suite.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smolagents.memory import ActionStep, ToolCall
from smolagents.monitoring import Timing
from smolagents.utils import truncate_content
from nexent.core.utils.code_analysis import extract_invoked_tool_signatures


def _text(msg) -> str:
    content = getattr(msg, "content", "")
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return content if isinstance(content, str) else str(content)


def render_texts(step):
    msgs = step.to_messages()
    texts = [_text(m) for m in msgs]
    assistant = texts[0] if texts else ""
    tool_call = next((t for t in texts if t.startswith("Calling tools:")), "")
    return assistant, tool_call


def make_step(arguments):
    code = (
        'res = search(query="a-very-long-query-string-that-should-be-bounded", limit=10)\n'
        'print(res)'
    )
    s = ActionStep(step_number=1, timing=Timing(start_time=0.0))
    s.model_output = f"Thoughts: do it\n<code>\n{code}\n</code>"
    s.code_action = code
    s.tool_calls = [ToolCall(name="python_interpreter", arguments=arguments, id="call_1")]
    return s, code


def main():
    code = (
        'res = search(query="a-very-long-query-string-that-should-be-bounded", limit=10)\n'
        'print(res)'
    )
    tools = {"search": object()}

    # 1. helper -> compact call-shape signatures (subset of the full code)
    sigs = extract_invoked_tool_signatures(code, tools)
    print("signatures:", sigs)
    assert sigs and "search(" in sigs[0], "must emit a search(...) signature"
    assert "print(res)" not in sigs[0], "signature is a compact call-shape, not the full code body"
    assert len(sigs[0]) < len(code), "compact signature must be shorter than the full code"

    # 1b. values longer than max_value_len (60) ARE bounded/placeholdered
    long_code = 'search(query="' + ("x" * 100) + '")'
    long_sigs = extract_invoked_tool_signatures(long_code, tools)
    assert ("x" * 100) not in long_sigs[0], "values > 60 chars must be bounded"

    # 2. helper with no registered tools -> []
    assert extract_invoked_tool_signatures(code, {}) == [], "empty tools -> no signatures"

    # 3. compact arguments -> ASSISTANT keeps full code, TOOL_CALL does not.
    # Use "print(res)" as the discriminator: it appears in the full code body
    # but not in the compact call signature. (A literal full-code substring
    # check on TOOL_CALL is unreliable because tc.dict() escapes newlines.)
    compact_args = "\n".join(sigs)
    step_c, code_c = make_step(compact_args)
    asst_c, tc_c = render_texts(step_c)
    assert code_c in asst_c, "ASSISTANT (model_output) must still carry the full code"
    assert "print(res)" not in tc_c, "TOOL_CALL must NOT carry the full code body"
    assert "search(" in tc_c, "TOOL_CALL must carry the compact signature"
    print("[compact]  TOOL_CALL snippet:", tc_c[:80].replace("\n", " "))

    # 4. legacy full-code arguments -> TOOL_CALL carries the full code body
    # (this is the duplication the compaction removes).
    step_f, _ = make_step(code)
    asst_f, tc_f = render_texts(step_f)
    assert "print(res)" in tc_f, "legacy TOOL_CALL carries the full code (the duplication)"
    print("[legacy]   full code body in TOOL_CALL:", "print(res)" in tc_f)

    # 5. fallback path (no tool signatures) -> truncate(code, 100) shortens long code.
    # Used when CM is on but the step calls no registered tool (pure computation).
    long_pure_code = "result = " + ("2 ** 10 + " * 20) + "1\nprint(result)"
    fallback = truncate_content(long_pure_code, max_length=100)
    assert len(fallback) < len(long_pure_code), "fallback truncate must shorten long code"

    print("\nRESULT: PASS (compact dedups TOOL_CALL; full code preserved in model_output)")


if __name__ == "__main__":
    main()
