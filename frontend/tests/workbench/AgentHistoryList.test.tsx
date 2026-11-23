// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import {
  AgentHistoryList,
  AgentHistoryViewport,
} from "@/app/newchat/assistant-ui/agent-history-list";
import { conversationService } from "@/services/conversationService";
import agentChatStyles from "@/app/newchat/agent-chat.module.css";

const state = vi.hoisted(() => ({
  threadItems: [] as Array<{
    id: string;
    remoteId?: string;
    title?: string;
    custom?: { agentId?: number | string; lastMessageAt?: string | number };
  }>,
  mainThreadId: undefined as string | undefined,
  serverPinsRevision: 1,
  serverPins: [] as Array<{
    conversation_id: number;
    conversation_title: string;
    agent_id: number | null;
    create_time: number;
    update_time: number;
    pinned_at: string;
    conversation_type: "agent_chat";
  }>,
}));

vi.mock("@assistant-ui/react", () => ({
  useAui: () => ({ threads: { switchToThread: vi.fn() } }),
  useAuiEvent: () => undefined,
  useAuiState: (selector: (value: unknown) => unknown) =>
    selector({
      threads: {
        threadItems: state.threadItems,
        mainThreadId: state.mainThreadId,
      },
      thread: { isRunning: false },
    }),
}));

vi.mock("@/hooks/useConfirmModal", () => ({
  useConfirmModal: () => ({ confirm: vi.fn() }),
}));

vi.mock("@/app/newchat/assistant-ui/thread-pins", () => ({
  usePinnedThreads: () => ({
    serverPins: state.serverPins,
    serverPinsRevision: state.serverPinsRevision,
    canPin: () => true,
    isPinned: () => false,
    togglePin: vi.fn(),
  }),
}));

vi.mock("@/app/newchat/adapter/thread-agent-registry", () => ({
  resolveThreadAgentId: (agentId?: string | number | null) =>
    agentId == null ? null : Number(agentId),
  useThreadAgentOverrides: () => ({}),
}));

vi.mock("react-i18next", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-i18next")>();
  return { ...actual, useTranslation: () => ({ t: (key: string) => key }) };
});

const agentGroups = {
  items: [
    {
      group_key: "agent:7",
      agent_id: 7,
      agent_name: "Agent Seven",
      agent_available: true,
      last_activity_time: 0,
      matched_conversation: false,
    },
  ],
  pinned_items: [],
  included_items: [],
  next_cursor: null,
};

const conversation = (id: number) => ({
  conversation_id: id,
  conversation_title: `History ${id}`,
  agent_id: 7,
  create_time: id,
  update_time: id,
  last_activity_time: id,
});

const queryClients: QueryClient[] = [];

