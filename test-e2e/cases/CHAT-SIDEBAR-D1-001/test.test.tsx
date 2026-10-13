vi.mock("@/app/i18n", () => ({ default: { t: (key: string) => key, language: "zh" } }));
import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { ThreadList, BatchSelectionProvider, BatchSidebarFooter } from "@/app/newchat/assistant-ui/thread-list";
const fixture = vi.hoisted(() => ({
  items: [{ id: "saved", remoteId: "42", title: "Saved conversation" }, { id: "draft", title: "Unsent draft" }],
  rename: vi.fn().mockResolvedValue(undefined),
  reload: vi.fn().mockResolvedValue(undefined),
  deleteBatch: vi.fn().mockResolvedValue({ failed_ids: [] }),
  confirm: vi.fn(),
}));
vi.mock("@assistant-ui/react", async () => {
  const React = await import("react");
  const Context = React.createContext(0);
  const Wrap = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  const Button = ({ children, onSelect, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { onSelect?: () => void }) => <button {...props} onClick={onSelect ?? props.onClick}>{children}</button>;
  const getState = () => ({ threads: { threadIds: fixture.items.map(i => i.id), threadItems: fixture.items, mainThreadId: "saved", isLoading: false, hasMore: false }, thread: { isRunning: false }, threadListItem: { isRunning: false } });
  return {
    useAuiState: (select: (state: ReturnType<typeof getState>) => unknown) => select(getState()),
    useAui: () => {
      const index = React.useContext(Context);
      const item = { getState: () => fixture.items[index], rename: fixture.rename, delete: vi.fn() };
      return { threadListItem: Object.assign(() => item, item), threads: { reload: fixture.reload } };
    },
    AuiIf: ({ condition, children }: { condition: (s: ReturnType<typeof getState>) => boolean; children: React.ReactNode }) => condition(getState()) ? children : null,
    ThreadListPrimitive: { Root: Wrap, LoadMore: Button, ItemByIndex: ({ index, components }: { index: number; components: { ThreadListItem: React.ComponentType } }) => <Context.Provider value={index}><components.ThreadListItem /></Context.Provider> },
    ThreadListItemPrimitive: { Root: Wrap, Trigger: Button },
    ThreadListItemMorePrimitive: { Root: Wrap, Trigger: Button, Content: Wrap, Item: Button },
  };
});
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("@/hooks/agent/usePublishedAgentList", () => ({ usePublishedAgentList: () => ({ availableMainAgents: [] }) }));
vi.mock("@/hooks/useConfirmModal", () => ({ useConfirmModal: () => ({ confirm: fixture.confirm }) }));
vi.mock("@/services/conversationService", () => ({ conversationService: { deleteBatch: fixture.deleteBatch } }));
vi.mock("@/app/newchat/adapter/conversation-thread-list-adapter", () => ({ setPendingThreadOperationId: vi.fn() }));
vi.mock("@/app/newchat/adapter/thread-agent-registry", () => ({ resolveThreadAgentId: () => null, useThreadAgentOverrides: () => ({}) }));
vi.mock("@/components/ui/tooltip", () => {
  const Wrap = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  return { Tooltip: Wrap, TooltipTrigger: Wrap, TooltipContent: () => null };
});
beforeEach(() => { fixture.items = [{ id: "saved", remoteId: "42", title: "Saved conversation" }, { id: "draft", title: "Unsent draft" }]; });

test("[CHAT-SIDEBAR-D1-001] persisted conversations remain visible and unsent drafts stay hidden", () => {
  render(<ThreadList generatedTitles={new Map([["42", "Server title"]])} />);
  expect(screen.getByText("Server title")).toBeVisible();
  expect(screen.queryByText("Unsent draft")).toBeNull();
});
test("[CHAT-SIDEBAR-D1-001] renaming propagates normalized titles to the parent state", async () => {
  const renamed = vi.fn();
  render(<ThreadList onRenameSuccess={renamed} />);
  fireEvent.click(screen.getByRole("button", { name: "chat.threadList.rename" }));
  fireEvent.change(screen.getByRole("textbox"), { target: { value: " New title " } });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "common.save" })); });
  expect(fixture.rename).toHaveBeenCalledWith("New title");
  expect(renamed).toHaveBeenCalledWith("saved", "42", "New title");
});
test("[CHAT-SIDEBAR-D1-001] batch deletion resolves server IDs and resets the deleted active conversation", async () => {
  fixture.items = [{ id: "saved", title: "Saved conversation" }, { id: "draft", title: "Unsent draft" }];
  const reset = vi.fn();
  render(<BatchSelectionProvider onNewConversation={reset} serverConversationIds={new Map([["saved", "42"]])}><BatchSidebarFooter /></BatchSelectionProvider>);
  fireEvent.click(screen.getByRole("button", { name: "chat.threadList.batchManage" }));
  fireEvent.click(screen.getByRole("button", { name: "chat.threadList.selectAll" }));
  fireEvent.click(screen.getByRole("button", { name: "chat.threadList.delete" }));
  await act(async () => { await fixture.confirm.mock.calls[0][0].onOk(); });
  expect(fixture.deleteBatch).toHaveBeenCalledWith([42]);
  expect(fixture.reload).toHaveBeenCalled();
  expect(reset).toHaveBeenCalledOnce();
});
