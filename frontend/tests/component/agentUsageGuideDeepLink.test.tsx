import React, { useRef, useState } from "react";
import { screen } from "@testing-library/dom";
import { render } from "@testing-library/react";
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
  const [menuOpen, setMenuOpen] = useState(false);
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
      setMenuOpen(true);
      onReplace(clearAgentUsageGuidePath("en", 41));
    }
  };
  return (
    <div>
      <span>{target.state}</span>
      <button onClick={load}>load target</button>
      <div aria-current="true">Agent 41 card</div>
      {menuOpen ? (
        <div role="menu">
          <button onClick={() => setMenuOpen(false)}>Usage and sharing</button>
        </div>
      ) : null}
    </div>
  );
}

describe("usage guide deep-link component state", () => {
  it("UT-FE-AGUG-023 waits for the URL target then opens its menu while retaining the card", async () => {
    const user = userEvent.setup();
    render(<DeepLinkHarness onReplace={vi.fn()} />);
    expect(screen.getByText("loading")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "load target" }));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText("Agent 41 card")).toHaveAttribute(
      "aria-current",
      "true"
    );
    await user.click(screen.getByRole("button", { name: "load target" }));
    expect(screen.getAllByRole("menu")).toHaveLength(1);
  });

  it("UT-FE-AGUG-024 clears onboarding while retaining target location after the menu closes", async () => {
    const user = userEvent.setup();
    const replace = vi.fn();
    render(<DeepLinkHarness onReplace={replace} />);
    await user.click(screen.getByRole("button", { name: "load target" }));
    expect(replace).toHaveBeenCalledOnce();
    expect(replace).toHaveBeenCalledWith(
      "/en/agent-space?tab=mine&agent_id=41"
    );
    await user.click(screen.getByRole("button", { name: "Usage and sharing" }));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(screen.getByText("Agent 41 card")).toHaveAttribute(
      "aria-current",
      "true"
    );
  });
});