afterEach(async () => {
  state.threadItems = [];
  state.mainThreadId = undefined;
  state.serverPins = [];
  state.serverPinsRevision = 1;
  const clients = queryClients.splice(0);
  await Promise.all(clients.map((client) => client.cancelQueries()));
  clients.forEach((client) => client.clear());
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function renderHistory(selectedAgentId?: number) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  queryClients.push(client);
  return render(
    <QueryClientProvider client={client}>
      <AgentHistoryViewport enabled={selectedAgentId === undefined}>
        <AgentHistoryList searchQuery="" selectedAgentId={selectedAgentId} />
      </AgentHistoryViewport>
    </QueryClientProvider>
  );
}

it("shows animated skeleton rows without visible loading copy", async () => {
  let resolveConversations!: (value: {
    items: ReturnType<typeof conversation>[];
    pinned_items: [];
    next_cursor: null;
  }) => void;
  vi.spyOn(conversationService, "getAgentGroups").mockResolvedValue(
    agentGroups
  );
  vi.spyOn(conversationService, "getAgentGroupConversations").mockReturnValue(
    new Promise((resolve) => {
      resolveConversations = resolve;
    })
  );

  renderHistory();
  fireEvent.click(await screen.findByRole("button", { name: "Agent Seven" }));

  const status = await screen.findByRole("status", {
    name: "chat.threadList.loading",
  });
  expect(status.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  expect(screen.queryByText("chat.threadList.loading")).toBeNull();

  await act(async () => {
    resolveConversations({
      items: [conversation(1)],
      pinned_items: [],
      next_cursor: null,
    });
  });
  expect(await screen.findByText("History 1")).toBeVisible();
});

it("skips the skeleton for a fast Agent history request and animates its height", async () => {
  vi.spyOn(conversationService, "getAgentGroups").mockResolvedValue(
    agentGroups
  );
  vi.spyOn(conversationService, "getAgentGroupConversations").mockResolvedValue(
    {
      items: [conversation(1)],
      pinned_items: [],
      next_cursor: null,
    }
  );

  renderHistory();
  fireEvent.click(await screen.findByRole("button", { name: "Agent Seven" }));
  expect(await screen.findByText("History 1")).toBeVisible();

  expect(
    screen.queryByRole("status", { name: "chat.threadList.loading" })
  ).toBeNull();
  const viewport = screen.getByTestId("agent-history-conversation-viewport");
  expect(viewport).toHaveStyle({ height: "40px" });
  expect(viewport).toHaveStyle({ transition: "height 180ms ease-out" });
});

it("uses the remaining sidebar height for a selected Agent history", async () => {
  vi.spyOn(conversationService, "getAgentGroups").mockResolvedValue(
    agentGroups
  );
  vi.spyOn(conversationService, "getAgentGroupConversations").mockResolvedValue(
    {
      items: [conversation(1)],
      pinned_items: [],
      next_cursor: null,
    }
  );

  renderHistory(7);
  expect(await screen.findByText("History 1")).toBeVisible();
  expect(screen.queryByTestId("agent-history-group-viewport")).toBeNull();

  const viewport = screen.getByTestId("agent-history-conversation-viewport");
  expect(viewport).toHaveClass("h-full", "min-h-0", "flex-1", "max-h-none");
  expect(viewport).toHaveStyle({ height: "100%" });
  expect(viewport.parentElement).toHaveClass("min-h-0", "flex-1");
  expect(viewport.parentElement?.parentElement).toHaveClass(
    "h-full",
    "min-h-0",
    "flex-1"
  );
});

it("fills a selected Agent viewport until it has enough history to scroll", async () => {
  let resolveFirstPage!: (
    value: Awaited<
      ReturnType<typeof conversationService.getAgentGroupConversations>
    >
  ) => void;
  const getConversations = vi
    .spyOn(conversationService, "getAgentGroupConversations")
    .mockImplementation(({ cursor }) => {
      if (!cursor) {
        return new Promise((resolve) => {
          resolveFirstPage = resolve;
        });
      }
      const offset = Number(cursor);
      return Promise.resolve({
        items: Array.from({ length: 10 }, (_, index) =>
          conversation(offset + index + 1)
        ),
        pinned_items: [],
        next_cursor: String(offset + 10),
      });
    });

  renderHistory(7);
  await waitFor(() => expect(getConversations).toHaveBeenCalledTimes(1));
  const viewport = screen.getByTestId("agent-history-conversation-viewport");
  Object.defineProperties(viewport, {
    clientHeight: { configurable: true, value: 500 },
    scrollHeight: {
      configurable: true,
      get: () =>
        viewport.querySelectorAll('button[title^="History"]').length * 40,
    },
  });

  await act(async () => {
    resolveFirstPage({
      items: Array.from({ length: 10 }, (_, index) => conversation(index + 1)),
      pinned_items: [],
      next_cursor: "10",
    });
  });

  await waitFor(() => expect(getConversations).toHaveBeenCalledTimes(2));
  expect(await screen.findByText("History 20")).toBeVisible();
  expect(getConversations).toHaveBeenNthCalledWith(
    2,
    expect.objectContaining({ groupKey: "agent:7", limit: 10, cursor: "10" })
  );
});

it("expands the active Agent group so its selected conversation stays in the group", async () => {
  state.threadItems = [
    {
      id: "active-thread",
      remoteId: "501",
      title: "Current conversation",
      custom: { agentId: 7, lastMessageAt: 100 },
    },
  ];
  state.mainThreadId = "active-thread";
  vi.spyOn(conversationService, "getAgentGroups").mockResolvedValue(
    agentGroups
  );
  vi.spyOn(conversationService, "getAgentGroupConversations").mockResolvedValue(
    {
      items: [conversation(502)],
      pinned_items: [],
      next_cursor: null,
    }
  );

  renderHistory();

  const group = await screen.findByRole("button", { name: "Agent Seven" });
  await waitFor(() => expect(group).toHaveAttribute("aria-expanded", "true"));
  expect(group).toHaveAttribute("title", "Agent Seven");
  const currentConversation = await screen.findByText("Current conversation");
  expect(currentConversation).toBeVisible();
  expect(currentConversation.closest("button")).toHaveAttribute(
    "title",
    "Current conversation"
  );
  expect(await screen.findByText("History 502")).toBeVisible();

  fireEvent.click(group);
  await waitFor(() => expect(group).toHaveAttribute("aria-expanded", "false"));
  expect(screen.queryByText("Current conversation")).toBeNull();
  fireEvent.click(group);
  await waitFor(() => expect(group).toHaveAttribute("aria-expanded", "true"));
  expect(await screen.findByText("Current conversation")).toBeVisible();
});

it("keeps an active out-of-page Agent group in place when loading more groups", async () => {
  const group = (id: number, name: string, activity: number) => ({
    group_key: `agent:${id}`,
    agent_id: id,
    agent_name: name,
    agent_available: true,
    last_activity_time: activity,
    matched_conversation: false,
  });
  const activeGroup = group(999, "xxxxx", 1);
  const getGroups = vi
    .spyOn(conversationService, "getAgentGroups")
    .mockImplementation(async (params = {}) => {
      const { cursor, includeAgentIds } = params;
      if (includeAgentIds?.includes(999)) {
        return {
          items: [],
          pinned_items: [],
          included_items: [activeGroup],
          next_cursor: null,
        };
      }
      return cursor
        ? {
            items: Array.from({ length: 10 }, (_, index) =>
              group(
                index + 11,
                `Agent ${String(index + 11).padStart(2, "0")}`,
                90 - index
              )
            ),
            pinned_items: [],
            included_items: [],
            next_cursor: null,
          }
        : {
            items: Array.from({ length: 10 }, (_, index) =>
              group(
                index + 1,
                `Agent ${String(index + 1).padStart(2, "0")}`,
                100 - index
              )
            ),
            pinned_items: [],
            included_items: [],
            next_cursor: "page-2",
          };
    });
  state.threadItems = [
    {
      id: "active-thread",
      remoteId: "9999",
      title: "Active conversation",
      custom: { agentId: 999 },
    },
  ];
  state.mainThreadId = "active-thread";
  vi.spyOn(conversationService, "getAgentGroupConversations").mockResolvedValue(
    {
      items: [],
      pinned_items: [],
      next_cursor: null,
    }
  );

  renderHistory();
  const readGroupOrder = () =>
    Array.from(
      document.querySelectorAll<HTMLButtonElement>(
        'button[data-slot="aui_thread-list-group-label"]'
      )
    ).map((button) => button.textContent?.trim());
  const firstGroup = await screen.findByRole("button", { name: "Agent 01" });
  const [agentIcon, toggleIcon] = firstGroup.querySelectorAll("svg");
  expect(agentIcon).toHaveClass("size-5");
  expect(firstGroup).toHaveClass("gap-5", "px-0");
  expect(toggleIcon).toHaveClass(
    "w-0",
    "opacity-0",
    "group-hover:opacity-100",
    "group-focus-visible:opacity-100"
  );
  const firstPageOrder = readGroupOrder();
  expect(firstPageOrder).toHaveLength(11);
  expect(firstPageOrder[10]).toBe("xxxxx");

  const viewport = firstGroup.closest("[data-agent-history-group-viewport]")!;
  Object.defineProperties(viewport, {
    clientHeight: { configurable: true, value: 400 },
    scrollHeight: { configurable: true, value: 800 },
    scrollTop: { configurable: true, value: 340 },
  });
  fireEvent.scroll(viewport);
  await waitFor(() => expect(readGroupOrder()).toHaveLength(21));

  const loadedOrder = readGroupOrder();
  expect(loadedOrder.slice(0, 11)).toEqual(firstPageOrder);
  expect(loadedOrder[11]).toBe("Agent 11");
  expect(getGroups).toHaveBeenCalledTimes(3);
});

it("loads Agent groups on outer scroll only and stops requesting at the end", async () => {
  let resolveNext!: (value: typeof agentGroups) => void;
  const getGroups = vi
    .spyOn(conversationService, "getAgentGroups")
    .mockResolvedValueOnce({ ...agentGroups, next_cursor: "next" })
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveNext = resolve;
        })
    );
  renderHistory();
  const first = await screen.findByRole("button", { name: "Agent Seven" });
  const viewport = first.closest("[data-agent-history-group-viewport]")!;
  Object.defineProperties(viewport, {
    clientHeight: { configurable: true, value: 400 },
    scrollHeight: { configurable: true, value: 800 },
    scrollTop: { configurable: true, value: 340 },
  });
  expect(
    screen.queryByRole("button", { name: "chat.threadList.loadMoreAgents" })
  ).toBeNull();
  fireEvent.scroll(screen.getByTestId("agent-history-conversation-viewport"), {
    bubbles: true,
  });
  expect(getGroups).toHaveBeenCalledTimes(1);
  fireEvent.scroll(viewport);
  fireEvent.scroll(viewport);
  await waitFor(() => expect(getGroups).toHaveBeenCalledTimes(2));
  expect(
    screen.getByRole("status", { name: "chat.threadList.loadingMore" })
  ).toBeVisible();
  await act(async () =>
    resolveNext({
      ...agentGroups,
      items: [
        {
          ...agentGroups.items[0],
          group_key: "agent:8",
          agent_id: 8,
          agent_name: "Agent Eight",
        },
      ],
    })
  );
  expect(
    await screen.findByRole("button", { name: "Agent Eight" })
  ).toBeVisible();
  expect(screen.getByText("chat.threadList.noMoreAgents")).toBeVisible();
  fireEvent.scroll(viewport);
  expect(getGroups).toHaveBeenCalledTimes(2);
  await waitFor(
    () => expect(screen.queryByText("chat.threadList.noMoreAgents")).toBeNull(),
    { timeout: 1600 }
  );
  fireEvent.scroll(viewport);
  expect(screen.queryByText("chat.threadList.noMoreAgents")).toBeNull();
  expect(getGroups).toHaveBeenCalledTimes(2);
});

