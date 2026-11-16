// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ConversationHistoryLabel } from "@/components/common/ConversationHistoryLabel";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { ReactElement, ReactNode } from "react";

// Keep tooltip positioning external to the unit proof; D4 exercises real Radix hover.
vi.mock("@/components/ui/tooltip", async () => {
  const { createContext, useContext, cloneElement } = await import("react");
  const State = createContext<{
    open: boolean;
    onOpenChange: (open: boolean) => void;
  }>({
    open: false,
    onOpenChange: () => {},
  });
  return {
    TooltipProvider: ({ children }: { children: ReactNode }) => children,
    Tooltip: ({
      children,
      ...state
    }: {
      children: ReactNode;
      open: boolean;
      onOpenChange: (open: boolean) => void;
    }) => <State.Provider value={state}>{children}</State.Provider>,
    TooltipTrigger: ({
      children,
    }: {
      children: ReactElement<{ onMouseEnter?: () => void }>;
    }) => {
      const state = useContext(State);
      return cloneElement(children, {
        onMouseEnter: () => state.onOpenChange(true),
      });
    },
    TooltipContent: ({ children }: { children: ReactNode }) =>
      useContext(State).open ? <div role="tooltip">{children}</div> : null,
  };
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function setup() {
  return render(
    <TooltipProvider delayDuration={0}>
      <ConversationHistoryLabel title="Long history title" time="2m ago" />
    </TooltipProvider>
  );
}

function hover(element: Element) {
  fireEvent.mouseEnter(element);
}

it("reserves metadata width while hover and focus hide time", () => {
  const { container } = setup();
  const title = container.querySelector("[data-history-title]");
  const time = screen.getByText("2m ago");
  expect(title).toHaveClass("truncate", "min-w-0");
  expect(time).toHaveClass(
    "group-hover/item:invisible",
    "group-focus-within/item:invisible"
  );
  expect(time.className).not.toMatch(
    /(?:^|\s)(?:group-hover\/item|group-focus-within\/item):hidden(?:\s|$)/
  );
  expect(title).not.toHaveAttribute("title");
});

it("keeps time visible in batch mode without row actions", () => {
  render(
    <TooltipProvider>
      <ConversationHistoryLabel
        title="Batch title"
        time="2m ago"
        showActions={false}
      />
    </TooltipProvider>
  );
  expect(screen.getByText("2m ago")).not.toHaveClass(
    "group-hover/item:invisible",
    "group-focus-within/item:invisible"
  );
});

it.each([false, true])(
  "opens the shared tooltip only for actual overflow=%s",
  async (overflow) => {
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(100);
    vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockReturnValue(
      overflow ? 160 : 100
    );
    const { container } = setup();
    const title = container.querySelector("[data-history-title]")!;
    hover(title);
    if (overflow)
      expect(await screen.findByRole("tooltip")).toHaveTextContent(
        "Long history title"
      );
    else expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  }
);

it("closes an obsolete tooltip after resize and releases its observer", async () => {
  let resize!: () => void;
  const disconnect = vi.fn();
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(private callback: () => void) {}
      observe(element: Element) {
        if (element.hasAttribute("data-history-title")) resize = this.callback;
      }
      unobserve() {}
      disconnect() {
        disconnect();
      }
    }
  );
  let width = 80;
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(
    () => width
  );
  vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockReturnValue(160);
  const { container, unmount } = setup();
  hover(container.querySelector("[data-history-title]")!);
  await screen.findByRole("tooltip");
  width = 200;
  act(() => resize());
  await waitFor(() =>
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument()
  );
  unmount();
  expect(disconnect).toHaveBeenCalled();
});
