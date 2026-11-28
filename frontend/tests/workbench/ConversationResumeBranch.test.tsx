// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ReadableStream } from "node:stream/web";
import { useSyncExternalStore } from "react";
import {
  AssistantRuntimeImpl,
  LocalRuntimeCore,
} from "@assistant-ui/core/internal";
import { RemoteConversationHistoryAdapter } from "@/app/newchat/adapter/conversation-thread-list-adapter";
import {
  remoteChatModelAdapter,
  type PersistedReplay,
} from "@/app/newchat/adapter/remote-chat-model-adapter";
import { useConversationResume } from "@/features/workbench/hooks/useConversationResume";
import type { ApiConversationDetail } from "@/types/conversation";

const service = vi.hoisted(() => ({
  getById: vi.fn(),
  runAgent: vi.fn(),
  stop: vi.fn(),
}));
vi.mock("@/services/conversationService", () => ({
  CONVERSATION_PAGE_SIZE: 20,
  conversationService: service,
}));
vi.mock(
  "@/app/newchat/adapter/remote-chat-model-adapter",
  async (original) => ({
    ...(await original<object>()),
    remoteChatModelAdapter: { run: vi.fn() },
  })
);

afterEach(() => {
  vi.mocked(remoteChatModelAdapter.run).mockReset();
  service.runAgent.mockReset();
  service.stop.mockReset();
});

function detail(partial: boolean, completed = false): ApiConversationDetail {
  return {
    conversation_id: "42",
    create_time: 0,
    message: [
      { role: "user", message_id: 1, message_index: 0, message: "question" },
      { role: "user", message_id: 3, message_index: 0, message: "question" },
      { role: "user", message_id: 5, message_index: 0, message: "question" },
      ...[2, 4, 6].map((id) => ({
        role: "assistant" as const,
        message_id: id,
        message_index: 1,
        status:
          id === 6 && !completed
            ? ("streaming" as const)
            : ("completed" as const),
        message:
          id === 6 && !partial && !completed
            ? []
            : [{ type: "final_answer", content: `answer-${id}` }],
      })),
    ],
    ...(!completed
      ? {
          streaming_message: {
            message_id: 6,
            message_index: 1,
            status: "streaming" as const,
            message_content: "",
            units: [],
          },
        }
      : {}),
  };
}

function replayStream(events: object[]) {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(
        new TextEncoder().encode(
          events
            .map((event) => "data: " + JSON.stringify(event) + "\n\n")
            .join("")
        )
      );
      controller.close();
    },
  }).getReader();
}

async function renderRealResume() {
  const actual = await vi.importActual<
    typeof import("@/app/newchat/adapter/remote-chat-model-adapter")
  >("@/app/newchat/adapter/remote-chat-model-adapter");
  vi.mocked(remoteChatModelAdapter.run).mockImplementation(
    actual.remoteChatModelAdapter.run
  );
  const initial: ApiConversationDetail = {
    ...detail(true),
    agent_system_key: "nl2agent_main",
    target: { type: "agent", id: 42 },
  };
  const loadDetail = vi.fn().mockResolvedValue(initial);
  const runtime = new AssistantRuntimeImpl(
    new LocalRuntimeCore(
      { adapters: { chatModel: remoteChatModelAdapter } },
      undefined
    )
  );
  const history = new RemoteConversationHistoryAdapter(
    () => "42",
    async () => ({ remoteId: "42" }),
    async () => initial
  );
  runtime.thread.import(await history.load());
  const resumedConversationIdsRef = { current: new Set<number>() };
  const handleGenerationStopped = (id: number) =>
    resumedConversationIdsRef.current.add(id);
  const subscribe = (callback: () => void) =>
    runtime.thread.subscribe(callback);
  const isRunning = () => runtime.thread.getState().isRunning;
  const hook = renderHook(
    ({ active }) => {
      const isThreadRunning = useSyncExternalStore(subscribe, isRunning);
      useConversationResume({
        runtime,
        activeConversationId: active ? "42" : undefined,
        activeThreadId: active ? "local-42" : undefined,
        ready: active,
        isThreadRunning,
        selectedAgent: null,
        chatMode: "execution",
        resumedConversationIdsRef,
        handleGenerationStopped,
        loadDetail,
      });
    },
    { initialProps: { active: true } }
  );
  return { ...hook, runtime, loadDetail, initial };
}