it("retains Agent groups on a failed next page and retries only on request", async () => {
  const getGroups = vi
    .spyOn(conversationService, "getAgentGroups")
    .mockResolvedValueOnce({ ...agentGroups, next_cursor: "next" })
    .mockRejectedValueOnce(new Error("Unavailable"))
    .mockResolvedValueOnce({
      ...agentGroups,
      items: [
        {
          ...agentGroups.items[0],
          group_key: "agent:8",
          agent_id: 8,
          agent_name: "Agent Eight",
        },
      ],
    });
  renderHistory();
  const first = await screen.findByRole("button", { name: "Agent Seven" });
  const viewport = first.closest("[data-agent-history-group-viewport]")!;
  Object.defineProperties(viewport, {
    clientHeight: { configurable: true, value: 400 },
    scrollHeight: { configurable: true, value: 800 },
    scrollTop: { configurable: true, value: 340 },
  });
  fireEvent.scroll(viewport);
  const retry = await screen.findByRole("button", {
    name: "chat.threadList.retry",
  });
  expect(first).toBeVisible();
  fireEvent.scroll(viewport);
  expect(getGroups).toHaveBeenCalledTimes(2);
  fireEvent.click(retry);
  expect(
    await screen.findByRole("button", { name: "Agent Eight" })
  ).toBeVisible();
  expect(getGroups).toHaveBeenCalledTimes(3);
});

