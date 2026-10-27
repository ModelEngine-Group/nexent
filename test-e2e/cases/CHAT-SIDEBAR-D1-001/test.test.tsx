// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

vi.mock("@/app/i18n", () => ({
  default: { t: (key: string) => key, language: "zh" },
}));
import React from "react";
import {
  act,
  cleanup,
  fireEvent,
  render as renderComponent,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  ThreadList,
  BatchSelectionProvider,
  BatchSidebarFooter,
} from "@/app/newchat/assistant-ui/thread-list";

const fixture = vi.hoisted(() => ({
  items: [] as Array<{
    id: string;
    remoteId?: string;
    title: string;
    custom?: { agentId?: number | string };
  }>,
  availableAgents: [] as Array<{
    agent_id: number;
    display_name: string;
    name: string;
  }>,
  agentConversationIds: {} as Record<number, string[]>,
  rename: vi.fn().mockResolvedValue(undefined),
  reload: vi.fn().mockResolvedValue(undefined),
  deleteBatch: vi.fn().mockResolvedValue({ failed_ids: [] }),
  getList: vi.fn(),
  getAgentGroups: vi.fn(),
  getAgentGroupConversations: vi.fn(),
  getAgentConversationIds: vi.fn(),
  getWorkbenchPins: vi.fn().mockResolvedValue({ items: [] }),
  confirm: vi.fn(),
  mainThreadId: "saved" as string | undefined,
}));

vi.mock("@assistant-ui/react", async () => {
  const React = await import("react");
  const Context = React.createContext(0);
  const Wrap = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  const Button = ({
    children,
    onSelect,
    ...props
  }: React.ButtonHTMLAttributes<HTMLButtonElement> & {
    onSelect?: () => void;
  }) => (
    <button {...props} onClick={onSelect ?? props.onClick}>
      {children}
    </button>
  );
  const getState = () => ({
    threads: {
      threadIds: fixture.items.map((item) => item.id),
      threadItems: fixture.items,
      mainThreadId: fixture.mainThreadId,
      isLoading: false,
      hasMore: false,
    },
    thread: { isRunning: false },
    threadListItem: { isRunning: false },
  });
  return {
    useAuiState: (select: (state: ReturnType<typeof getState>) => unknown) =>
      select(getState()),
    useAuiEvent: () => undefined,
    useAui: () => {
      const index = React.useContext(Context);
      const item = {
        getState: () => fixture.items[index],
        rename: fixture.rename,
        delete: vi.fn(),
      };
      return {
        threadListItem: Object.assign(() => item, item),
        threads: { reload: fixture.reload, switchToThread: vi.fn() },
      };
    },
    AuiIf: ({
      condition,
      children,
    }: {
      condition: (state: ReturnType<typeof getState>) => boolean;
      children: React.ReactNode;
    }) => (condition(getState()) ? children : null),
    ThreadListPrimitive: {
      Root: Wrap,
      LoadMore: Button,
      ItemByIndex: ({
        index,
        components,
      }: {
        index: number;
        components: { ThreadListItem: React.ComponentType };
      }) => (
        <Context.Provider value={index}>
          <components.ThreadListItem />
        </Context.Provider>
      ),
    },
    ThreadListItemPrimitive: { Root: Wrap, Trigger: Button },
    ThreadListItemMorePrimitive: {
      Root: Wrap,
      Trigger: Button,
      Content: Wrap,
      Item: Button,
    },
  };
});
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: { agent?: string }) =>
      key === "chat.threadList.selectAgentConversations"
        ? `${key} ${values?.agent}`
        : key,
  }),
}));
vi.mock("@/hooks/agent/usePublishedAgentList", () => ({
  usePublishedAgentList: () => ({
    availableMainAgents: fixture.availableAgents,
  }),
}));
vi.mock("@/hooks/useConfirmModal", () => ({
  useConfirmModal: () => ({ confirm: fixture.confirm }),
}));
vi.mock("@/services/conversationService", () => ({
  conversationService: {
    deleteBatch: fixture.deleteBatch,
    getList: fixture.getList,
    getAgentGroups: fixture.getAgentGroups,
    getAgentGroupConversations: fixture.getAgentGroupConversations,
    getAgentConversationIds: fixture.getAgentConversationIds,
    getWorkbenchPins: fixture.getWorkbenchPins,
  },
}));
vi.mock("@/app/newchat/adapter/conversation-thread-list-adapter", () => ({
  setPendingThreadOperationId: vi.fn(),
}));
vi.mock("@/app/newchat/adapter/thread-agent-registry", () => ({
  resolveThreadAgentId: (agentId?: string | number | null) =>
    agentId == null ? null : Number(agentId),
  useThreadAgentOverrides: () => ({}),
}));
vi.mock("@/components/ui/tooltip", () => {
  const Wrap = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  return { Tooltip: Wrap, TooltipTrigger: Wrap, TooltipContent: () => null };
});

