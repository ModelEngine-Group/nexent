import React, { useRef, useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  clearAgentUsageGuidePath,
  getAgentUsageGuideOpenAction,
  resolveAgentUsageGuideTarget,
} from "@/lib/agentUsageGuide";

function DeepLinkHarness({ onReplace }: { onReplace: (path: string) => void }) {
  const consumed = useRef<number | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [open, setOpen] = useState(false);
  const target = resolveAgentUsageGuideTarget({
    agentId: 41,
    agents: loaded ? [{ agent_id: 41 }] : [],
    fallbackAgent: null,
    isListLoading: !loaded,
    isFallbackLoading: false,
    getAgentId: (agent) => agent.agent_id,
  });
  const load = () => {
    setLoaded(true);
    const nextTarget = resolveAgentUsageGuideTarget({
      agentId: 41,
      agents: [{ agent_id: 41 }],
      fallbackAgent: null,
      isListLoading: false,
      isFallbackLoading: false,
      getAgentId: (agent) => agent.agent_id,
    });
    const action = getAgentUsageGuideOpenAction({
      agentId: 41,
      consumedAgentId: consumed.current,
      target: nextTarget,
    });
    if (action.action === "open") {
      consumed.current = 41;
      setOpen(true);
    }
  };
  return (
    <div>
      <span>{target.state}</span>
      <button onClick={load}>load target</button>
      {open ? (
        <div role="dialog">
          Agent 41 guide
          <button
            onClick={() => {
              setOpen(false);
              onReplace(clearAgentUsageGuidePath("en", 41));
            }}
          >
            close
          </button>
        </div>
      ) : null}
    </div>
  );
}

describe("usage guide deep-link component state", () => {
  it("UT-FE-AGUG-023 waits for the URL target then opens and highlights it once", async () => {
    const user = userEvent.setup();
    render(<DeepLinkHarness onReplace={vi.fn()} />);
    expect(screen.getByText("loading")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "load target" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Agent 41 guide");
    await user.click(screen.getByRole("button", { name: "load target" }));
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
  });

  it("UT-FE-AGUG-024 closes with replace semantics while preserving tab and agent_id", async () => {
    const user = userEvent.setup();
    const replace = vi.fn();
    render(<DeepLinkHarness onReplace={replace} />);
    await user.click(screen.getByRole("button", { name: "load target" }));
    await user.click(screen.getByRole("button", { name: "close" }));
    expect(replace).toHaveBeenCalledOnce();
    expect(replace).toHaveBeenCalledWith(
      "/en/agent-space?tab=mine&agent_id=41"
    );
  });
});