it("shows outer shadows only where Agent groups overflow the viewport", async () => {
  vi.spyOn(conversationService, "getAgentGroups").mockResolvedValue(
    agentGroups
  );
  renderHistory();
  await screen.findByRole("button", { name: "Agent Seven" });
  const viewport = screen.getByTestId("agent-history-group-viewport");
  Object.defineProperties(viewport, {
    clientHeight: { configurable: true, value: 100 },
    scrollHeight: { configurable: true, value: 300 },
    scrollTop: { configurable: true, value: 0 },
  });
  fireEvent.scroll(viewport);
  expect(screen.queryByTestId("agent-history-group-shadow-top")).toBeNull();
  expect(screen.getByTestId("agent-history-group-shadow-bottom")).toBeVisible();
  Object.defineProperty(viewport, "scrollTop", {
    configurable: true,
    value: 100,
  });
  fireEvent.scroll(viewport);
  expect(screen.getByTestId("agent-history-group-shadow-top")).toBeVisible();
  expect(screen.getByTestId("agent-history-group-shadow-bottom")).toBeVisible();
  Object.defineProperty(viewport, "scrollTop", {
    configurable: true,
    value: 200,
  });
  fireEvent.scroll(viewport);
  expect(screen.queryByTestId("agent-history-group-shadow-bottom")).toBeNull();
  Object.defineProperties(viewport, {
    scrollTop: { configurable: true, value: 0 },
    scrollHeight: { configurable: true, value: 100 },
  });
  fireEvent.scroll(viewport);
  expect(screen.queryByTestId("agent-history-group-shadow-top")).toBeNull();
  expect(screen.queryByTestId("agent-history-group-shadow-bottom")).toBeNull();
});

