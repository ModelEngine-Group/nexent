// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useEffect, type ReactNode } from "react";
import { act, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { AgentEditorSplit } from "@/app/agents/[agentId]/components/agent-editor-split";

const fixture = vi.hoisted(() => ({
  resize: (() => {}) as (sizes: number[]) => void,
  panels: [] as Array<Record<string, unknown>>,
}));

vi.mock("antd", () => {
  const Panel = ({ children, ...props }: { children: ReactNode }) => {
    fixture.panels.push(props);
    return children;
  };
  const Splitter = Object.assign(
    ({
      children,
      onResize,
    }: {
      children: ReactNode;
      onResize: (sizes: number[]) => void;
    }) => {
      fixture.resize = onResize;
      fixture.panels = [];
      return children;
    },
    { Panel }
  );
  return { Splitter };
});

it.each(["start", "end"] as const)(
  "remembers bounded proportions for the %s panel",
  (side) => {
    render(
      <AgentEditorSplit side={side} visible panel={<div>Panel</div>}>
        <div>Config</div>
      </AgentEditorSplit>
    );
    const index = side === "start" ? 0 : 1;
    act(() => fixture.resize(side === "start" ? [400, 600] : [600, 400]));
    expect(fixture.panels[index].size).toBe("40%");
    act(() => fixture.resize(side === "start" ? [950, 50] : [50, 950]));
    expect(fixture.panels[index].size).toBe("65%");
    act(() => fixture.resize(side === "start" ? [50, 950] : [950, 50]));
    expect(fixture.panels[index].size).toBe("25%");
  }
);

it("reserves 800px for configuration and adapts the drag limit to the viewport", () => {
  const clientWidth = vi
    .spyOn(HTMLElement.prototype, "clientWidth", "get")
    .mockReturnValue(1440);
  let resized = () => {};
  const disconnect = vi.fn();
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(callback: () => void) {
        resized = callback;
      }
      observe() {}
      disconnect = disconnect;
    }
  );
  try {
    const { unmount } = render(
      <AgentEditorSplit
        side="start"
        visible
        min={20}
        max={55}
        contentMin={800}
        panel={<div>Panel</div>}
      >
        <div>Config</div>
      </AgentEditorSplit>
    );
    act(() => fixture.resize([900, 540]));
    expect(Number.parseFloat(String(fixture.panels[0].size))).toBeCloseTo(
      44.444
    );
    expect(Number.parseFloat(String(fixture.panels[1].min))).toBeCloseTo(
      55.556
    );
    clientWidth.mockReturnValue(1200);
    act(() => resized());
    expect(Number.parseFloat(String(fixture.panels[0].size))).toBeCloseTo(
      33.333
    );
    clientWidth.mockReturnValue(900);
    act(() => resized());
    expect(fixture.panels[0].size).toBe("20%");
    expect(fixture.panels[1].min).toBe("80%");
    unmount();
    expect(disconnect).toHaveBeenCalledOnce();
  } finally {
    vi.unstubAllGlobals();
  }
});

it.each([
  [0, 0],
  [NaN, 600],
  [Infinity, 600],
  [-1, 600],
])("ignores invalid measurements %j", (first, second) => {
  render(
    <AgentEditorSplit visible panel={<div>Panel</div>}>
      <div>Config</div>
    </AgentEditorSplit>
  );
  act(() => fixture.resize([first, second]));
  expect(fixture.panels[1].size).toBe("48%");
});

it("retains mounted content and restores widths through hidden and expanded modes", () => {
  const mounted = vi.fn();
  const unmounted = vi.fn();
  function Content() {
    useEffect(() => {
      mounted();
      return unmounted;
    }, []);
    return <input aria-label="Draft" defaultValue="Keep this draft" />;
  }
  const view = (visible: boolean, expanded = false) => (
    <AgentEditorSplit visible={visible} expanded={expanded} panel={<Content />}>
      <div>Config</div>
    </AgentEditorSplit>
  );
  const { rerender } = render(view(true));
  const draft = screen.getByRole("textbox");
  act(() => fixture.resize([600, 400]));
  for (const mode of ["hidden", "expanded"] as const) {
    rerender(view(mode !== "hidden", mode === "expanded"));
    expect(fixture.panels[1].size).toBe(mode === "hidden" ? 0 : "100%");
    expect(fixture.panels[1].resizable).toBe(false);
    act(() => fixture.resize([100, 900]));
    rerender(view(true));
    expect(fixture.panels[1].size).toBe("40%");
    expect(fixture.panels[1].resizable).toBe(true);
    expect(screen.getByRole("textbox")).toBe(draft);
  }
  expect(mounted).toHaveBeenCalledTimes(1);
  expect(unmounted).not.toHaveBeenCalled();
});