const queryClients: QueryClient[] = [];
const render = (ui: React.ReactNode) => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  queryClients.push(client);
  return renderComponent(ui, {
    wrapper: ({ children }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
};

const agentId = (item: (typeof fixture.items)[number]) => {
  const value = item.custom?.agentId;
  return value === undefined || value === null ? null : Number(value);
};
const groupFor = (id: number) => {
  const agent = fixture.availableAgents.find((item) => item.agent_id === id);
  const agentRows = fixture.items.filter(
    (item) => item.remoteId && agentId(item) === id,
  );
  return {
    group_key: `agent:${id}`,
    agent_id: id,
    agent_name: agent?.display_name ?? agent?.name ?? `Agent ${id}`,
    agent_available: true,
    last_activity_time: Math.max(
      0,
      ...agentRows.map((item) => Number(item.remoteId)),
    ),
    matched_conversation: false,
  };
};
const configureHistory = () => {
  fixture.getAgentGroups.mockImplementation(
    async (
      params: {
        limit?: number;
        cursor?: string | null;
        search?: string;
        includeAgentIds?: readonly number[];
        includeOther?: boolean;
      } = {},
    ) => {
      const search = params.search?.trim().toLocaleLowerCase() ?? "";
      const groups = [
        ...new Set(
          fixture.items
            .filter((item) => item.remoteId)
            .map(agentId)
            .filter((id): id is number => id !== null),
        ),
      ]
        .map(groupFor)
        .filter((group) => {
          if (!search) return true;
          const nameMatches =
            group.agent_name?.toLocaleLowerCase().includes(search) ?? false;
          const titleMatches = fixture.items.some(
            (item) =>
              agentId(item) === group.agent_id &&
              item.title.toLocaleLowerCase().includes(search),
          );
          group.matched_conversation = titleMatches;
          return nameMatches || titleMatches;
        })
        .sort(
          (left, right) =>
            right.last_activity_time - left.last_activity_time ||
            (right.agent_id ?? -1) - (left.agent_id ?? -1),
        );
      const offset = params.cursor ? Number(params.cursor) : 0;
      const limit = params.limit ?? 10;
      const included = groups.filter(
        (group) =>
          params.includeAgentIds?.includes(group.agent_id ?? -1) ||
          (params.includeOther && group.agent_id === null),
      );
      return {
        items: groups.slice(offset, offset + limit),
        pinned_items: [],
        included_items: included,
        next_cursor:
          offset + limit < groups.length ? String(offset + limit) : null,
      };
    },
  );
  fixture.getAgentGroupConversations.mockImplementation(
    async (params: {
      groupKey: string;
      limit?: number;
      cursor?: string | null;
      search?: string;
    }) => {
      const id =
        params.groupKey === "other"
          ? null
          : Number(params.groupKey.slice("agent:".length));
      const search = params.search?.trim().toLocaleLowerCase() ?? "";
      const rows = fixture.items
        .filter(
          (item) =>
            item.remoteId &&
            agentId(item) === id &&
            item.title.toLocaleLowerCase().includes(search),
        )
        .map((item) => ({
          conversation_id: Number(item.remoteId),
          conversation_title: item.title,
          agent_id: id,
          create_time: Number(item.remoteId),
          update_time: Number(item.remoteId),
          last_activity_time: Number(item.remoteId),
          pinned_at: null,
        }));
      const offset = params.cursor ? Number(params.cursor) : 0;
      const limit = params.limit ?? 10;
      return {
        items: rows.slice(offset, offset + limit),
        pinned_items: [],
        next_cursor:
          offset + limit < rows.length ? String(offset + limit) : null,
      };
    },
  );
  fixture.getAgentConversationIds.mockImplementation(
    async (id: number) =>
      fixture.agentConversationIds[id] ??
      fixture.items
        .filter((item) => item.remoteId && agentId(item) === id)
        .map((item) => item.remoteId!),
  );
  fixture.getWorkbenchPins.mockResolvedValue({ items: [] });
};

afterEach(async () => {
  await act(async () => {
    cleanup();
    for (const client of queryClients) {
      await client.cancelQueries();
      client.clear();
    }
    queryClients.length = 0;
  });
  // Drain queued React scheduler work before jsdom is disposed.
  await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
});
beforeEach(() => {
  fixture.items = [
    {
      id: "saved",
      remoteId: "42",
      title: "Saved conversation",
      custom: { agentId: 7 },
    },
    { id: "draft", title: "Unsent draft", custom: { agentId: 7 } },
  ];
  fixture.availableAgents = [
    { agent_id: 7, display_name: "Agent Seven", name: "Agent Seven" },
  ];
  fixture.agentConversationIds = {};
  fixture.mainThreadId = "saved";
  fixture.rename.mockReset().mockResolvedValue(undefined);
  fixture.reload.mockReset().mockResolvedValue(undefined);
  fixture.deleteBatch.mockReset().mockResolvedValue({ failed_ids: [] });
  fixture.getList.mockReset().mockResolvedValue({
    items: [],
    metadata: { total: 0, today: 0, last_7_days: 0, older: 0 },
  });
  fixture.getAgentGroups.mockReset();
  fixture.getAgentGroupConversations.mockReset();
  fixture.getAgentConversationIds.mockReset();
  fixture.confirm.mockReset();
  configureHistory();
});

const renderAgentBatchList = (onNewConversation?: () => void) =>
  render(
    <BatchSelectionProvider
      conversationType="agent_chat"
      onNewConversation={onNewConversation}
    >
      <>
        <ThreadList newChatDesign />
        <BatchSidebarFooter />
      </>
    </BatchSelectionProvider>,
  );

test("[CHAT-SIDEBAR-D1-001] persisted conversations remain visible and unsent drafts stay hidden", () => {
  render(<ThreadList generatedTitles={new Map([["42", "Server title"]])} />);
  expect(screen.getByText("Server title")).toBeVisible();
  expect(screen.queryByText("Unsent draft")).toBeNull();
});

test("[CHAT-SIDEBAR-D1-001] renaming propagates normalized titles to the parent state", async () => {
  const renamed = vi.fn();
  render(<ThreadList onRenameSuccess={renamed} />);
  fireEvent.click(
    screen.getByRole("button", { name: "chat.threadList.rename" }),
  );
  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: " New title " },
  });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "common.save" }));
  });
  expect(fixture.rename).toHaveBeenCalledWith("New title");
  expect(renamed).toHaveBeenCalledWith("saved", "42", "New title");
});

