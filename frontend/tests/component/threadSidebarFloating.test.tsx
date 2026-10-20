// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ReactNode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ThreadListSidebar } from "@/app/newchat/assistant-ui/threadlist-sidebar";

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
vi.mock("@/app/newchat/assistant-ui/agent-selector-dropdown", () => ({
  AgentSelectorDropdown: () => null,
}));

beforeEach(() => {
  sidebar.state = "collapsed";
  sidebar.isMobile = false;
  sidebar.openMobile = false;
});

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

test("Workbench hidden collapse does not render a second rail or floating action", () => {
  const { container } = render(<ThreadListSidebar collapseToHeader />);
  expect(container).toBeEmptyDOMElement();
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
