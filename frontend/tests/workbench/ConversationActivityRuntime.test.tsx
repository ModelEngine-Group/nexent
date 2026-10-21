// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, render, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  useRemoteThreadListRuntime,
  type AssistantRuntime,
  type ChatModelAdapter,
  type RemoteThreadListAdapter,
} from "@assistant-ui/react";
import { createAssistantStream } from "assistant-stream";
import { expect, it, vi } from "vitest";
import { conversationService } from "@/services/conversationService";
import { useConversationActivitySync } from "@/hooks/chat/useConversationActivitySync";

it("real same-adapter activity reload retains an active stream and the next composer draft", async () => {
  let finish!: () => void;
  const completion = new Promise<void>((resolve) => {
    finish = resolve;
  });
  let signal: AbortSignal | undefined;
  const model: ChatModelAdapter = {
    async *run(options) {
      signal = options.abortSignal;
      yield { content: [{ type: "text", text: "partial response" }] };
      await completion;
      yield { content: [{ type: "text", text: "finished response" }] };
    },
  };
  let rows = [
    {
      conversation_id: 42,
      conversation_title: "Active history",
      create_time: 1,
      update_time: 1,
      last_activity_time: 1,
    },
  ];
  const metadata = (id: string) => {
    const row = rows.find((item) => String(item.conversation_id) === id)!;
    return {
      remoteId: id,
      status: "regular" as const,
      title: row.conversation_title,
      custom: { lastMessageAt: new Date(row.last_activity_time).toISOString() },
    };
  };
  const adapter: RemoteThreadListAdapter = {
    async list() {
      return {
        threads: rows.map((row) => metadata(String(row.conversation_id))),
      };
    },
    async fetch(id) {
      return metadata(id);
    },
    async initialize() {
      return { remoteId: "draft", externalId: "draft" };
    },
    async rename() {},
    async archive() {},
    async unarchive() {},
    async delete() {},
    async generateTitle() {
      return createAssistantStream(() => {});
    },
  };
  vi.spyOn(conversationService, "getList").mockImplementation(async () => ({
    items: [...rows],
    metadata: {
      total: rows.length,
      today: rows.length,
      last_7_days: 0,
      older: 0,
    },
    next_cursor: null,
  }));
  let runtime!: AssistantRuntime;
  function Sync() {
    useConversationActivitySync("owner", "workbench");
    return null;
  }
  function useControlledRuntime() {
    return useLocalRuntime(model);
  }
  function Harness() {
    runtime = useRemoteThreadListRuntime({
      runtimeHook: useControlledRuntime,
      adapter,
    });
    return (
      <AssistantRuntimeProvider runtime={runtime}>
        <Sync />
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
  try {
    await waitFor(() =>
      expect(
        Object.values(runtime.threads.getState().threadItems).some(
          (item) => item.remoteId === "42"
        )
      ).toBe(true)
    );
    const id = Object.entries(runtime.threads.getState().threadItems).find(
      ([, item]) => item.remoteId === "42"
    )![0];
    await act(async () => {
      await runtime.threads.switchToThread(id);
    });
    act(() => runtime.thread.append("start the controlled stream"));
    await waitFor(() => expect(runtime.thread.getState().isRunning).toBe(true));
    act(() =>
      runtime.thread.composer.setText("Keep this next draft during the stream")
    );
    rows = [
      {
        conversation_id: 99,
        conversation_title: "Background activity",
        create_time: 1,
        update_time: 1,
        last_activity_time: 100,
      },
      ...rows,
    ];
    act(() => window.dispatchEvent(new Event("focus")));
    await waitFor(() =>
      expect(
        Object.values(runtime.threads.getState().threadItems).some(
          (item) => item.remoteId === "99"
        )
      ).toBe(true)
    );
    expect(runtime.threads.getState().mainThreadId).toBe(id);
    expect(runtime.thread.getState().isRunning).toBe(true);
    expect(runtime.thread.composer.getState().text).toBe(
      "Keep this next draft during the stream"
    );
    expect(signal?.aborted).toBe(false);
    await act(async () => finish());
    await waitFor(() =>
      expect(runtime.thread.getState().isRunning).toBe(false)
    );
    expect(runtime.thread.getState().messages.at(-1)?.content).toEqual([
      { type: "text", text: "finished response" },
    ]);
    expect(runtime.thread.composer.getState().text).toBe(
      "Keep this next draft during the stream"
    );
  } finally {
    finish();
    view.unmount();
    query.clear();
  }
});