test("[CHAT-SIDEBAR-D1-001] batch deletion resolves server IDs and resets the deleted active conversation", async () => {
  fixture.items = [
    { id: "saved", title: "Saved conversation" },
    { id: "draft", title: "Unsent draft" },
  ];
  const reset = vi.fn();
  render(
    <BatchSelectionProvider
      onNewConversation={reset}
      serverConversationIds={new Map([["saved", "42"]])}
    >
      <ThreadList serverConversationIds={new Map([["saved", "42"]])} />
      <BatchSidebarFooter />
    </BatchSelectionProvider>,
  );
  fireEvent.click(
    screen.getByRole("button", { name: "chat.threadList.batchManage" }),
  );
  fireEvent.click(
    screen.getByRole("checkbox", { name: "chat.threadList.selectAll" }),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "chat.threadList.delete" }),
  );
  await act(async () => {
    await fixture.confirm.mock.calls[0][0].onOk();
  });
  expect(fixture.deleteBatch).toHaveBeenCalledWith([42]);
  expect(fixture.reload).toHaveBeenCalled();
  expect(reset).toHaveBeenCalledOnce();
});

test("[CHAT-SIDEBAR-D1-001] selecting an Agent resolves and deletes all only that Agent's conversations", async () => {
  fixture.items = [
    {
      id: "agent-seven-1",
      remoteId: "1",
      title: "Agent seven recent",
      custom: { agentId: 7 },
    },
    {
      id: "agent-seven-2",
      remoteId: "101",
      title: "Agent seven older",
      custom: { agentId: 7 },
    },
    {
      id: "agent-eight-1",
      remoteId: "2",
      title: "Agent eight recent",
      custom: { agentId: 8 },
    },
    {
      id: "agent-eight-2",
      remoteId: "102",
      title: "Agent eight older",
      custom: { agentId: 8 },
    },
  ];
  fixture.availableAgents = [
    { agent_id: 7, display_name: "Agent Seven", name: "Agent Seven" },
    { agent_id: 8, display_name: "Agent Eight", name: "Agent Eight" },
  ];
  fixture.agentConversationIds = { 7: ["1", "101"], 8: ["2", "102"] };
  fixture.mainThreadId = "agent-seven-1";
  configureHistory();
  fixture.confirm.mockClear();
  const reset = vi.fn();
  renderAgentBatchList(reset);

  fireEvent.click(
    screen.getByRole("button", { name: "chat.threadList.batchManage" }),
  );
  await screen.findByRole("checkbox", {
    name: "chat.threadList.selectAgentConversations Agent Seven",
  });
  await act(async () => {
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "chat.threadList.selectAgentConversations Agent Seven",
      }),
    );
  });
  await waitFor(() =>
    expect(fixture.getAgentConversationIds).toHaveBeenCalledWith(7),
  );
  expect(screen.getByText("2/2")).toBeVisible();
  expect(screen.queryByText("Agent eight recent")).toBeNull();

  fireEvent.click(
    screen.getByRole("button", { name: "chat.threadList.delete" }),
  );
  await act(async () => {
    await fixture.confirm.mock.calls.at(-1)?.[0].onOk();
  });
  expect(fixture.deleteBatch).toHaveBeenCalledWith([1, 101]);
  expect(fixture.deleteBatch).not.toHaveBeenCalledWith(
    expect.arrayContaining([2, 102]),
  );
  expect(reset).toHaveBeenCalledOnce();
});

