// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, test } from "vitest";
import { useConversationSidebarStore } from "@/stores/conversationSidebarStore";
import { useSidebar } from "@/components/ui/sidebar";
import { WorkbenchConversationLayout } from "@/features/workbench/components/WorkbenchConversationLayout";

function Conversation() {
  const { state, toggleSidebar } = useSidebar();
  return <button onClick={toggleSidebar}>{state}</button>;
}

beforeEach(() => {
  useConversationSidebarStore.setState({
    open: { workbench: true, "agent-chat": true },
  });
});

test("collapsed sidebar survives the conversation loading and remount cycle", () => {
  const { rerender } = render(
    <WorkbenchConversationLayout ready>
      <Conversation />
    </WorkbenchConversationLayout>
  );
  fireEvent.click(screen.getByRole("button", { name: "expanded" }));
  expect(screen.getByRole("button", { name: "collapsed" })).toBeInTheDocument();
  rerender(
    <WorkbenchConversationLayout ready={false}>
      <Conversation />
    </WorkbenchConversationLayout>
  );
  expect(screen.queryByRole("button")).toBeNull();
  expect(screen.getByText("chat.threadList.loading")).toBeInTheDocument();
  rerender(
    <WorkbenchConversationLayout ready>
      <Conversation />
    </WorkbenchConversationLayout>
  );
  fireEvent.click(screen.getByRole("button", { name: "collapsed" }));
  expect(screen.getByRole("button", { name: "expanded" })).toBeInTheDocument();
});

test("expanded sidebar also survives repeated conversation loading cycles", () => {
  const { rerender } = render(
    <WorkbenchConversationLayout ready>
      <Conversation />
    </WorkbenchConversationLayout>
  );
  for (let cycle = 0; cycle < 2; cycle += 1) {
    rerender(
      <WorkbenchConversationLayout ready={false}>
        <Conversation />
      </WorkbenchConversationLayout>
    );
    rerender(
      <WorkbenchConversationLayout ready>
        <Conversation />
      </WorkbenchConversationLayout>
    );
    expect(
      screen.getByRole("button", { name: "expanded" })
    ).toBeInTheDocument();
  }
});
