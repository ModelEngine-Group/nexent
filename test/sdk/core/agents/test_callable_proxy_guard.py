# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Malformed registry names fail before any remote Python submission."""

import pytest

from nexent.core.agents import sandbox


@pytest.mark.parametrize("name", ["agent-one", "class", "_nexent_json", "x = injected()"])
def test_proxy_guard_rejects_invalid_names_before_bootstrap(name):
    bridge = sandbox._ToolBridge.__new__(sandbox._ToolBridge)
    bridge._tools = {"existing": object()}
    with pytest.raises(ValueError, match="callable name"):
        bridge.register({name: object()})
    assert list(bridge._tools) == ["existing"]
    with pytest.raises(ValueError, match="callable name"):
        bridge.proxy_code({name: object()})


def test_external_wrapper_keeps_original_display_name():
    from nexent.core.agents.a2a_agent_proxy import A2AAgentInfo, ExternalA2AAgentWrapper

    wrapper = ExternalA2AAgentWrapper(A2AAgentInfo(agent_id="7", name="agent-one", url="https://unused.invalid"))
    assert wrapper.name == "a2a_agent_7"
    assert wrapper.display_name == wrapper.agent_info.name == "agent-one"
    assert wrapper._proxy is None
