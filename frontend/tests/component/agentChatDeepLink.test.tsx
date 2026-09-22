import React, { useEffect, useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { resolveAgentDeepLinkAction } from "@/lib/agentUsageGuide";

function DeepLinkChatHarness() {
  const [loaded, setLoaded] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const consumed = React.useRef(false);

  useEffect(() => {
    const action = resolveAgentDeepLinkAction({
      agentId: 41,
      agents: loaded ? [{ id: 41 }, { id: 42 }] : [],
      consumed: consumed.current,
      isLoading: !loaded,
      getAgentId: (agent) => agent.id,
    });
    if (action.action === "wait") return;
    consumed.current = true;
    if (action.action === "select") {
      setSelectedId(action.agent.id);
    }
  }, [loaded]);

  return (
    <div>
      <button onClick={() => setLoaded(true)}>load agents</button>
      <button onClick={() => setSelectedId(null)}>back to list</button>
      {selectedId ? <div>Agent {selectedId} chat</div> : <div>Agent list</div>}
    </div>
  );
}

describe("Agent deep link chat state", () => {
  it("selects the target Agent once and allows returning to the list", async () => {
    const user = userEvent.setup();
    render(<DeepLinkChatHarness />);
    expect(screen.getByText("Agent list")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "load agents" }));
    expect(screen.getByText("Agent 41 chat")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "back to list" }));
    expect(screen.getByText("Agent list")).toBeInTheDocument();
  });

  it("dismisses a missing target without selecting another Agent", async () => {
    expect(
      resolveAgentDeepLinkAction({
        agentId: 41,
        agents: [{ id: 42 }],
        consumed: false,
        isLoading: false,
        getAgentId: (agent) => agent.id,
      })
    ).toEqual({ action: "dismiss" });
  });
});
