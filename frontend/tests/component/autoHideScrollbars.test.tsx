// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AutoHideScrollbars } from "@/components/providers/AutoHideScrollbars";

describe("AutoHideScrollbars", () => {
  beforeEach(() => vi.useFakeTimers());

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("reveals only the scrolling container and resets its hide delay", () => {
    const { getByTestId } = render(
      <>
        <AutoHideScrollbars />
        <div data-testid="outer">
          <div data-testid="inner" />
        </div>
      </>
    );
    const inner = getByTestId("inner");
    const outer = getByTestId("outer");
    expect(document.documentElement).toHaveClass("auto-hide-scrollbars");
    expect(inner).not.toHaveAttribute("data-scrollbar-scrolling");

    fireEvent.scroll(inner);
    expect(inner).toHaveAttribute("data-scrollbar-scrolling");
    expect(outer).not.toHaveAttribute("data-scrollbar-scrolling");
    act(() => vi.advanceTimersByTime(500));
    fireEvent.scroll(inner);
    act(() => vi.advanceTimersByTime(599));
    expect(inner).toHaveAttribute("data-scrollbar-scrolling");
    act(() => vi.advanceTimersByTime(1));
    expect(inner).not.toHaveAttribute("data-scrollbar-scrolling");
  });

  it("tracks late-mounted portal content independently from page scrolling", () => {
    render(<AutoHideScrollbars />);
    const portal = document.createElement("div");
    document.body.append(portal);
    const scrollingElement = document.scrollingElement;
    Object.defineProperty(document, "scrollingElement", {
      configurable: true,
      value: document.documentElement,
    });
    try {
      fireEvent.scroll(document);
      act(() => vi.advanceTimersByTime(300));
      fireEvent.scroll(portal);
      act(() => vi.advanceTimersByTime(300));
      expect(document.documentElement).not.toHaveAttribute(
        "data-scrollbar-scrolling"
      );
      expect(portal).toHaveAttribute("data-scrollbar-scrolling");
      act(() => vi.advanceTimersByTime(300));
      expect(portal).not.toHaveAttribute("data-scrollbar-scrolling");
    } finally {
      portal.remove();
      Object.defineProperty(document, "scrollingElement", {
        configurable: true,
        value: scrollingElement,
      });
    }
  });

  it("cleans up pending timers and stops listening when unmounted", () => {
    const { getByTestId, unmount } = render(
      <>
        <AutoHideScrollbars />
        <div data-testid="scroll" />
      </>
    );
    const target = getByTestId("scroll");
    fireEvent.scroll(target);
    unmount();
    expect(document.documentElement).not.toHaveClass("auto-hide-scrollbars");
    expect(target).not.toHaveAttribute("data-scrollbar-scrolling");
    expect(vi.getTimerCount()).toBe(0);
    fireEvent.scroll(document);
    expect(document.documentElement).not.toHaveAttribute(
      "data-scrollbar-scrolling"
    );
  });
});