it("refreshes history only when the pin snapshot changes, not when it is polled", async () => {
  const getGroups = vi
    .spyOn(conversationService, "getAgentGroups")
    .mockResolvedValue(agentGroups);
  const view = renderHistory();
  await screen.findByRole("button", { name: "Agent Seven" });
  expect(getGroups).toHaveBeenCalledTimes(1);
  const client = queryClients.at(-1)!;
  const renderAgain = () =>
    view.rerender(
      <QueryClientProvider client={client}>
        <AgentHistoryViewport>
          <AgentHistoryList searchQuery="" />
        </AgentHistoryViewport>
      </QueryClientProvider>
    );
  state.serverPins = [];
  state.serverPinsRevision += 1;
  renderAgain();
  expect(getGroups).toHaveBeenCalledTimes(1);
  state.serverPins = [
    {
      ...conversation(1),
      pinned_at: "2026-10-27T00:00:00Z",
      conversation_type: "agent_chat",
    },
  ];
  renderAgain();
  await waitFor(() => expect(getGroups).toHaveBeenCalledTimes(2));
});

it("puts an Agent group with pinned conversations before other groups", async () => {
  const pinnedGroup = {
    group_key: "agent:999",
    agent_id: 999,
    agent_name: "Pinned Agent",
    agent_available: true,
    last_activity_time: 1,
    matched_conversation: false,
  };
  const activeGroup = {
    group_key: "agent:7",
    agent_id: 7,
    agent_name: "Agent Seven",
    agent_available: true,
    last_activity_time: 100,
    matched_conversation: false,
  };
  state.serverPins = [
    {
      conversation_id: 901,
      conversation_title: "Pinned history",
      agent_id: 999,
      create_time: 1,
      update_time: 1,
      pinned_at: "2026-10-26T00:00:00Z",
      conversation_type: "agent_chat",
    },
  ];
  vi.spyOn(conversationService, "getAgentGroups").mockResolvedValue({
    items: [activeGroup],
    pinned_items: [pinnedGroup],
    included_items: [],
    next_cursor: null,
  });

  renderHistory();

  const groupOrder = await screen.findAllByRole("button", {
    name: /Agent|Pinned Agent/,
  });
  expect(groupOrder[0]).toHaveAccessibleName("Pinned Agent");
  expect(groupOrder[1]).toHaveAccessibleName("Agent Seven");
});

