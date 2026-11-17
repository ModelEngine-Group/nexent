// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import type { TFunction } from "i18next";
import zh from "../../public/locales/zh/common.json";
import en from "../../public/locales/en/common.json";
import { trajectoryNodeName } from "@/app/observability/components/TrajectoryPresentation";
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
            ? "Python 调用"
            : key === "trajectory.tools.python_interpreter"
              ? "代码执行"
              : key === "trajectory.tools.code"
                ? "Python 调用"
                : key === "trajectory.tools.parallel_executor"
                  ? "并行执行"
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
  it.each([
    ["zh", zh, "代码执行", "Python 调用", "并行执行"],
    ["en", en, "Code execution", "Python call", "Parallel execution"],
  ] as const)(
    "uses real %s names consistently",
    (_locale, dictionary, group, call, parallel) => {
      const translate = ((key: string) =>
        dictionary[key as keyof typeof dictionary] ?? key) as TFunction;
      expect(
        trajectoryNodeName(
          traceNode({ kind: "tool", name: "python_interpreter" }),
          translate
        )
      ).toBe(group);
      expect(
        trajectoryNodeName(
          traceNode({ kind: "phase", name: "code.execute" }),
          translate
        )
      ).toBe(call);
      expect(
        trajectoryNodeName(traceNode({ kind: "tool", name: "code" }), translate)
      ).toBe(call);
      expect(
        trajectoryNodeName(
          traceNode({ kind: "tool", name: "parallel_executor" }),
          translate
        )
      ).toBe(parallel);
      expect(
        trajectoryNodeName(
          traceNode({ kind: "tool", name: "read_skill_md" }),
          translate
        )
      ).toBe("read_skill_md");
    }
  );

  it.each([
    ["python_interpreter", "代码执行", ".lucide-code-xml"],
    ["parallel_executor", "并行执行", ".lucide-wrench"],
  ])(
    "localizes %s for tree, search and detail while selecting the original DTO",
    (name, label, icon) => {
      const tool = traceNode({
        id: "python",
        parent_id: "root",
        kind: "tool",
        name,
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
        target: { value: label },
      });
      const item = screen.getByRole("treeitem", { name: new RegExp(label) });
      expect(item.querySelector(icon)).toBeTruthy();
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
      expect(screen.getByRole("heading", { name: label })).toBeTruthy();
    }
  );

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
    expect(screen.getByRole("heading", { name: "Python 调用" })).toBeTruthy();
    expect(screen.getByText("125 ms")).toBeTruthy();
    expect(screen.queryByText("trajectory.toolCalls")).toBeNull();
  });

  it("labels generated code as Python calls and leaves named tools unchanged", () => {
    const generated = traceNode({
      id: "code",
      parent_id: "root",
      kind: "tool",
      name: "code",
    });
    const named = traceNode({
      id: "read",
      parent_id: "root",
      kind: "tool",
      name: "read_skill_md",
    });
    const onSelect = vi.fn();
    const view = render(
      <App>
        <TrajectoryTimeline
          nodes={[traceNode(), generated, named]}
          complete
          cache={new BodyCache()}
          onSelect={onSelect}
        />
      </App>
    );
    const python = screen.getByRole("treeitem", { name: /Python 调用/ });
    expect(python.querySelector(".lucide-terminal")).toBeTruthy();
    expect(
      screen
        .getByRole("treeitem", { name: /read_skill_md/ })
        .querySelector(".lucide-wrench")
    ).toBeTruthy();
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Python 调用" },
    });
    expect(
      screen.queryByRole("treeitem", { name: /read_skill_md/ })
    ).toBeNull();
    fireEvent.click(screen.getByRole("treeitem", { name: /Python 调用/ }));
    expect(onSelect).toHaveBeenCalledWith(generated);
    view.unmount();
    const onParent = vi.fn();
    render(
      <App>
        <TrajectoryNodeDetail
          node={generated}
          conversationId="123"
          cache={new BodyCache()}
          onParent={onParent}
          onLoaded={vi.fn()}
        />
      </App>
    );
    expect(screen.getByRole("heading", { name: "Python 调用" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /trajectory.parent/ }));
    expect(onParent).toHaveBeenCalledWith("root");
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
