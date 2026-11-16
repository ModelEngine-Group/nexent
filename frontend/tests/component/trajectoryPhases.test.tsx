// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TrajectoryTimeline } from "@/app/observability/components/TrajectoryTimeline";
import { TrajectoryNodeDetail } from "@/app/observability/components/TrajectoryNodeDetail";
import { BodyCache } from "@/lib/trajectory";
import { body, traceNode } from "./trajectoryFixtures";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string }) =>
      key === "trajectory.phases.memory.presearch"
        ? "记忆预检索"
        : (options?.defaultValue ?? key),
  }),
}));

const phase = traceNode({
  id: "phase",
  parent_id: "root",
  kind: "phase",
  name: "memory.presearch",
  usage: null,
  model_call_count: null,
  tool_call_count: null,
  input: body('{"query":"任务"}'),
  output: body('{"memories":["偏好"]}'),
});

describe("trajectory preparation phases", () => {
  it("localizes phase names and searches without losing parent context", () => {
    const select = vi.fn();
    render(
      <App>
        <TrajectoryTimeline
          nodes={[traceNode(), phase]}
          complete
          cache={new BodyCache()}
          onSelect={select}
        />
      </App>
    );
    const item = screen.getByRole("treeitem", { name: /记忆预检索/ });
    expect(item.querySelector(".kind-phase")).toBeTruthy();
    fireEvent.click(item);
    expect(select).toHaveBeenCalledWith(
      expect.objectContaining({ id: "phase", kind: "phase" })
    );
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "记忆" },
    });
    expect(screen.getByRole("treeitem", { name: /记忆预检索/ })).toBeTruthy();
    expect(screen.getByRole("treeitem", { name: /Root Agent/ })).toBeTruthy();
  });

  it("filters lifecycle phases while retaining their agent ancestors", async () => {
    render(
      <App>
        <TrajectoryTimeline
          nodes={[
            traceNode(),
            phase,
            traceNode({
              id: "tool",
              parent_id: "root",
              kind: "tool",
              name: "Search tool",
            }),
          ]}
          complete
          cache={new BodyCache()}
          onSelect={vi.fn()}
        />
      </App>
    );
    fireEvent.mouseDown(
      screen.getByRole("combobox", { name: "trajectory.nodeType" })
    );
    fireEvent.click(await screen.findByText("trajectory.kinds.phase"));
    expect(screen.getByRole("treeitem", { name: /记忆预检索/ })).toBeTruthy();
    expect(screen.getByRole("treeitem", { name: /Root Agent/ })).toBeTruthy();
    expect(screen.queryByRole("treeitem", { name: /Search tool/ })).toBeNull();
  });

  it("shows time and full phase bodies without model or agent metrics", () => {
    const { container } = render(
      <App>
        <TrajectoryNodeDetail
          node={phase}
          conversationId="123"
          cache={new BodyCache()}
          onParent={vi.fn()}
          onLoaded={vi.fn()}
        />
      </App>
    );
    expect(screen.getByRole("heading", { name: "记忆预检索" })).toBeTruthy();
    const summary = within(
      container.querySelector(".trajectory-node-summary") as HTMLElement
    );
    expect(summary.getByText("trajectory.duration")).toBeTruthy();
    for (const metric of [
      "inputTokens",
      "outputTokens",
      "totalTokens",
      "ttft",
      "throughput",
      "modelCalls",
      "toolCalls",
    ]) {
      expect(summary.queryByText(`trajectory.${metric}`)).toBeNull();
    }
    expect(container.querySelector(".trajectory-token-bar")).toBeNull();
    expect(screen.getByText(/偏好/)).toBeTruthy();
    expect(screen.getByText("trajectory.started")).toBeTruthy();
    expect(screen.getByText("trajectory.finished")).toBeTruthy();
  });
});
