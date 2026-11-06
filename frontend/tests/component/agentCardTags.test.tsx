// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AgentCardTags } from "@/app/agent-space/components/AgentCardTags";

let width = 180;
let callbacks: (() => void)[] = [];
const labels = ["First", "Second", "Third"];
const originalResizeObserver = window.ResizeObserver;

beforeEach(() => {
  width = 180;
  callbacks = [];
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(
    () => width
  );
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
    function (this: HTMLElement) {
      return {
        width: this.textContent?.startsWith("+") ? 28 : 60,
        height: 24,
        top: 0,
        left: 0,
        right: 60,
        bottom: 24,
        x: 0,
        y: 0,
        toJSON: () => ({}),
      };
    }
  );
  window.ResizeObserver = class {
    constructor(callback: ResizeObserverCallback) {
      callbacks.push(() => callback([], this));
    }
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

afterEach(() => {
  vi.restoreAllMocks();
  window.ResizeObserver = originalResizeObserver;
});

describe("agent card tags", () => {
  it("shows only tags that fit and recalculates when the row shrinks or grows", () => {
    render(<AgentCardTags labels={labels} />);
    expect(screen.getByTitle("First")).toBeVisible();
    expect(screen.getByTitle("Second")).toBeVisible();
    expect(screen.queryByTitle("Third")).toBeNull();
    expect(screen.getByRole("button", { name: "+1" })).toBeVisible();
    width = 80;
    act(() => callbacks.forEach((callback) => callback()));
    expect(screen.getByRole("button", { name: "+3" })).toBeVisible();
    expect(screen.queryByTitle("First")).toBeNull();
    width = 196;
    act(() => callbacks.forEach((callback) => callback()));
    expect(screen.getByTitle("Third")).toBeVisible();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("reveals all complete labels on click without triggering the card", async () => {
    const onCardClick = vi.fn();
    render(
      <div onClick={onCardClick}>
        <AgentCardTags labels={labels} />
      </div>
    );
    fireEvent.click(screen.getByRole("button", { name: "+1" }));
    const popover = await screen.findByRole("tooltip");
    await waitFor(() =>
      labels.forEach((label) =>
        expect(within(popover).getByText(label)).toBeVisible()
      )
    );
    fireEvent.click(within(popover).getByText("Third"));
    expect(onCardClick).not.toHaveBeenCalled();
  });

  it.each(["hover", "focus"])("opens all tags on %s", async (trigger) => {
    render(<AgentCardTags labels={labels} />);
    const button = screen.getByRole("button", { name: "+1" });
    if (trigger === "hover") fireEvent.mouseEnter(button);
    else fireEvent.focus(button);
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Third");
  });

  it("preserves long-label hints, updates labels, and handles an empty list", () => {
    const longLabel = "超长标签".repeat(25);
    const { rerender, container } = render(
      <AgentCardTags labels={[longLabel]} />
    );
    expect(screen.getByTitle(longLabel)).toHaveClass(
      "truncate",
      "max-w-[120px]"
    );
    rerender(<AgentCardTags labels={labels} />);
    expect(screen.getByRole("button", { name: "+1" })).toBeVisible();
    rerender(<AgentCardTags labels={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("recalculates after a hidden tab becomes visible", () => {
    width = 0;
    render(<AgentCardTags labels={labels} />);
    width = 180;
    act(() => callbacks.forEach((callback) => callback()));
    expect(screen.getByRole("button", { name: "+1" })).toBeVisible();
  });
});