test("[CHAT-SIDEBAR-D1-001] Agent ID query failures do not partially select or delete conversations", async () => {
  fixture.items = [
    {
      id: "agent-seven-1",
      remoteId: "1",
      title: "Agent seven recent",
      custom: { agentId: 7 },
    },
    {
      id: "agent-eight-1",
      remoteId: "2",
      title: "Agent eight recent",
      custom: { agentId: 8 },
    },
  ];
  fixture.availableAgents = [
    { agent_id: 7, display_name: "Agent Seven", name: "Agent Seven" },
    { agent_id: 8, display_name: "Agent Eight", name: "Agent Eight" },
  ];
  configureHistory();
  fixture.getAgentConversationIds.mockRejectedValueOnce(
    new Error("ID query failed"),
  );
  fixture.confirm.mockClear();
  fixture.deleteBatch.mockClear();
  renderAgentBatchList();

  fireEvent.click(
    screen.getByRole("button", { name: "chat.threadList.batchManage" }),
  );
  const agentCheckbox = await screen.findByRole("checkbox", {
    name: "chat.threadList.selectAgentConversations Agent Seven",
  });
  await act(async () => {
    fireEvent.click(agentCheckbox);
  });
  await waitFor(() =>
    expect(fixture.getAgentConversationIds).toHaveBeenCalledWith(7),
  );
  expect(agentCheckbox).not.toBeChecked();
  expect(screen.queryByText("1/1")).toBeNull();
  expect(
    screen.getByRole("button", { name: "chat.threadList.delete" }),
  ).toBeDisabled();
  expect(fixture.confirm).not.toHaveBeenCalled();
  expect(fixture.deleteBatch).not.toHaveBeenCalled();
});

