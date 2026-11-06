// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { ConversationSidebarProvider } from "@/components/common/ConversationSidebarProvider";
import { useSidebar } from "@/components/ui/sidebar";

function StateButton() {
  const { state, toggleSidebar } = useSidebar();
  return <button onClick={toggleSidebar}>{state}</button>;
}

test.each(["workbench", "agent-chat"])(
  "%s resets to expanded after leaving and returning",
  (page) => {
    const { rerender } = render(
      <ConversationSidebarProvider key={page}>
        <StateButton />
      </ConversationSidebarProvider>
    );
    fireEvent.click(screen.getByRole("button", { name: "expanded" }));
    expect(
      screen.getByRole("button", { name: "collapsed" })
    ).toBeInTheDocument();
    rerender(<div>another page</div>);
    rerender(
      <ConversationSidebarProvider key={page}>
        <StateButton />
      </ConversationSidebarProvider>
    );
    expect(
      screen.getByRole("button", { name: "expanded" })
    ).toBeInTheDocument();
  }
);

test("separate conversation pages start expanded independently", () => {
  const { rerender } = render(
    <ConversationSidebarProvider key="workbench">
      <StateButton />
    </ConversationSidebarProvider>
  );
  fireEvent.click(screen.getByRole("button", { name: "expanded" }));
  rerender(
    <ConversationSidebarProvider key="agent-chat">
      <StateButton />
    </ConversationSidebarProvider>
  );
  expect(screen.getByRole("button", { name: "expanded" })).toBeInTheDocument();
});
