// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { ReadableStream } from "node:stream/web";
import {
  AssistantRuntimeImpl,
  LocalRuntimeCore,
} from "@assistant-ui/core/internal";
import { conversationService } from "@/services/conversationService";
import { remoteChatModelAdapter } from "@/app/newchat/adapter/remote-chat-model-adapter";
import { RemoteConversationHistoryAdapter } from "@/app/newchat/adapter/conversation-thread-list-adapter";
import { useConversationResume } from "@/hooks/chat/useConversationResume";
import type { ApiConversationDetail } from "@/types/conversation";
import type { Agent } from "@/types/agentConfig";
import {
  collectStream,
  restoreHistory,
  summaryEvent,
  summaryParts,
} from "../../infra/automation/d1/frontend/newchat-fixture";

vi.mock("@/services/conversationService", () => ({
  CONVERSATION_PAGE_SIZE: 20,
  conversationService: { getById: vi.fn(), runAgent: vi.fn(), stop: vi.fn() },
}));

describe("UT-FE-040 newchat history turn ownership", () => {
  it("UT-FE-040 groups normal chat output by the originating user turn", async () => {
    const history = await restoreHistory([
      { message_id: 1, role: "user", message: "first question" },
      {
        message_id: 2,
        role: "assistant",
        message: [
          {
            type: "tool",
            content: "",
            tool_name: "first-tool",
            tool_call_id: "tool-1",
            tool_arguments: {},
          },
          {
            type: "execution_logs",
            content: "first result",
            tool_call_id: "tool-1",
          },
        ],
      },
      { message_id: 3, role: "user", message: "follow-up question" },
      {
        message_id: 4,
        role: "assistant",
        message: [
          {
            type: "tool",
            content: "",
            tool_name: "second-tool",
            tool_call_id: "tool-2",
            tool_arguments: {},
          },
          {
            type: "execution_logs",
            content: "second result",
            tool_call_id: "tool-2",
          },
        ],
      },
    ]);
    expect(
      history.messages.map((entry) => [entry.message.id, entry.parentId]),
    ).toEqual([
      ["1", null],
      ["2", "1"],
      ["3", "2"],
      ["4", "3"],
    ]);
    const first = history.messages[1].message.content as any[];
    const second = history.messages[3].message.content as any[];
    expect(first).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          type: "tool-call",
          tool_call_id: "tool-1",
          result: "first result",
        }),
      ]),
    );
    expect(second).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          type: "tool-call",
          tool_call_id: "tool-2",
          result: "second result",
        }),
      ]),
    );
    expect(JSON.stringify(first)).not.toContain("second result");
    expect(JSON.stringify(second)).not.toContain("first result");
    expect(history.headId).toBe("4");
  });
});

