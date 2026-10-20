// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import {
  AssistantRuntimeImpl,
  LocalRuntimeCore,
} from "@assistant-ui/core/internal";
import { RemoteConversationHistoryAdapter } from "@/app/newchat/adapter/conversation-thread-list-adapter";
import { remoteChatModelAdapter } from "@/app/newchat/adapter/remote-chat-model-adapter";
import { useConversationResume } from "@/features/workbench/hooks/useConversationResume";
import type { ApiConversationDetail } from "@/types/conversation";

const service = vi.hoisted(() => ({ getById: vi.fn() }));
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

afterEach(() => vi.mocked(remoteChatModelAdapter.run).mockReset());

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

it.each([false, true])(
  "restores the third retry under its query with partial=%s",
  async (partial) => {
    const snapshot = detail(partial);
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
        expect(runtime.thread.getState().isRunning).toBe(true)
      );
      const visible = runtime.thread.getState().messages;
      expect(visible.map((message) => message.role)).toEqual([
        "user",
        "assistant",
      ]);
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
      ).toEqual(["1", "1", "1"]);
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
