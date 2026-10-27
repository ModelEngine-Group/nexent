// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { Agent } from "@/types/agentConfig";
import type { ReactNode } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ThreadListSidebar } from "@/app/newchat/assistant-ui/threadlist-sidebar";

const activitySync = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/chat/useConversationActivitySync", () => ({
  useConversationActivitySync: activitySync,
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({
    user: { id: "sidebar-user", tenantId: "sidebar-tenant" },
  }),
}));
const sidebar = vi.hoisted(() => ({
  state: "collapsed",
  isMobile: false,
  openMobile: false,
  toggleSidebar: vi.fn(),
}));
vi.mock("@/hooks/use-mobile", () => ({ useIsMobile: () => sidebar.isMobile }));
vi.mock("@/components/ui/sidebar", () => ({
  useSidebar: () => sidebar,
  Sidebar: ({ children }: { children: ReactNode }) => <aside>{children}</aside>,
  SidebarHeader: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  SidebarContent: () => <div>conversation list content</div>,
  SidebarFooter: () => null,
  SidebarTrigger: () => null,
}));
vi.mock("@/app/newchat/assistant-ui/thread-list", () => ({
  BatchSelectionProvider: ({ children }: { children: ReactNode }) => children,
  PinnedThreadsProvider: ({ children }: { children: ReactNode }) => children,
  BatchSidebarFooter: () => null,
  ThreadList: () => null,
}));
vi.mock("@/app/newchat/assistant-ui/workbench-pin-history-sync", () => ({
  WorkbenchPinHistorySync: () => null,
}));
vi.mock("@/app/newchat/assistant-ui/agent-selector-dropdown", () => ({
  AgentSelectorDropdown: () => (
    <select aria-label="Agent selector">
      <option>Selected Agent</option>
    </select>
  ),
}));

vi.mock("@assistant-ui/react", () => ({
  ThreadListPrimitive: {
    Root: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  },
  ThreadListItemPrimitive: {},
  ThreadListItemMorePrimitive: {},
}));

beforeEach(() => {
  activitySync.mockClear();
  sidebar.state = "collapsed";
  sidebar.isMobile = false;
  sidebar.openMobile = false;
});

test.each([false, true])(
  "collapsed sidebar retains account-scoped activity synchronization (agentChat=%s)",
  (newChatDesign) => {
    render(
      <TooltipProvider>
        <ThreadListSidebar
          collapseToFloatingButton
          newChatDesign={newChatDesign}
        />
      </TooltipProvider>
    );
    expect(activitySync).toHaveBeenCalledWith(
      "sidebar-user:sidebar-tenant",
      newChatDesign ? "agent_chat" : "workbench"
    );
  }
);

test("floating Agent-chat collapse renders one expand action with no rail, header or new-conversation action", () => {
  const create = vi.fn();
  const { container } = render(
    <TooltipProvider>
      <ThreadListSidebar
        newChatDesign
        collapseToFloatingButton
        onNewConversation={create}
      />
    </TooltipProvider>
  );
  expect(screen.getAllByRole("button")).toHaveLength(1);
  const expand = screen.getByRole("button", { name: "chat.sidebar.expand" });
  expect(expand).toHaveAttribute("aria-expanded", "false");
  expect(
    container.querySelector("[data-floating-sidebar-trigger]")
  ).toHaveClass("absolute", "left-3", "top-3");
  expect(container.querySelector("aside, header")).toBeNull();
  fireEvent.click(expand);
  expect(sidebar.toggleSidebar).toHaveBeenCalledTimes(1);
  expect(create).not.toHaveBeenCalled();
});

test("keeps the discovery sidebar hidden while a saved Agent view is restoring", () => {
  sidebar.state = "expanded";
  const { container } = render(
    <TooltipProvider>
      <ThreadListSidebar newChatDesign isRestoringView />
    </TooltipProvider>
  );

  expect(container.querySelector(".animate-pulse")).toBeInTheDocument();
  expect(screen.queryByText("sidebar.startChat")).toBeNull();
  expect(screen.queryByRole("combobox", { name: "Agent selector" })).toBeNull();
});

