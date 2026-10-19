// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

vi.mock("@/app/i18n", () => ({ default: { t: (key: string) => key, language: "zh" } }));
import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { ThreadList, BatchSelectionProvider, BatchSidebarFooter } from "@/app/newchat/assistant-ui/thread-list";
const fixture = vi.hoisted(() => ({
  items: [{ id: "saved", remoteId: "42", title: "Saved conversation", custom: { agentId: 7 } }, { id: "draft", title: "Unsent draft", custom: { agentId: 7 } }],
  availableAgents: [{ agent_id: 7, display_name: "Agent Seven", name: "Agent Seven" }],
  rename: vi.fn().mockResolvedValue(undefined),
  reload: vi.fn().mockResolvedValue(undefined),
  deleteBatch: vi.fn().mockResolvedValue({ failed_ids: [] }),
  getList: vi.fn(),
  confirm: vi.fn(),
  mainThreadId: "saved",
}));
vi.mock("@assistant-ui/react", async () => {
  const React = await import("react");
  const Context = React.createContext(0);
  const Wrap = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  const Button = ({ children, onSelect, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { onSelect?: () => void }) => <button {...props} onClick={onSelect ?? props.onClick}>{children}</button>;
  const getState = () => ({ threads: { threadIds: fixture.items.map(i => i.id), threadItems: fixture.items, mainThreadId: fixture.mainThreadId, isLoading: false, hasMore: false }, thread: { isRunning: false }, threadListItem: { isRunning: false } });
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
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string, values?: { agent?: string }) => key === "chat.threadList.selectAgentConversations" ? `${key} ${values?.agent}` : key }) }));
vi.mock("@/hooks/agent/usePublishedAgentList", () => ({ usePublishedAgentList: () => ({ availableMainAgents: fixture.availableAgents }) }));
vi.mock("@/hooks/useConfirmModal", () => ({ useConfirmModal: () => ({ confirm: fixture.confirm }) }));
vi.mock("@/services/conversationService", () => ({ conversationService: { deleteBatch: fixture.deleteBatch, getList: fixture.getList } }));
vi.mock("@/app/newchat/adapter/conversation-thread-list-adapter", () => ({ setPendingThreadOperationId: vi.fn() }));
vi.mock("@/app/newchat/adapter/thread-agent-registry", () => ({ resolveThreadAgentId: (agentId?: string | number | null) => agentId == null ? null : Number(agentId), useThreadAgentOverrides: () => ({}) }));
vi.mock("@/components/ui/tooltip", () => {
  const Wrap = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  return { Tooltip: Wrap, TooltipTrigger: Wrap, TooltipContent: () => null };
});
beforeEach(() => { fixture.items = [{ id: "saved", remoteId: "42", title: "Saved conversation", custom: { agentId: 7 } }, { id: "draft", title: "Unsent draft", custom: { agentId: 7 } }]; fixture.mainThreadId = "saved"; });

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
  render(<BatchSelectionProvider onNewConversation={reset} serverConversationIds={new Map([["saved", "42"]])}><ThreadList serverConversationIds={new Map([["saved", "42"]])} /><BatchSidebarFooter /></BatchSelectionProvider>);
  fireEvent.click(screen.getByRole("button", { name: "chat.threadList.batchManage" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "chat.threadList.selectAll" }));
  fireEvent.click(screen.getByRole("button", { name: "chat.threadList.delete" }));
  await act(async () => { await fixture.confirm.mock.calls[0][0].onOk(); });
  expect(fixture.deleteBatch).toHaveBeenCalledWith([42]);
  expect(fixture.reload).toHaveBeenCalled();
  expect(reset).toHaveBeenCalledOnce();
});

const apiConversation = (conversationId: number, agentId: number) => ({
  conversation_id: conversationId,
  conversation_title: `Conversation ${conversationId}`,
  agent_id: agentId,
  create_time: 0,
  update_time: 0,
});

const renderAgentBatchList = (onNewConversation?: () => void) => render(
  <BatchSelectionProvider conversationType="agent_chat" onNewConversation={onNewConversation}>
    <>
      <ThreadList newChatDesign />
      <BatchSidebarFooter />
    </>
  </BatchSelectionProvider>
);

