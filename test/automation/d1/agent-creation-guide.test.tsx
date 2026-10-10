import React, { createRef } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { TourProps } from "antd";
import { AgentCreationGuide } from "../../../frontend/app/[locale]/agents/[agentId]/components/agent-creation-guide";
import {
  agentCreationGuideKey,
  canStartAgentCreationGuide,
  completeAgentCreationGuide,
  hasCompletedAgentCreationGuide,
} from "../../../frontend/lib/agentCreationGuide";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/components/common/StandardTour", () => ({
  StandardTour: (props: TourProps) => {
    if (!props.open) return null;
    const current = props.current ?? 0;
    const step = props.steps![current];
    const target =
      typeof step.target === "function" ? step.target() : step.target;
    const next = (
      <button
        className="ant-btn-primary"
        onClick={() =>
          current === 3
            ? props.onClose?.(current)
            : props.onChange?.(current + 1)
        }
      >
        {step.nextButtonProps?.children}
      </button>
    );
    return (
      <div
        className="agent-creation-guide"
        data-target={target?.dataset.agentGuide}
      >
        <h2>{step.title}</h2>
        <p>{step.description}</p>
        {current > 0 && (
          <button onClick={() => props.onChange?.(current - 1)}>
            {step.prevButtonProps?.children}
          </button>
        )}
        {props.actionsRender
          ? props.actionsRender(next, { current, total: 4 })
          : next}
      </div>
    );
  },
}));

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});
const uniqueKey = () => agentCreationGuideKey("tenant", crypto.randomUUID());
function mountGuide(key: string) {
  const workspace = createRef<HTMLDivElement>();
  const changed = vi.fn();
  const businessAction = vi.fn();
  const view = render(
    <div ref={workspace}>
      <div data-agent-guide="assistant">
        <textarea aria-label="composer" />
      </div>
      {["core", "resources", "workflow"].map((name) => (
        <div key={name} data-agent-guide={name}>
          <button onClick={businessAction}>{name}</button>
        </div>
      ))}
      <AgentCreationGuide
        preferenceKey={key}
        workspaceRef={workspace}
        onOpenChange={changed}
      />
    </div>,
  );
  return { ...view, changed, businessAction };
}

it("AGENT-GUIDE-D1-001 excludes ordinary, loading, stale, read-only and unidentified contexts", () => {
  const ready = {
    creationEntry: true,
    ready: true,
    readOnly: false,
    tenantId: "t",
    userId: "u",
  };
  expect(canStartAgentCreationGuide(ready)).toBe(true);
  for (const excluded of [
    { creationEntry: false },
    { ready: false },
    { readOnly: true },
    { tenantId: null },
    { userId: "" },
  ]) {
    expect(canStartAgentCreationGuide({ ...ready, ...excluded })).toBe(false);
  }
  expect(agentCreationGuideKey("a.b", "c")).not.toBe(
    agentCreationGuideKey("a", "b.c"),
  );
  expect(agentCreationGuideKey("a/b", "c")).not.toBe(
    agentCreationGuideKey("a", "b/c"),
  );
});

it("AGENT-GUIDE-D1-001 navigates four targets, remembers finish and restores composer focus without business actions", async () => {
  const key = uniqueKey();
  const view = mountGuide(key);
  const heading = (name: string) =>
    screen.findByRole("heading", { name: `agent.creationGuide.${name}.title` });
  await heading("assistant");
  expect(document.querySelector(".agent-creation-guide")).toHaveAttribute(
    "data-target",
    "assistant",
  );
  fireEvent.click(screen.getByText("agent.creationGuide.next"));
  await heading("core");
  fireEvent.click(screen.getByText("agent.creationGuide.previous"));
  await heading("assistant");
  for (const name of ["core", "resources", "workflow"]) {
    fireEvent.click(screen.getByText("agent.creationGuide.next"));
    await heading(name);
    expect(document.querySelector(".agent-creation-guide")).toHaveAttribute(
      "data-target",
      name,
    );
  }
  fireEvent.click(screen.getByText("agent.creationGuide.finish"));
  await waitFor(() =>
    expect(screen.getByRole("textbox", { name: "composer" })).toHaveFocus(),
  );
  expect(hasCompletedAgentCreationGuide(key)).toBe(true);
  expect(view.businessAction).not.toHaveBeenCalled();
  view.unmount();
  mountGuide(key);
  await new Promise((resolve) => setTimeout(resolve, 40));
  expect(screen.queryByRole("heading")).not.toBeInTheDocument();
});

it("AGENT-GUIDE-D1-001 skips with denied storage, remembers in-session and isolates identity", async () => {
  const key = uniqueKey();
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("denied");
  });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("denied");
  });
  const view = mountGuide(key);
  fireEvent.click(await screen.findByText("agent.creationGuide.skip"));
  expect(hasCompletedAgentCreationGuide(key)).toBe(true);
  expect(hasCompletedAgentCreationGuide(uniqueKey())).toBe(false);
  expect(view.businessAction).not.toHaveBeenCalled();
  view.unmount();
  mountGuide(key);
  await new Promise((resolve) => setTimeout(resolve, 40));
  expect(screen.queryByRole("heading")).not.toBeInTheDocument();
});

it("AGENT-GUIDE-D1-001 persisted completion and Escape dismissal are scoped explanatory preferences", async () => {
  const stored = uniqueKey();
  window.localStorage.setItem(stored, "1");
  expect(hasCompletedAgentCreationGuide(stored)).toBe(true);
  const key = uniqueKey();
  const view = mountGuide(key);
  await screen.findByRole("heading");
  fireEvent.keyDown(window, { key: "Escape" });
  expect(hasCompletedAgentCreationGuide(key)).toBe(true);
  expect(view.businessAction).not.toHaveBeenCalled();
  completeAgentCreationGuide(stored);
  expect(window.localStorage.getItem(stored)).toBe("1");
});
