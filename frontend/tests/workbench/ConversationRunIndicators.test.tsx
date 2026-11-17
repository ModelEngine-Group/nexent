// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  useRemoteThreadListRuntime,
  useAuiState,
  type AssistantRuntime,
  type ChatModelAdapter,
  type RemoteThreadListAdapter,
} from "@assistant-ui/react";
import { createAssistantStream } from "assistant-stream";
import { expect, it, vi } from "vitest";
import { useState } from "react";
import { TooltipProvider } from "@/components/ui/tooltip";
import {
  BatchSelectionProvider,
  ThreadList,
} from "@/app/newchat/assistant-ui/thread-list";
import { conversationService } from "@/services/conversationService";

vi.mock("@/hooks/agent/usePublishedAgentList", () => ({
  usePublishedAgentList: () => ({ availableMainAgents: [] }),
}));
vi.mock("@/hooks/useConfirmModal", () => ({
  useConfirmModal: () => ({ confirm: vi.fn() }),
}));

async function setup(agentChat = false) {
  let runtime!: AssistantRuntime;
  let bindServerIds!: (ids: Map<string, string>) => void;
  let finish!: () => void;
  let fail = false;
  let runs = 0;
  const model: ChatModelAdapter = {
    async *run() {
      runs++;
      const completion = new Promise<void>((resolve) => {
        finish = resolve;
      });
      yield { content: [{ type: "text", text: "Partial" }] };
      await completion;
      if (fail) {
        yield {
          status: { type: "incomplete", reason: "error" },
          content: [{ type: "text", text: "Failed" }],
        };
        return;
      }
      yield { content: [{ type: "text", text: "Completed" }] };
    },
  };
  const rows = ["1", "2"].map((id) => ({
    remoteId: id,
    status: "regular" as const,
    title: `History ${id}`,
    custom: { agentId: 7, lastMessageAt: new Date().toISOString() },
  }));
  vi.spyOn(conversationService, "getAgentGroupConversations").mockResolvedValue(
    {
      items: rows.map((row) => ({
        conversation_id: Number(row.remoteId),
        agent_id: 7,
        conversation_title: row.title,
        create_time: Date.now(),
        update_time: Date.now(),
      })),
      next_cursor: null,
      pinned_items: [],
    }
  );
  const adapter: RemoteThreadListAdapter = {
    async list() {
      return { threads: rows };
    },
    async fetch(id) {
      return rows.find((row) => row.remoteId === id)!;
    },
    async initialize() {
      return { remoteId: "3" };
    },
    async rename() {},
    async archive() {},
    async unarchive() {},
    async delete() {},
    async generateTitle() {
      return createAssistantStream(() => {});
    },
  };
  function Content() {
    const id = useAuiState((state) => state.threads.mainThreadId);
    return (
      <div data-conversation-content={id}>
        <input aria-label="Conversation input" />
      </div>
    );
  }
  function Harness() {
    const [serverIds, setServerIds] = useState(new Map<string, string>());
    bindServerIds = setServerIds;
    runtime = useRemoteThreadListRuntime({
      runtimeHook: function Runtime() {
        return useLocalRuntime(model);
      },
      adapter,
    });
    return (
      <AssistantRuntimeProvider runtime={runtime}>
        <TooltipProvider>
          <BatchSelectionProvider serverConversationIds={serverIds}>
            <ThreadList
              newChatDesign={agentChat}
              selectedAgentId={agentChat ? 7 : undefined}
              serverConversationIds={serverIds}
            />
            <Content />
            <button>Outside conversation</button>
          </BatchSelectionProvider>
        </TooltipProvider>
      </AssistantRuntimeProvider>
    );
  }
  const query = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  const view = render(
    <QueryClientProvider client={query}>
      <Harness />
    </QueryClientProvider>
  );
  await screen.findByText("History 1");
  const id = (remote: string) =>
    Object.values(runtime.threads.getState().threadItems).find(
      (item) => item.remoteId === remote
    )!.id;
  await act(async () => runtime.threads.switchToThread(id("1")));
  return {
    view,
    runtime,
    id,
    bindServerIds,
    runs: () => runs,
    start: async () => {
      act(() => runtime.thread.append("A new question"));
      await waitFor(() =>
        expect(runtime.thread.getState().isRunning).toBe(true)
      );
    },
    finish: async (failed = false) => {
      fail = failed;
      await act(async () => finish());
      await waitFor(() =>
        expect(runtime.thread.getState().isRunning).toBe(false)
      );
    },
    close: async () => {
      await act(async () => {
        finish?.();
      });
      view.unmount();
      query.clear();
    },
  };
}

it.each([false, true])(
  "both list renderers use shared title and time presentation, Agent chat=%s",
  async (agentChat) => {
    const h = await setup(agentChat);
    try {
      const row = h.view.container.querySelector('[data-conversation-id="1"]')!;
      const title = row.querySelector("[data-history-title]");
      expect(title).toHaveTextContent("History 1");
      expect(title).toHaveClass("truncate");
      expect(title?.closest("button")).not.toHaveAttribute("title");
      expect(row.querySelector("[data-history-time]")).toHaveClass(
        "group-hover/item:invisible",
        "group-focus-within/item:invisible"
      );
    } finally {
      await h.close();
    }
  }
);