test("[CHAT-SIDEBAR-D1-001] selecting an agent group loads all pages and deletes only its conversations", async () => {
  fixture.items = [
    { id: "agent-seven-1", remoteId: "1", title: "Agent seven conversation", custom: { agentId: 7 } },
    { id: "agent-eight-1", remoteId: "2", title: "Agent eight conversation", custom: { agentId: 8 } },
  ];
  fixture.availableAgents = [
    { agent_id: 7, display_name: "Agent Seven", name: "Agent Seven" },
    { agent_id: 8, display_name: "Agent Eight", name: "Agent Eight" },
  ];
  fixture.mainThreadId = "agent-seven-1";
  fixture.getList.mockReset();
  fixture.confirm.mockClear();
  fixture.deleteBatch.mockClear();
  fixture.getList
    .mockResolvedValueOnce({
      items: Array.from({ length: 100 }, (_, index) => apiConversation(index + 1, index === 0 ? 7 : 8)),
      metadata: { total: 102, today: 0, last_7_days: 0, older: 102 },
    })
    .mockResolvedValueOnce({
      items: [apiConversation(101, 7), apiConversation(102, 8)],
      metadata: { total: 102, today: 0, last_7_days: 0, older: 102 },
    });
  const reset = vi.fn();
  renderAgentBatchList(reset);

  fireEvent.click(screen.getByRole("button", { name: "chat.threadList.batchManage" }));
  await act(async () => {
    fireEvent.click(screen.getByRole("checkbox", { name: "chat.threadList.selectAgentConversations Agent Seven" }));
  });
  expect(fixture.getList).toHaveBeenNthCalledWith(1, expect.objectContaining({ offset: 0, limit: 100, conversationType: "agent_chat" }));
  expect(fixture.getList).toHaveBeenNthCalledWith(2, expect.objectContaining({ offset: 100, limit: 100, conversationType: "agent_chat" }));
  expect(screen.getByText("2/2")).toBeVisible();

  fireEvent.click(screen.getByRole("button", { name: "chat.threadList.delete" }));
  await act(async () => { await fixture.confirm.mock.calls.at(-1)?.[0].onOk(); });
  expect(fixture.deleteBatch).toHaveBeenCalledWith([1, 101]);
  expect(fixture.deleteBatch).not.toHaveBeenCalledWith(expect.arrayContaining([2, 102]));
  expect(reset).toHaveBeenCalledOnce();
});

test("[CHAT-SIDEBAR-D1-001] agent-group page failures do not partially select or delete conversations", async () => {
  fixture.items = [
    { id: "agent-seven-1", remoteId: "1", title: "Agent seven conversation", custom: { agentId: 7 } },
    { id: "agent-eight-1", remoteId: "2", title: "Agent eight conversation", custom: { agentId: 8 } },
  ];
  fixture.availableAgents = [
    { agent_id: 7, display_name: "Agent Seven", name: "Agent Seven" },
    { agent_id: 8, display_name: "Agent Eight", name: "Agent Eight" },
  ];
  fixture.getList.mockReset();
  fixture.confirm.mockClear();
  fixture.deleteBatch.mockClear();
  fixture.getList
    .mockResolvedValueOnce({
      items: Array.from({ length: 100 }, (_, index) => apiConversation(index + 1, index === 0 ? 7 : 8)),
      metadata: { total: 101, today: 0, last_7_days: 0, older: 101 },
    })
    .mockRejectedValueOnce(new Error("page failed"));
  renderAgentBatchList();

  fireEvent.click(screen.getByRole("button", { name: "chat.threadList.batchManage" }));
  await act(async () => {
    fireEvent.click(screen.getByRole("checkbox", { name: "chat.threadList.selectAgentConversations Agent Seven" }));
  });
  expect(screen.getByRole("checkbox", { name: "chat.threadList.selectAgentConversations Agent Seven" })).not.toBeChecked();
  expect(screen.queryByText("1/1")).toBeNull();
  expect(screen.getByRole("button", { name: "chat.threadList.delete" })).toBeDisabled();
  expect(fixture.confirm).not.toHaveBeenCalled();
  expect(fixture.deleteBatch).not.toHaveBeenCalled();
});
