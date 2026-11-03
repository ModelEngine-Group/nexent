// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { agentCreationGuideKey } from "@/lib/agentCreationGuide";
import { useRef } from "react";
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { AgentCreationGuide } from "@/app/agents/[agentId]/components/agent-creation-guide";

vi.mock("@/components/common/StandardTour", () => ({
  StandardTour: ({ open }: { open: boolean }) =>
    open ? <div role="dialog">Creation guide</div> : null,
}));

function Workspace({
  preferenceKey,
  complete = true,
}: {
  preferenceKey: string;
  complete?: boolean;
}) {
  const workspaceRef = useRef<HTMLDivElement>(null);
  return (
    <div ref={workspaceRef}>
      <AgentCreationGuide
        preferenceKey={preferenceKey}
        workspaceRef={workspaceRef}
      />
      <div data-agent-guide="assistant" />
      <div data-agent-guide="core" />
      <div data-agent-guide="resources" />
      {complete && <div data-agent-guide="workflow" />}
    </div>
  );
}

it("opens as soon as targets mount without waiting for an animation frame", () => {
  vi.spyOn(window, "requestAnimationFrame").mockReturnValue(1);
  render(
    <Workspace
      preferenceKey={agentCreationGuideKey("timing", "guide-immediate")}
    />
  );
  expect(screen.getByRole("dialog")).toHaveTextContent("Creation guide");
});

it("does not reopen a completed guide", () => {
  localStorage.setItem(agentCreationGuideKey("timing", "guide-completed"), "1");
  render(
    <Workspace
      preferenceKey={agentCreationGuideKey("timing", "guide-completed")}
    />
  );
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  localStorage.removeItem(agentCreationGuideKey("timing", "guide-completed"));
});

it("does not open against missing targets", () => {
  render(
    <Workspace
      preferenceKey={agentCreationGuideKey("timing", "guide-missing-target")}
      complete={false}
    />
  );
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