test("collapsed Agent chat shows compact conversation actions and a truncated agent name", () => {
  const create = vi.fn();
  const back = vi.fn();
  const longAgentName =
    "Agent name that is much longer than the compact header";
  const { container } = render(
    <TooltipProvider>
      <ThreadListSidebar
        newChatDesign
        collapseToFloatingButton
        selectedAgent={
          {
            id: "fixture",
            name: longAgentName,
            display_name: longAgentName,
          } as Agent
        }
        onNewConversation={create}
        onPrepareNewConversation={back}
      />
    </TooltipProvider>
  );

  expect(screen.getByText(longAgentName)).toHaveClass("truncate");
  expect(
    screen.getByRole("button", { name: "workbench.sidebar.newConversation" })
  ).toBeInTheDocument();
  const discoverButton = screen.getByRole("button", {
    name: "chat.sidebar.discoverAgents",
  });
  expect(discoverButton).toBeInTheDocument();
  expect(
    container.querySelector("[data-floating-sidebar-trigger]")
  ).toHaveAttribute("data-collapsed-agent-toolbar");

  fireEvent.click(
    screen.getByRole("button", { name: "workbench.sidebar.newConversation" })
  );
  fireEvent.click(discoverButton);
  expect(create).toHaveBeenCalledTimes(1);
  expect(back).toHaveBeenCalledTimes(1);
});

test("Workbench hidden collapse does not render a second rail or floating action", () => {
  const { container } = render(<ThreadListSidebar collapseToHeader />);
  expect(container).toBeEmptyDOMElement();
});

test("Workbench floating controls preserve expand and new-conversation actions without a header", () => {
  const create = vi.fn();
  const { container } = render(
    <TooltipProvider>
      <ThreadListSidebar collapseToFloatingButton onNewConversation={create} />
    </TooltipProvider>
  );
  expect(container.querySelector("header, aside")).toBeNull();
  expect(screen.getAllByRole("button")).toHaveLength(2);
  fireEvent.click(
    screen.getByRole("button", { name: "workbench.sidebar.newConversation" })
  );
  expect(create).toHaveBeenCalledTimes(1);
});

test("Workbench places title and search above its full-width new-conversation button", () => {
  sidebar.state = "expanded";
  render(
    <TooltipProvider>
      <ThreadListSidebar collapseToFloatingButton onNewConversation={vi.fn()} />
    </TooltipProvider>
  );
  const titleRow = screen
    .getByText("workbench.sidebar.title")
    .closest("[data-workbench-header-actions]")!;
  expect(
    titleRow.contains(
      screen.getByRole("button", { name: "chat.sidebar.search" })
    )
  ).toBe(true);
  expect(
    titleRow.contains(
      screen.getByRole("button", { name: "workbench.sidebar.newConversation" })
    )
  ).toBe(false);
});