it.each([false, true])(
  "acknowledges successful completion and retry through either history list (agent=%s)",
  async (agentChat) => {
    const h = await setup(agentChat);
    try {
      await h.start();
      expect(
        screen.getByRole("status", { name: "chat.threadList.running" })
      ).toBeInTheDocument();
      fireEvent.click(screen.getByLabelText("Conversation input"));
      await h.finish();
      expect(
        screen.getByTitle("chat.threadList.completed")
      ).toBeInTheDocument();
      fireEvent.click(screen.getByText("Outside conversation"));
      expect(
        screen.getByTitle("chat.threadList.completed")
      ).toBeInTheDocument();
      fireEvent.click(screen.getByLabelText("Conversation input"));
      expect(
        screen.queryByTitle("chat.threadList.completed")
      ).not.toBeInTheDocument();
      expect(h.runs()).toBe(1);
      act(() => {
        void h.runtime.thread.startRun({
          parentId: h.runtime.thread.getState().messages[0]!.id,
        });
      });
      await waitFor(() =>
        expect(h.runtime.thread.getState().isRunning).toBe(true)
      );
      expect(
        screen.queryByTitle("chat.threadList.completed")
      ).not.toBeInTheDocument();
      await h.finish();
      fireEvent.click(screen.getByText("History 1"));
      await waitFor(() =>
        expect(
          screen.queryByTitle("chat.threadList.completed")
        ).not.toBeInTheDocument()
      );
      expect(h.runs()).toBe(2);
      expect(
        h.runtime.thread.getState().messages.filter((m) => m.role === "user")
      ).toHaveLength(1);
    } finally {
      await h.close();
    }
  }
);

it("tracks a background run by its owner and clears it only on viewing that owner", async () => {
  const h = await setup();
  try {
    await h.start();
    const owner = h.runtime.threads.getById(h.id("1"));
    await act(async () => h.runtime.threads.switchToThread(h.id("2")));
    expect(
      screen.queryByTitle("chat.threadList.completed")
    ).not.toBeInTheDocument();
    expect(owner.getState().isRunning).toBe(true);
    await h.finish();
    await waitFor(() =>
      expect(screen.getByTitle("chat.threadList.completed")).toBeInTheDocument()
    );
    fireEvent.keyDown(screen.getByLabelText("Conversation input"), {
      key: "a",
    });
    expect(screen.getByTitle("chat.threadList.completed")).toBeInTheDocument();
    await act(async () => h.runtime.threads.switchToThread(h.id("1")));
    expect(
      screen.queryByTitle("chat.threadList.completed")
    ).not.toBeInTheDocument();
  } finally {
    await h.close();
  }
});

it("does not mark a failed answer as successful completion", async () => {
  const h = await setup();
  try {
    await h.start();
    await h.finish(true);
    expect(
      screen.queryByTitle("chat.threadList.completed")
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("status", { name: "chat.threadList.running" })
    ).not.toBeInTheDocument();
  } finally {
    await h.close();
  }
});

it("clears completion on keyboard input and preserves it through a list refresh", async () => {
  const h = await setup();
  try {
    await h.start();
    await h.finish();
    await act(async () => h.runtime.threads.reload());
    expect(screen.getByTitle("chat.threadList.completed")).toBeInTheDocument();
    fireEvent.keyDown(screen.getByLabelText("Conversation input"), {
      key: "Tab",
    });
    expect(
      screen.queryByTitle("chat.threadList.completed")
    ).not.toBeInTheDocument();
    expect(h.runs()).toBe(1);
  } finally {
    await h.close();
  }
});

it("does not show successful completion for a cancelled run", async () => {
  const h = await setup();
  try {
    await h.start();
    act(() => {
      h.runtime.thread.cancelRun();
    });
    await h.finish();
    expect(
      screen.queryByTitle("chat.threadList.completed")
    ).not.toBeInTheDocument();
  } finally {
    await h.close();
  }
});

it("maps a newly persisted conversation to the same completion and clears it on the next run", async () => {
  const h = await setup();
  try {
    await act(async () => h.runtime.threads.switchToNewThread());
    await h.start();
    await h.finish();
    expect(h.runtime.threads.mainItem.getState().remoteId).toBe("3");
    expect(screen.getByTitle("chat.threadList.completed")).toBeInTheDocument();
    await h.start();
    expect(
      screen.queryByTitle("chat.threadList.completed")
    ).not.toBeInTheDocument();
    await h.finish();
    expect(screen.getByTitle("chat.threadList.completed")).toBeInTheDocument();
  } finally {
    await h.close();
  }
});

it("uses the server identity registry for Agent rows while the local runtime keeps its original identity", async () => {
  const h = await setup(true);
  try {
    await h.start();
    act(() => h.bindServerIds(new Map([[h.id("1"), "301"]])));
    const row = h.view.container.querySelector('[data-conversation-id="301"]')!;
    expect(
      row.querySelector('[role="status"].animate-spin')
    ).toBeInTheDocument();
    await h.finish();
    expect(row.querySelector('span[role="status"]')).toBeInTheDocument();
    fireEvent.click(row);
    expect(row.querySelector('span[role="status"]')).not.toBeInTheDocument();
    expect(h.runtime.threads.mainItem.getState().remoteId).toBe("1");
    expect(h.runs()).toBe(1);
  } finally {
    await h.close();
  }
});