it.each([
  [
    "EOF",
    replayStream([{ type: "final_answer", content: "partial reply" }]),
    "partial reply",
  ],
  [
    "EOF with inline error",
    replayStream([{ type: "error", content: "inline error" }]),
    "inline error",
  ],
  [
    "unavailable SSE",
    replayStream([{ status: "stopped", replay_unavailable: true }]),
    "answer-6",
  ],
  [
    "unavailable JSON",
    { type: "json", data: { replay_unavailable: true } },
    "answer-6",
  ],
] as const)(
  "reconnects the same running assistant after %s",
  async (_name, first, partial) => {
    const second = Promise.withResolvers<ReturnType<typeof replayStream>>();
    service.runAgent
      .mockResolvedValueOnce(first)
      .mockReturnValueOnce(second.promise);
    const { runtime, loadDetail, unmount } = await renderRealResume();
    try {
      await waitFor(() => expect(service.runAgent).toHaveBeenCalledTimes(2));
      const current = runtime.thread.getState().messages.at(-1);
      expect(current?.status).toEqual({ type: "running" });
      expect(current?.content).toContainEqual(
        expect.objectContaining({ type: "text", text: partial })
      );
      for (const [request] of service.runAgent.mock.calls) {
        expect(request).toMatchObject({
          conversation_id: 42,
          runtime_mode: "nl2agent",
          is_resume: true,
          resume_message_id: 6,
        });
      }
      loadDetail.mockResolvedValue(detail(true, true));
      second.resolve(
        replayStream([
          { type: "final_answer", content: "recovered" },
          { status: "completed" },
        ])
      );
      await waitFor(() =>
        expect(runtime.thread.getState().messages.at(-1)).toMatchObject({
          id: current?.id,
          status: { type: "complete", reason: "stop" },
          content: [
            expect.objectContaining({ type: "text", text: "recovered" }),
          ],
        })
      );
      expect(
        runtime.thread
          .export()
          .messages.filter((entry) => entry.message.role === "assistant")
      ).toHaveLength(3);
      expect(service.stop).not.toHaveBeenCalled();
    } finally {
      second.resolve(replayStream([]));
      unmount();
    }
  }
);

it("preserves the reply after the retry budget and reconnects on re-entry", async () => {
  const unavailable = { type: "json", data: { replay_unavailable: true } };
  service.runAgent.mockResolvedValue(unavailable);
  const { runtime, loadDetail, initial, rerender, unmount } =
    await renderRealResume();
  try {
    await waitFor(
      () => {
        expect(runtime.thread.getState().messages.at(-1)).toMatchObject({
          status: { type: "incomplete", reason: "other" },
          content: [
            expect.objectContaining({ type: "text", text: "answer-6" }),
          ],
        });
      },
      { timeout: 2500 }
    );
    // The idle transition checks detail once; it does not start another retry loop.
    await waitFor(() => expect(loadDetail).toHaveBeenCalledTimes(5));
    expect(service.runAgent).toHaveBeenCalledTimes(3);
    expect(service.stop).not.toHaveBeenCalled();

    service.runAgent.mockResolvedValueOnce(
      replayStream([{ status: "completed" }])
    );
    loadDetail
      .mockResolvedValueOnce(initial)
      .mockResolvedValue(detail(true, true));
    rerender({ active: false });
    rerender({ active: true });
    await waitFor(() =>
      expect(runtime.thread.getState().messages.at(-1)?.status).toEqual({
        type: "complete",
        reason: "stop",
      })
    );
    expect(service.runAgent).toHaveBeenCalledTimes(4);
    expect(service.runAgent.mock.lastCall?.[0]).toMatchObject({
      is_resume: true,
      resume_message_id: 6,
    });
  } finally {
    unmount();
  }
});

