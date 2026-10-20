// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { ConversationSidebarProvider } from "@/components/common/ConversationSidebarProvider";
import { useSidebar } from "@/components/ui/sidebar";
import { useConversationSidebarStore } from "@/stores/conversationSidebarStore";

function StateButton() {
  const { state, toggleSidebar } = useSidebar();
  return <button onClick={toggleSidebar}>{state}</button>;
}

beforeEach(() => {
  useConversationSidebarStore.setState({
    open: { workbench: true, "agent-chat": true },
  });
});

test("route unmount and return preserve collapsed Workbench visibility independently of Agent chat", () => {
  const { rerender } = render(
    <ConversationSidebarProvider key="workbench" scope="workbench">
      <StateButton />
    </ConversationSidebarProvider>
  );
  fireEvent.click(screen.getByRole("button", { name: "expanded" }));
  rerender(<div>another route</div>);
  rerender(
    <ConversationSidebarProvider key="agent-chat" scope="agent-chat">
      <StateButton />
    </ConversationSidebarProvider>
  );
  expect(screen.getByRole("button", { name: "expanded" })).toBeInTheDocument();
  rerender(
    <ConversationSidebarProvider key="workbench" scope="workbench">
      <StateButton />
    </ConversationSidebarProvider>
  );
  expect(screen.getByRole("button", { name: "collapsed" })).toBeInTheDocument();
  expect(useConversationSidebarStore.getState().open["agent-chat"]).toBe(true);
});

test("Agent chat retains its own state while Workbench can be expanded independently", () => {
  const { rerender } = render(
    <ConversationSidebarProvider key="agent-chat" scope="agent-chat">
      <StateButton />
    </ConversationSidebarProvider>
  );
  fireEvent.click(screen.getByRole("button", { name: "expanded" }));
  rerender(
    <ConversationSidebarProvider key="workbench" scope="workbench">
      <StateButton />
    </ConversationSidebarProvider>
  );
  expect(screen.getByRole("button", { name: "expanded" })).toBeInTheDocument();
  rerender(
    <ConversationSidebarProvider key="agent-chat" scope="agent-chat">
      <StateButton />
    </ConversationSidebarProvider>
  );
  expect(screen.getByRole("button", { name: "collapsed" })).toBeInTheDocument();
});

test("a freshly loaded store starts expanded even if the previous document stored collapsed values", async () => {
  useConversationSidebarStore.getState().setOpen("workbench", false);
  useConversationSidebarStore.getState().setOpen("agent-chat", false);
  vi.resetModules();
  const fresh = await import("@/stores/conversationSidebarStore");
  expect(fresh.useConversationSidebarStore.getState().open).toEqual({
    workbench: true,
    "agent-chat": true,
  });
});
