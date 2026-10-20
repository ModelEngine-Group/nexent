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

test.each([false, true])(
  "develop collapsed rail retains expand action (agentChat=%s)",
  (newChatDesign) => {
    const create = vi.fn();
    render(
      <TooltipProvider>
        <ThreadListSidebar
          newChatDesign={newChatDesign}
          onNewConversation={create}
        />
      </TooltipProvider>
    );
    expect(screen.getByRole("complementary")).toBeInTheDocument();
    expect(screen.getByText("conversation list content")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "chat.sidebar.expand" })
    );
    expect(sidebar.toggleSidebar).toHaveBeenCalledTimes(1);
    expect(create).not.toHaveBeenCalled();
    if (newChatDesign) {
      expect(screen.getAllByRole("button")).toHaveLength(1);
    } else {
      fireEvent.click(
        screen.getByRole("button", {
          name: "workbench.sidebar.newConversation",
        })
      );
      expect(create).toHaveBeenCalledTimes(1);
    }
  }
);
