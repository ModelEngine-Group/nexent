// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useEffect } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { useSidebar } from "@/components/ui/sidebar";
import { WorkbenchConversationLayout } from "@/features/workbench/components/WorkbenchConversationLayout";

import { WorkbenchLoadingBoundary } from "@/features/workbench/components/WorkbenchLoadingBoundary";

function Conversation() {
  const { state, toggleSidebar } = useSidebar();
  return <button onClick={toggleSidebar}>{state}</button>;
}

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

test.each([
  "conversationReady",
  "modelsLoading",
  "bootstrapLoading",
  "resourcesResolving",
] as const)(
  "keeps collapsed state through the actual loading boundary: %s",
  (pending) => {
    const settled = {
      conversationReady: true,
      modelsLoading: false,
      bootstrapLoading: false,
      resourcesResolving: false,
    };
    function Layout({ loading }: { loading: boolean }) {
      const flags = {
        ...settled,
        [pending]: pending === "conversationReady" ? !loading : loading,
      };
      return (
        <WorkbenchConversationLayout ready>
          <WorkbenchLoadingBoundary {...flags}>
            <Conversation />
          </WorkbenchLoadingBoundary>
        </WorkbenchConversationLayout>
      );
    }
    const { rerender } = render(<Layout loading={false} />);
    fireEvent.click(screen.getByRole("button", { name: "expanded" }));
    for (let attempt = 0; attempt < 2; attempt++) {
      rerender(<Layout loading />);
      expect(screen.queryByRole("button")).toBeNull();
      expect(screen.getByRole("status")).toBeInTheDocument();
      rerender(<Layout loading={false} />);
      expect(
        screen.getByRole("button", { name: "collapsed" })
      ).toBeInTheDocument();
    }
  }
);

test("conversation loading leaves sidebar mounted and preserves its local search", () => {
  const mounted = vi.fn();
  function SidebarProbe() {
    useEffect(() => {
      mounted();
    }, []);
    return <input aria-label="history search" defaultValue="" />;
  }
  function Page({ ready }: { ready: boolean }) {
    return (
      <WorkbenchConversationLayout ready>
        <SidebarProbe />
        <WorkbenchLoadingBoundary
          conversationReady={ready}
          modelsLoading={false}
          bootstrapLoading={false}
          resourcesResolving={false}
        >
          <Conversation />
        </WorkbenchLoadingBoundary>
      </WorkbenchConversationLayout>
    );
  }
  const { rerender } = render(<Page ready />);
  fireEvent.change(screen.getByRole("textbox", { name: "history search" }), {
    target: { value: "saved search" },
  });
  for (let attempt = 0; attempt < 2; attempt++) {
    rerender(<Page ready={false} />);
    expect(screen.getByRole("textbox", { name: "history search" })).toHaveValue(
      "saved search"
    );
    expect(screen.queryByRole("button")).toBeNull();
    rerender(<Page ready />);
  }
  expect(mounted).toHaveBeenCalledOnce();
});