it("pages more than 100 conversations independently inside one Agent group", async () => {
  vi.spyOn(conversationService, "getAgentGroups").mockResolvedValue(
    agentGroups
  );
  const getConversations = vi
    .spyOn(conversationService, "getAgentGroupConversations")
    .mockImplementation(async ({ cursor }) => {
      const offset = cursor ? Number(cursor) : 0;
      const rows = Array.from(
        { length: Math.min(10, 101 - offset) },
        (_, index) => conversation(offset + index + 1)
      );
      const next = offset + rows.length;
      return {
        items: rows,
        pinned_items: [],
        next_cursor: next < 101 ? String(next) : null,
      };
    });

  renderHistory();
  fireEvent.click(await screen.findByRole("button", { name: "Agent Seven" }));
  await screen.findByText("History 10");
  expect(screen.queryByText("History 11")).toBeNull();
  const viewport = screen.getByTestId("agent-history-conversation-viewport");
  expect(viewport).toHaveClass(
    agentChatStyles.scrollArea,
    "overflow-y-auto",
    "max-h-[320px]",
    "overscroll-contain"
  );
  expect(viewport.parentElement).toHaveClass("mr-[2px]");
  expect(viewport).toHaveStyle({ width: "100%" });
  expect(screen.queryByTestId("agent-history-floating-scrollbar")).toBeNull();
  expect(screen.queryByTestId("agent-history-scroll-shadow-top")).toBeNull();
  expect(
    screen.getByTestId("agent-history-scroll-shadow-bottom")
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "chat.threadList.loadMore" })
  ).toBeNull();
  Object.defineProperties(viewport, {
    scrollHeight: { configurable: true, value: 600 },
    clientHeight: { configurable: true, value: 320 },
    scrollTop: { configurable: true, value: 0 },
    offsetWidth: { configurable: true, value: 260 },
    clientWidth: { configurable: true, value: 250 },
  });
  fireEvent.scroll(viewport);
  expect(viewport).toHaveAttribute("data-agent-history-scrolling", "true");
  expect(viewport).toHaveStyle({ width: "100%" });
  Object.defineProperty(viewport, "scrollTop", {
    configurable: true,
    value: 220,
  });

  for (let page = 1; page < 11; page += 1) {
    if (page > 1) {
      Object.defineProperty(viewport, "scrollTop", {
        configurable: true,
        value: 0,
      });
      fireEvent.scroll(viewport);
      Object.defineProperty(viewport, "scrollTop", {
        configurable: true,
        value: 220,
      });
    }
    fireEvent.scroll(viewport);
    await waitFor(() =>
      expect(
        screen.getByText(`History ${Math.min((page + 1) * 10, 101)}`)
      ).toBeVisible()
    );
    if (page === 1) {
      expect(
        screen.getByTestId("agent-history-scroll-shadow-top")
      ).toBeVisible();
      expect(
        screen.getByTestId("agent-history-scroll-shadow-bottom")
      ).toBeVisible();
      fireEvent.scroll(viewport);
      expect(getConversations).toHaveBeenCalledTimes(2);
    }
  }

  expect(screen.getByText("History 101")).toBeVisible();
  expect(getConversations).toHaveBeenCalledTimes(11);
  expect(getConversations).toHaveBeenNthCalledWith(
    1,
    expect.objectContaining({ groupKey: "agent:7", limit: 10, cursor: null })
  );
  expect(getConversations).toHaveBeenLastCalledWith(
    expect.objectContaining({ groupKey: "agent:7", limit: 10, cursor: "100" })
  );

  fireEvent.scroll(viewport);
  expect(
    await screen.findByText("chat.threadList.noMoreConversations")
  ).toBeVisible();
  expect(getConversations).toHaveBeenCalledTimes(11);
  Object.defineProperty(viewport, "scrollTop", {
    configurable: true,
    value: 280,
  });
  fireEvent.scroll(viewport);
  expect(screen.getByTestId("agent-history-scroll-shadow-top")).toBeVisible();
  expect(screen.queryByTestId("agent-history-scroll-shadow-bottom")).toBeNull();
  await new Promise((resolve) => setTimeout(resolve, 800));
  Object.defineProperty(viewport, "scrollTop", {
    configurable: true,
    value: 300,
  });
  fireEvent.scroll(viewport);
  await waitFor(
    () =>
      expect(
        screen.queryByText("chat.threadList.noMoreConversations")
      ).toBeNull(),
    { timeout: 700 }
  );
});