test("narrow Agent chat retains the original expand position and reserves a content gutter", () => {
  let notifyResize: (() => void) | undefined;
  const originalResizeObserver = window.ResizeObserver;
  window.ResizeObserver = class {
    constructor(private callback: ResizeObserverCallback) {}
    observe(target: Element) {
      if (target.hasAttribute("data-agent-chat-page")) {
        notifyResize = () => this.callback([], this);
      }
    }
    unobserve() {}
    disconnect() {}
  };
  try {
    const { container, unmount } = render(
      <TooltipProvider>
        <div data-agent-chat-page>
          <ThreadListSidebar
            newChatDesign
            collapseToFloatingButton
            selectedAgent={{ id: "fixture", name: "Agent" } as Agent}
          />
        </div>
      </TooltipProvider>
    );
    const page = container.querySelector("[data-agent-chat-page]")!;
    const bounds = vi.spyOn(page, "getBoundingClientRect");
    bounds.mockReturnValue({ width: 900, left: 240 } as DOMRect);
    const toolbar = container.querySelector("[data-floating-sidebar-trigger]")!;
    vi.spyOn(toolbar, "getBoundingClientRect").mockReturnValue({
      top: 72,
    } as DOMRect);
    act(() => notifyResize?.());
    expect(toolbar).toHaveAttribute("data-expand-gutter", "true");
    expect(toolbar).toHaveClass("left-3", "top-3");
    expect(
      page.contains(screen.getByRole("button", { name: "chat.sidebar.expand" }))
    ).toBe(true);
    expect(
      screen.getByRole("button", { name: "chat.sidebar.expand" })
    ).toHaveClass("!size-8");
    fireEvent.click(
      screen.getByRole("button", { name: "chat.sidebar.expand" })
    );
    expect(sidebar.toggleSidebar).toHaveBeenCalledTimes(1);
    bounds.mockReturnValue({ width: 1600, left: 240 } as DOMRect);
    act(() => notifyResize?.());
    expect(toolbar).not.toHaveAttribute("data-expand-gutter");
    expect(
      page.contains(screen.getByRole("button", { name: "chat.sidebar.expand" }))
    ).toBe(true);
    unmount();
  } finally {
    window.ResizeObserver = originalResizeObserver;
  }
});

test("legacy collapse remains available without opting into a compact presentation", () => {
  render(
    <TooltipProvider>
      <ThreadListSidebar newChatDesign />
    </TooltipProvider>
  );
  expect(screen.getByRole("complementary")).toBeInTheDocument();
  expect(screen.getByText("conversation list content")).toBeInTheDocument();
});

test("mobile collapsed action remains reachable even when desktop state is expanded", () => {
  sidebar.state = "expanded";
  sidebar.isMobile = true;
  render(
    <TooltipProvider>
      <ThreadListSidebar newChatDesign collapseToFloatingButton />
    </TooltipProvider>
  );
  fireEvent.click(screen.getByRole("button", { name: "chat.sidebar.expand" }));
  expect(sidebar.toggleSidebar).toHaveBeenCalledTimes(1);
});

test("discovery header shows its title and search without agent selection or a new conversation", () => {
  sidebar.state = "expanded";
  const create = vi.fn();
  render(
    <TooltipProvider>
      <ThreadListSidebar
        newChatDesign
        selectedAgent={null}
        onNewConversation={create}
        onAgentSelected={vi.fn()}
        onPrepareNewConversation={vi.fn()}
      />
    </TooltipProvider>
  );
  expect(screen.getByText("sidebar.startChat")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "chat.sidebar.search" })
  ).toBeEnabled();
  expect(screen.queryByRole("combobox", { name: "Agent selector" })).toBeNull();
  expect(
    screen.queryByRole("button", { name: "chat.sidebar.newConversation" })
  ).toBeNull();
  expect(
    screen.queryByRole("button", { name: "chat.sidebar.discoverAgents" })
  ).toBeNull();
  expect(create).not.toHaveBeenCalled();
});

test("selecting an agent restores the conversation actions", () => {
  sidebar.state = "expanded";
  const create = vi.fn();
  const { rerender } = render(
    <TooltipProvider>
      <ThreadListSidebar
        newChatDesign
        selectedAgent={null}
        onNewConversation={create}
        onAgentSelected={vi.fn()}
      />
    </TooltipProvider>
  );
  rerender(
    <TooltipProvider>
      <ThreadListSidebar
        newChatDesign
        selectedAgent={{ id: "fixture", name: "Agent" } as Agent}
        onNewConversation={create}
        onAgentSelected={vi.fn()}
      />
    </TooltipProvider>
  );
  expect(
    screen.getByRole("combobox", { name: "Agent selector" })
  ).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "chat.sidebar.newConversation" })
  );
  expect(create).toHaveBeenCalledTimes(1);
  expect(screen.queryByText("sidebar.startChat")).toBeNull();
});