function retrySnapshot(
  partial: boolean,
  completed = false,
): ApiConversationDetail {
  return {
    conversation_id: "901",
    create_time: 0,
    message: [
      ...[1, 3, 5].map((id) => ({
        role: "user" as const,
        message_id: id,
        message_index: 0,
        message: "create a document",
      })),
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
            : id === 6 && !completed
              ? [{ type: "model_output_thinking", content: "thinking-6" }]
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

async function loadRetry(snapshot: ApiConversationDetail) {
  return new RemoteConversationHistoryAdapter(
    () => "901",
    async () => ({ remoteId: "901" }),
    async () => snapshot,
  ).load();
}

it.each([
  [false, "refresh"],
  [true, "refresh"],
  [false, "re-entry"],
  [true, "re-entry"],
] as const)(
  "UT-FE-040 preserves 3/3 through streaming replay with partial=%s and %s",
  async (partial, path) => {
    let snapshot = retrySnapshot(partial);
    const getById = vi
      .mocked(conversationService.getById)
      .mockImplementation(async () => snapshot);
    const controllers: Array<{
      enqueue(chunk: Uint8Array): void;
      close(): void;
    }> = [];
    vi.mocked(conversationService.stop).mockResolvedValue(undefined as never);
    vi.mocked(conversationService.runAgent).mockImplementation(
      async (_request, signal) =>
        new ReadableStream<Uint8Array>({
          start(controller) {
            let open = true;
            const transport = {
              enqueue: (chunk: Uint8Array) => controller.enqueue(chunk),
              close: () => {
                if (open) {
                  open = false;
                  controller.close();
                }
              },
            };
            controllers.push(transport);
            signal?.addEventListener("abort", transport.close, { once: true });
          },
        }).getReader() as never,
    );
    const core = new LocalRuntimeCore(
      { adapters: { chatModel: remoteChatModelAdapter } },
      undefined,
    );
    const runtime = new AssistantRuntimeImpl(core);
    const restored = await loadRetry(snapshot);
    expect(restored).not.toHaveProperty("unstable_resume");
    runtime.thread.import(restored);
    expect(runtime.thread.getMessageById("6").getState()).toMatchObject({
      branchNumber: 3,
      branchCount: 3,
    });
    const stopped = { current: new Set<number>() };
    const props = {
      runtime,
      activeConversationId: "901",
      activeThreadId: "thread-901",
      ready: true,
      isThreadRunning: false,
      selectedAgent: { id: 1 } as Agent,
      chatMode: "execution" as const,
      resumedConversationIdsRef: stopped,
      handleGenerationStopped: vi.fn(),
    };
    let mounted = renderHook(() => useConversationResume(props));
    const assertBranches = () => {
      const visible = runtime.thread.getState().messages;
      expect(visible.map((message) => message.role)).toEqual([
        "user",
        "assistant",
      ]);
      expect(visible[0].content).toEqual([
        { type: "text", text: "create a document" },
      ]);
      const answer = runtime.thread.getMessageById(visible.at(-1)!.id);
      expect(answer.getState()).toMatchObject({
        branchNumber: 3,
        branchCount: 3,
      });
      const rows = runtime.thread.export().messages;
      expect(
        rows
          .filter((entry) => entry.message.role === "assistant")
          .map((entry) => entry.parentId),
      ).toEqual(["1", "1", "1"]);
      expect(rows.map((entry) => entry.message.id)).toEqual(
        expect.arrayContaining(["1", "2", "4"]),
      );
    };
    try {
      await waitFor(() => expect(controllers).toHaveLength(1));
      assertBranches();
      if (partial)
        expect(
          JSON.stringify(runtime.thread.getState().messages.at(-1)?.content),
        ).toContain("thinking-6");
      if (path === "re-entry") {
        for (let attempt = 2; attempt <= 3; attempt++) {
          mounted.unmount();
          await act(async () => {
            core.threads.getMainThreadRuntimeCore().detach();
          });
          await waitFor(() =>
            expect(runtime.thread.getState().isRunning).toBe(false),
          );
          mounted = renderHook(() => useConversationResume(props));
          await waitFor(() => expect(controllers).toHaveLength(attempt));
          assertBranches();
        }
      }
      const controller = controllers.at(-1)!;
      snapshot = retrySnapshot(true, true);
      await act(async () => {
        controller.enqueue(
          new TextEncoder().encode(
            `data: ${JSON.stringify({ type: "final_answer", content: "answer-6" })}\n\n`,
          ),
        );
        controller.close();
      });
      await waitFor(() =>
        expect(runtime.thread.getState().isRunning).toBe(false),
      );
      assertBranches();
      expect(
        JSON.stringify(runtime.thread.getState().messages.at(-1)?.content),
      ).toContain("answer-6");
      mounted.unmount();
      runtime.thread.import(await loadRetry(snapshot));
      const lookupCount = getById.mock.calls.length;
      const complete = renderHook(() => useConversationResume(props));
      await waitFor(() =>
        expect(getById).toHaveBeenCalledTimes(lookupCount + 1),
      );
      await act(async () => {
        await Promise.resolve();
      });
      assertBranches();
      expect(controllers).toHaveLength(path === "refresh" ? 1 : 3);
      const current = runtime.thread.getMessageById("6");
      current.switchToBranch({ position: "previous" });
      expect(runtime.thread.getState().messages.at(-1)?.id).toBe("4");
      runtime.thread
        .getMessageById("4")
        .switchToBranch({ position: "previous" });
      expect(runtime.thread.getState().messages.at(-1)?.id).toBe("2");
      complete.unmount();
    } finally {
      mounted.unmount();
      await act(async () => {
        core.threads.getMainThreadRuntimeCore().detach();
      });
    }
  },
);
