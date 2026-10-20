// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ConversationHeaderActions } from "@/components/common/ConversationHeaderActions";

const sidebar = vi.hoisted(() => ({
  state: "collapsed",
  isMobile: false,
  openMobile: false,
  toggleSidebar: vi.fn(),
}));
vi.mock("@/components/ui/sidebar", () => ({ useSidebar: () => sidebar }));

beforeEach(() => {
  sidebar.state = "collapsed";
  sidebar.isMobile = false;
  sidebar.openMobile = false;
});

function renderActions(onNewConversation = vi.fn()) {
  render(
    <TooltipProvider>
      <ConversationHeaderActions
        position="leading"
        onNewConversation={onNewConversation}
      />
      <ConversationHeaderActions
        position="trailing"
        onNewConversation={onNewConversation}
      />
    </TooltipProvider>
  );
  return onNewConversation;
}

test("collapsed header exposes expansion and invokes the existing new-conversation action once", () => {
  const create = renderActions();
  fireEvent.click(screen.getByRole("button", { name: "chat.sidebar.expand" }));
  expect(sidebar.toggleSidebar).toHaveBeenCalledTimes(1);
  expect(create).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "workbench.sidebar.newConversation" })
  );
  expect(create).toHaveBeenCalledTimes(1);
});

test("expanded desktop list does not duplicate header actions", () => {
  sidebar.state = "expanded";
  renderActions();
  expect(screen.queryAllByRole("button")).toHaveLength(0);
});

test("mobile actions follow the mobile drawer state independently of desktop expansion", () => {
  sidebar.isMobile = true;
  sidebar.state = "expanded";
  const { rerender } = render(
    <TooltipProvider>
      <ConversationHeaderActions
        position="leading"
        onNewConversation={vi.fn()}
      />
    </TooltipProvider>
  );
  expect(screen.getByRole("button")).toHaveAttribute("aria-expanded", "false");
  sidebar.openMobile = true;
  rerender(
    <TooltipProvider>
      <ConversationHeaderActions
        position="leading"
        onNewConversation={vi.fn()}
      />
    </TooltipProvider>
  );
  expect(screen.queryByRole("button")).toBeNull();
});
