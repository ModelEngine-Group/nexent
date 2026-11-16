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
        : key === "trajectory.phases.memory.prepare"
          ? "记忆准备"
          : key === "trajectory.phases.code.execute"
            ? "代码执行"
            : key === "trajectory.tools.python_interpreter"
              ? "Python 解释器"
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
  it("localizes the Python tool for the tree, search and detail while selecting the original DTO", () => {
    const tool = traceNode({
      id: "python",
      parent_id: "root",
      kind: "tool",
      name: "python_interpreter",
    });
    const select = vi.fn();
    const view = render(
      <App>
        <TrajectoryTimeline
          nodes={[traceNode(), tool]}
          complete
          cache={new BodyCache()}
          onSelect={select}
        />
      </App>
    );
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "解释器" },
    });
    const item = screen.getByRole("treeitem", { name: /Python 解释器/ });
    fireEvent.click(item);
    expect(select).toHaveBeenCalledWith(tool);
    expect(screen.getByRole("treeitem", { name: /Root Agent/ })).toBeTruthy();
    view.unmount();
    render(
      <App>
        <TrajectoryNodeDetail
          node={select.mock.calls[0][0]}
          conversationId="123"
          cache={new BodyCache()}
          onParent={vi.fn()}
          onLoaded={vi.fn()}
        />
      </App>
    );
    expect(screen.getByRole("heading", { name: "Python 解释器" })).toBeTruthy();
  });

  it("shows code execution duration separately from sandbox initialization", () => {
    render(
      <App>
        <TrajectoryNodeDetail
          node={{ ...phase, name: "code.execute", duration_ms: 125 }}
          conversationId="123"
          cache={new BodyCache()}
          onParent={vi.fn()}
          onLoaded={vi.fn()}
        />
      </App>
    );
    expect(screen.getByRole("heading", { name: "代码执行" })).toBeTruthy();
    expect(screen.getByText("125 ms")).toBeTruthy();
    expect(screen.queryByText("trajectory.toolCalls")).toBeNull();
  });

  it("distinguishes grouped agents and preserves selection, search and detail titles", () => {
    const grouped = (id: string, name: string) => ({
      ...phase,
      id,
      name: "memory.prepare",
      attributes: {
        "agent.name": `internal_${id}`,
        "agent.display_name": name,
      },
    });
    const selected = grouped("memory-root", "主智能体");
    const onSelect = vi.fn();
    const { unmount } = render(
      <App>
        <TrajectoryTimeline
          nodes={[traceNode(), selected, grouped("memory-child", "子智能体")]}
          complete
          cache={new BodyCache()}
          onSelect={onSelect}
        />
      </App>
    );
    fireEvent.click(
      screen.getByRole("treeitem", { name: /记忆准备 · 主智能体/ })
    );
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ id: selected.id })
    );
    const clicked = onSelect.mock.calls[0][0];
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "子智能体" },
    });
    expect(
      screen.getByRole("treeitem", { name: /记忆准备 · 子智能体/ })
    ).toBeTruthy();
    expect(
      screen.queryByRole("treeitem", { name: /记忆准备 · 主智能体/ })
    ).toBeNull();
    unmount();
    render(
      <App>
        <TrajectoryNodeDetail
          node={clicked}
          conversationId="123"
          cache={new BodyCache()}
          onParent={vi.fn()}
          onLoaded={vi.fn()}
        />
      </App>
    );
    expect(
      screen.getByRole("heading", { name: "记忆准备 · 主智能体" })
    ).toBeTruthy();
  });

  it("shows a grouped phase without a name using the localized fallback", () => {
    render(
      <App>
        <TrajectoryNodeDetail
          node={{ ...phase, name: "memory.prepare", attributes: {} }}
          conversationId="123"
          cache={new BodyCache()}
          onParent={vi.fn()}
          onLoaded={vi.fn()}
        />
      </App>
    );
    expect(screen.getByRole("heading", { name: "记忆准备" })).toBeTruthy();
  });

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