test("[CHAT-SIDEBAR-D1-001] server search expands matching Agent groups and preserves manual expansion", async () => {
  fixture.items = [
    {
      id: "saved",
      remoteId: "42",
      title: "Seven active",
      custom: { agentId: 7 },
    },
    {
      id: "seven-other",
      remoteId: "43",
      title: "Seven older",
      custom: { agentId: 7 },
    },
    {
      id: "eight-budget",
      remoteId: "44",
      title: "Quarterly budget",
      custom: { agentId: 8 },
    },
    {
      id: "eight-notes",
      remoteId: "45",
      title: "Eight notes",
      custom: { agentId: 8 },
    },
  ];
  fixture.availableAgents = [
    { agent_id: 7, display_name: "Agent Seven", name: "Agent Seven" },
    { agent_id: 8, display_name: "Agent Eight", name: "Agent Eight" },
  ];
  fixture.mainThreadId = "saved";
  configureHistory();
  const { rerender } = render(
    <ThreadList newChatDesign activeThreadId="saved" />,
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Agent Seven" })).toHaveAttribute(
      "aria-expanded",
      "true",
    ),
  );
  await waitFor(() => expect(screen.getByText("Seven older")).toBeVisible());
  expect(screen.queryByText("Quarterly budget")).toBeNull();

  rerender(
    <ThreadList newChatDesign activeThreadId="saved" searchQuery=" budget " />,
  );
  await waitFor(() =>
    expect(screen.getByText("Quarterly budget")).toBeVisible(),
  );
  expect(screen.getByRole("button", { name: "Agent Eight" })).toHaveAttribute(
    "aria-expanded",
    "true",
  );
  expect(screen.queryByText("Eight notes")).toBeNull();

  for (let attempt = 0; attempt < 3; attempt += 1) {
    fireEvent.click(screen.getByRole("button", { name: "Agent Eight" }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Agent Eight" }),
      ).toHaveAttribute("aria-expanded", "false"),
    );
    expect(screen.queryByText("Quarterly budget")).toBeNull();
    rerender(
      <ThreadList
        newChatDesign
        activeThreadId="saved"
        searchQuery="Agent Eight"
      />,
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Agent Eight" }),
      ).toHaveAttribute("aria-expanded", "false"),
    );
    rerender(
      <ThreadList
        newChatDesign
        activeThreadId="saved"
        searchQuery=" budget "
      />,
    );
    await waitFor(() =>
      expect(screen.getByText("Quarterly budget")).toBeVisible(),
    );
    expect(screen.getByRole("button", { name: "Agent Eight" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  }

  fireEvent.click(screen.getByRole("button", { name: "Agent Eight" }));
  await waitFor(() =>
    expect(screen.queryByText("Quarterly budget")).toBeNull(),
  );
  rerender(<ThreadList newChatDesign activeThreadId="saved" searchQuery="" />);
  rerender(
    <ThreadList newChatDesign activeThreadId="saved" searchQuery=" budget " />,
  );
  expect(await screen.findByText("Quarterly budget")).toBeVisible();

  rerender(
    <ThreadList
      newChatDesign
      activeThreadId="saved"
      searchQuery="Agent Eight"
    />,
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Agent Eight" })).toHaveAttribute(
      "aria-expanded",
      "false",
    ),
  );
  expect(screen.queryByText("Quarterly budget")).toBeNull();
  expect(screen.queryByText("Eight notes")).toBeNull();
  rerender(
    <ThreadList newChatDesign activeThreadId="saved" searchQuery="eight" />,
  );
  await waitFor(() => expect(screen.getByText("Eight notes")).toBeVisible());
  rerender(
    <ThreadList
      newChatDesign
      activeThreadId="saved"
      searchQuery="no matching history"
    />,
  );
  expect(
    await screen.findByText("chat.threadList.noSearchResults"),
  ).toBeVisible();

  for (const query of ["", "   "]) {
    rerender(
      <ThreadList newChatDesign activeThreadId="saved" searchQuery={query} />,
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Agent Seven" }),
      ).toHaveAttribute("aria-expanded", "true"),
    );
    expect(screen.getByRole("button", { name: "Agent Eight" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.getByText("Seven older")).toBeVisible();
    expect(screen.queryByText("Quarterly budget")).toBeNull();
  }

  rerender(
    <ThreadList newChatDesign selectedAgentId={8} searchQuery="Agent Eight" />,
  );
  expect(
    await screen.findByText("chat.threadList.noSearchResults"),
  ).toBeVisible();
  rerender(
    <ThreadList newChatDesign selectedAgentId={8} searchQuery="budget" />,
  );
  expect(await screen.findByText("Quarterly budget")).toBeVisible();
  expect(screen.queryByText("Eight notes")).toBeNull();
  rerender(<ThreadList newChatDesign selectedAgentId={8} searchQuery="" />);
  expect(await screen.findByText("Quarterly budget")).toBeVisible();
  expect(screen.getByText("Eight notes")).toBeVisible();
  expect(screen.queryByText("Seven active")).toBeNull();
  expect(fixture.rename).not.toHaveBeenCalled();
  expect(fixture.deleteBatch).not.toHaveBeenCalled();
});