it.each([true, false])("restores only the original assistant with a saved terminal status (completed: %s)", async (completed) => {
  const initial = detail(false);
  const saved = detail(true, completed);
  saved.message.push({
    role: "assistant",
    message_id: 8,
    message_index: 1,
    status: "completed",
    message: [{ type: "final_answer", content: "a different execution" }],
  });
  const loadDetail = vi.fn().mockResolvedValueOnce(initial).mockResolvedValueOnce(saved);
  const invalidateDetail = vi.fn();
  const replayLoaded = vi.fn();
  vi.mocked(remoteChatModelAdapter.run).mockImplementation(async function* (options) {
    expect(options.runConfig?.custom?.resumeMessageId).toBe(6);
    const load = options.runConfig?.custom
      ?.loadPersistedReplay as () => Promise<PersistedReplay | undefined>;
    const replay = await load();
    replayLoaded(replay);
    if (replay?.state === "terminal") yield replay.result;
  });
  const runtime = new AssistantRuntimeImpl(
    new LocalRuntimeCore({ adapters: { chatModel: remoteChatModelAdapter } }, undefined)
  );
  const history = new RemoteConversationHistoryAdapter(
    () => "42", async () => ({ remoteId: "42" }), async () => initial
  );
  runtime.thread.import(await history.load());
  const { unmount } = renderHook(() => useConversationResume({
    runtime,
    activeConversationId: "42",
    activeThreadId: "local-42",
    ready: true,
    isThreadRunning: false,
    selectedAgent: null,
    chatMode: "execution",
    resumedConversationIdsRef: { current: new Set<number>() },
    handleGenerationStopped: vi.fn(),
    loadDetail,
    invalidateDetail,
  }));
  try {
    await waitFor(() => expect(replayLoaded).toHaveBeenCalledOnce());
    if (completed) {
      expect(replayLoaded).toHaveBeenCalledWith(
        expect.objectContaining({
          state: "terminal",
          result: expect.objectContaining({
            content: [expect.objectContaining({ type: "text", text: "answer-6" })],
            status: expect.objectContaining({ type: "complete" }),
          }),
        })
      );
      await waitFor(() =>
        expect(runtime.thread.getState().messages.at(-1)?.content).toEqual([
          expect.objectContaining({ type: "text", text: "answer-6" }),
        ])
      );
    } else {
      expect(replayLoaded).toHaveBeenCalledWith({ state: "active" });
    }
    expect(invalidateDetail).toHaveBeenCalledWith("42");
    expect(loadDetail).toHaveBeenCalledTimes(2);
  } finally {
    unmount();
  }
});

it.each([
  [false, false],
  [true, false],
  [false, true],
  [true, true],
])(
  "restores the third retry under its query with partial=%s and preceding=%s",
  async (partial, preceding) => {
    const snapshot = detail(partial);
    if (preceding) {
      for (const message of snapshot.message) message.message_index! += 2;
      snapshot.streaming_message!.message_index += 2;
      snapshot.message.unshift(
        {
          role: "user",
          message_id: 901,
          message_index: 0,
          message: "earlier question",
        },
        {
          role: "assistant",
          message_id: 902,
          message_index: 1,
          message: [{ type: "final_answer", content: "earlier answer" }],
        }
      );
    }
    service.getById.mockResolvedValue(snapshot);
    let finish!: () => void;
    const completion = new Promise<void>((resolve) => {
      finish = resolve;
    });
    vi.mocked(remoteChatModelAdapter.run).mockImplementation(
      async function* () {
        yield { content: [{ type: "text", text: "third answer streaming" }] };
        await completion;
        yield { content: [{ type: "text", text: "third answer complete" }] };
      }
    );
    const runtime = new AssistantRuntimeImpl(
      new LocalRuntimeCore(
        { adapters: { chatModel: remoteChatModelAdapter } },
        undefined
      )
    );
    const history = new RemoteConversationHistoryAdapter(
      () => "42",
      async () => ({ remoteId: "42" }),
      async () => snapshot
    );
    runtime.thread.import(await history.load());
    expect(runtime.thread.getState().isRunning).toBe(false);
    const { unmount } = renderHook(() =>
      useConversationResume({
        runtime,
        activeConversationId: "42",
        activeThreadId: "local-42",
        ready: true,
        isThreadRunning: false,
        selectedAgent: null,
        chatMode: "execution",
        resumedConversationIdsRef: { current: new Set<number>() },
        handleGenerationStopped: vi.fn(),
      })
    );
    try {
      await waitFor(() =>
        expect(remoteChatModelAdapter.run).toHaveBeenCalledTimes(1)
      );
      expect(runtime.thread.getState().isRunning).toBe(true);
      const visible = runtime.thread.getState().messages;
      expect(visible.map((message) => message.role)).toEqual(
        preceding
          ? ["user", "assistant", "user", "assistant"]
          : ["user", "assistant"]
      );
      if (preceding) {
        expect(visible[0].id).toBe("901");
        expect(visible[1].content).toEqual([
          expect.objectContaining({ type: "text", text: "earlier answer" }),
        ]);
      }
      const current = runtime.thread.getMessageById(visible.at(-1)!.id);
      expect(current.getState()).toMatchObject({
        branchNumber: 3,
        branchCount: 3,
      });
      expect(
        runtime.thread
          .export()
          .messages.filter((entry) => entry.message.role === "assistant")
          .map((entry) => entry.parentId)
      ).toEqual(preceding ? ["901", "1", "1", "1"] : ["1", "1", "1"]);
      current.switchToBranch({ position: "previous" });
      expect(runtime.thread.getState().messages.at(-1)?.id).toBe("4");
    } finally {
      await act(async () => {
        finish();
        await completion;
      });
      unmount();
    }
  }
);