it("keeps native overflow without a custom scrollbar when rows fit", async () => {
  vi.spyOn(conversationService, "getAgentGroups").mockResolvedValue(
    agentGroups
  );
  vi.spyOn(conversationService, "getAgentGroupConversations").mockResolvedValue(
    {
      items: [conversation(1), conversation(2)],
      pinned_items: [],
      next_cursor: null,
    }
  );

  renderHistory();
  fireEvent.click(await screen.findByRole("button", { name: "Agent Seven" }));
  await screen.findByText("History 2");

  const viewport = screen.getByTestId("agent-history-conversation-viewport");
  Object.defineProperties(viewport, {
    scrollHeight: { configurable: true, value: 80 },
    clientHeight: { configurable: true, value: 80 },
    scrollTop: { configurable: true, value: 0 },
    offsetWidth: { configurable: true, value: 260 },
    clientWidth: { configurable: true, value: 260 },
  });
  fireEvent.scroll(viewport);

  expect(viewport).toHaveClass(agentChatStyles.scrollArea, "overflow-y-auto");
  expect(viewport.scrollHeight).toBe(viewport.clientHeight);
  expect(viewport).not.toHaveAttribute("data-agent-history-scrolling");
  expect(viewport).toHaveStyle({ width: "100%" });
  expect(screen.queryByTestId("agent-history-floating-scrollbar")).toBeNull();
});

it("removes stale shadows when a short group finishes expanding without a scroll", async () => {
  const resizeCallbacks = new Map<Element, () => void>();
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(private readonly callback: () => void) {}
      observe(element: Element) {
        resizeCallbacks.set(element, this.callback);
      }
      unobserve() {}
      disconnect() {}
    }
  );
  vi.spyOn(conversationService, "getAgentGroups").mockResolvedValue(
    agentGroups
  );
  vi.spyOn(conversationService, "getAgentGroupConversations").mockResolvedValue(
    {
      items: [conversation(1), conversation(2)],
      pinned_items: [],
      next_cursor: null,
    }
  );

  renderHistory();
  fireEvent.click(await screen.findByRole("button", { name: "Agent Seven" }));
  await screen.findByText("History 2");
  const viewport = screen.getByTestId("agent-history-conversation-viewport");
  Object.defineProperties(viewport, {
    scrollHeight: { configurable: true, value: 80 },
    clientHeight: { configurable: true, value: 40 },
    scrollTop: { configurable: true, value: 0 },
  });
  fireEvent.scroll(viewport);
  expect(
    screen.getByTestId("agent-history-scroll-shadow-bottom")
  ).toBeVisible();

  Object.defineProperty(viewport, "clientHeight", {
    configurable: true,
    value: 80,
  });
  act(() => resizeCallbacks.get(viewport)?.());

  expect(screen.queryByTestId("agent-history-scroll-shadow-bottom")).toBeNull();
  expect(screen.queryByTestId("agent-history-scroll-shadow-top")).toBeNull();
});

it("stops when the history API repeats its pagination cursor", async () => {
  vi.spyOn(conversationService, "getAgentGroups").mockResolvedValue(
    agentGroups
  );
  const repeatedPage = {
    items: Array.from({ length: 10 }, (_, index) => conversation(index + 1)),
    pinned_items: [],
    next_cursor: "same-cursor",
  };
  const getConversations = vi
    .spyOn(conversationService, "getAgentGroupConversations")
    .mockResolvedValueOnce(repeatedPage)
    .mockResolvedValueOnce(repeatedPage);

  renderHistory();
  fireEvent.click(await screen.findByRole("button", { name: "Agent Seven" }));
  await screen.findByText("History 10");
  const viewport = screen.getByTestId("agent-history-conversation-viewport");
  Object.defineProperties(viewport, {
    scrollHeight: { configurable: true, value: 600 },
    clientHeight: { configurable: true, value: 320 },
    scrollTop: { configurable: true, value: 220 },
  });

  fireEvent.scroll(viewport);
  await waitFor(() => expect(getConversations).toHaveBeenCalledTimes(2));
  expect(
    await screen.findByText("chat.threadList.noMoreConversations")
  ).toBeVisible();

  Object.defineProperty(viewport, "scrollTop", {
    configurable: true,
    value: 0,
  });
  fireEvent.scroll(viewport);
  Object.defineProperty(viewport, "scrollTop", {
    configurable: true,
    value: 220,
  });
  fireEvent.scroll(viewport);
  expect(getConversations).toHaveBeenCalledTimes(2);
});

