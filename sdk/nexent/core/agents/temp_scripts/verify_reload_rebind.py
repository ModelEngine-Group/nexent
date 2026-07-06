"""Verify the reload-tool store rebind on conversation-CM mount (run_agent.py).

Reproduces the bug (tool bound to a per-build empty store, session store has
the handle -> reload misses), then proves _rebind_reload_tool_store points the
tool at the conversation CM's session store so reload hits. Also covers the
container/no-tool/no-store guards.
"""
import json
import sys, os
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nexent.core.agents.run_agent import _rebind_reload_tool_store
from nexent.core.tools.reload_original_context_tool import ReloadOriginalContextTool
from nexent.core.agents.agent_context.offload_store import OffloadStore


def forward_json(tool, handle):
    return json.loads(tool.forward(handle))


def main():
    # Session store has the archived content; per-build store is empty.
    session_store = OffloadStore()
    handle = session_store.store("THE OFFLOADED CONTENT", description="server health report")
    per_build_store = OffloadStore()  # what create_single_agent bound the tool to

    tool = ReloadOriginalContextTool(offload_store=per_build_store)

    # Before rebind: tool reads the empty per-build store -> miss.
    res_before = forward_json(tool, handle)
    assert "error" in res_before and "No offloaded content" in res_before["error"], \
        "before rebind the tool must miss (reads the empty per-build store)"
    print("[before] miss as expected:", res_before["error"][:60], "...")

    # Mount: agent.tools dict + conversation CM carrying the session store.
    agent = SimpleNamespace(tools={"reload_original_context_messages": tool})
    cm = SimpleNamespace(offload_store=session_store)
    _rebind_reload_tool_store(agent, cm)

    # After rebind: tool reads the session store -> hit, full content returned.
    res_after = forward_json(tool, handle)
    assert res_after.get("content") == "THE OFFLOADED CONTENT", \
        "after rebind the tool must read the session store and return the content"
    print("[after]  hit, content =", repr(res_after["content"])[:40], "...")

    # --- Guards (must be no-ops, never raise) ---

    # list-form tools container also supported
    tool2 = ReloadOriginalContextTool(offload_store=OffloadStore())
    _rebind_reload_tool_store(SimpleNamespace(tools=[tool2]), cm)
    assert tool2._offload_store is session_store, "list-form tools must be rebound too"

    # no reload tool present -> no-op, no error
    _rebind_reload_tool_store(
        SimpleNamespace(tools={"other_tool": SimpleNamespace(name="other")}), cm
    )

    # CM without offload_store -> no-op
    other_tool = ReloadOriginalContextTool(offload_store=per_build_store)
    _rebind_reload_tool_store(
        SimpleNamespace(tools={"reload_original_context_messages": other_tool}),
        SimpleNamespace(),  # no offload_store attr
    )
    assert other_tool._offload_store is per_build_store, "missing store must not rebind"

    # missing/empty agent.tools -> no-op, no error
    _rebind_reload_tool_store(SimpleNamespace(), cm)
    _rebind_reload_tool_store(SimpleNamespace(tools=None), cm)

    print("\nRESULT: PASS (rebind makes reload follow the session-level store; guards safe)")


if __name__ == "__main__":
    main()