it("separates pinned conversations from the regular Agent history", async () => {
  vi.spyOn(conversationService, "getAgentGroups").mockResolvedValue(
    agentGroups
  );
  vi.spyOn(conversationService, "getAgentGroupConversations").mockResolvedValue(
    {
      items: [conversation(1), conversation(2)],
      pinned_items: [{ ...conversation(1), pinned_at: "2026-10-26T00:00:00Z" }],
      next_cursor: null,
    }
  );

  renderHistory();
  fireEvent.click(await screen.findByRole("button", { name: "Agent Seven" }));
  await screen.findByText("History 2");

  expect(screen.getByRole("separator")).toBeVisible();
});

it("shows an in-list loading animation while scrolling fetches another page", async () => {
  vi.spyOn(conversationService, "getAgentGroups").mockResolvedValue(
    agentGroups
  );
  let resolveNext!: (
    value: Awaited<
      ReturnType<typeof conversationService.getAgentGroupConversations>
    >
  ) => void;
  const getConversations = vi
    .spyOn(conversationService, "getAgentGroupConversations")
    .mockResolvedValueOnce({
      items: Array.from({ length: 10 }, (_, index) => conversation(index + 1)),
      pinned_items: [],
      next_cursor: "10",
    })
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveNext = resolve;
        })
    );

  renderHistory();
  fireEvent.click(await screen.findByRole("button", { name: "Agent Seven" }));
  await screen.findByText("History 10");
  const viewport = screen.getByTestId("agent-history-conversation-viewport");
  Object.defineProperties(viewport, {
    scrollHeight: { configurable: true, value: 600 },
    clientHeight: { configurable: true, value: 320 },
    scrollTop: { configurable: true, value: 220 },
  });

  fireEvent.scroll(viewport);
  await waitFor(() => expect(getConversations).toHaveBeenCalledTimes(2));
  expect(
    await screen.findByRole("status", {
      name: "chat.threadList.loadingMore",
    })
  ).toBeVisible();
  fireEvent.scroll(viewport);
  expect(getConversations).toHaveBeenCalledTimes(2);
  Object.defineProperty(viewport, "scrollTop", {
    configurable: true,
    value: 0,
  });
  fireEvent.scroll(viewport);

  await act(async () => {
    resolveNext({
      items: [conversation(11)],
      pinned_items: [],
      next_cursor: null,
    });
  });
  expect(await screen.findByText("History 11")).toBeVisible();
  expect(
    screen.queryByRole("status", { name: "chat.threadList.loadingMore" })
  ).toBeNull();
  expect(
    await screen.findByText("chat.threadList.noMoreConversations")
  ).toBeVisible();
});

it("offers retry after an Agent conversation page fails", async () => {
  state.threadItems = [
    {
      id: "active-thread",
      remoteId: "501",
      title: "Current conversation",
      custom: { agentId: 7, lastMessageAt: 100 },
    },
  ];
  state.mainThreadId = "active-thread";
  vi.spyOn(conversationService, "getAgentGroups").mockResolvedValue(
    agentGroups
  );
  const getConversations = vi
    .spyOn(conversationService, "getAgentGroupConversations")
    .mockRejectedValueOnce(new Error("history unavailable"))
    .mockResolvedValue({
      items: [conversation(502)],
      pinned_items: [],
      next_cursor: null,
    });

  renderHistory(7);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "chat.threadList.historyLoadFailed"
  );
  expect(screen.getByText("Current conversation")).toBeVisible();

  fireEvent.click(
    screen.getByRole("button", { name: "chat.threadList.retry" })
  );
  await waitFor(() => expect(getConversations).toHaveBeenCalledTimes(2));
  expect(await screen.findByText("History 502")).toBeVisible();
  expect(screen.getByText("Current conversation")).toBeVisible();
});

it("keeps the active conversation visible when its history page has no result yet", async () => {
  state.threadItems = [
    {
      id: "active-thread",
      remoteId: "501",
      title: "Current conversation",
      custom: { agentId: 7, lastMessageAt: 100 },
    },
  ];
  state.mainThreadId = "active-thread";
  vi.spyOn(conversationService, "getAgentGroupConversations").mockResolvedValue(
    {
      items: [],
      pinned_items: [],
      next_cursor: null,
    }
  );

  renderHistory(7);

  expect(await screen.findByText("Current conversation")).toBeVisible();
});
