// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { renderHook, waitFor } from "@testing-library/react";
import type {
  AssistantRuntime,
  ChatModelRunOptions,
  ChatModelRunResult,
} from "@assistant-ui/react";
import { expect, it, vi } from "vitest";
import { useConversationResume } from "@/features/workbench/hooks/useConversationResume";
import { remoteChatModelAdapter } from "@/app/newchat/adapter/remote-chat-model-adapter";

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
vi.mock("@/lib/logger", () => ({ default: { error: vi.fn(), log: vi.fn() } }));

it.each([
  { retries: 0, partial: false },
  { retries: 0, partial: true },
  { retries: 2, partial: false },
  { retries: 2, partial: true },
])(
  "resumes the user branch with $retries earlier answers and partial=$partial",
  async ({ retries, partial }) => {
    const answer = (id: number, text: string) => ({
      role: "assistant",
      message_id: id,
      message: [{ type: "final_answer", content: text }],
    });
    const detail = {
      conversation_id: "13",
      message: [
        { role: "user", message_id: 1, message: "earlier question" },
        answer(2, "earlier answer"),
        { role: "user", message_id: 3, message: "current question" },
        ...Array.from({ length: retries }, (_, i) =>
          answer(4 + i, `retry ${i + 1}`)
        ),
        answer(6, partial ? "saved partial" : ""),
      ],
      streaming_message: { message_id: 6, status: "streaming" },
    };
    const originalDetail = JSON.stringify(detail);
    service.getById.mockReset().mockResolvedValue(detail);
    const continued: ChatModelRunResult = {
      content: [{ type: "text", text: "continued" }],
    };
    vi.mocked(remoteChatModelAdapter.run)
      .mockReset()
      .mockImplementation(async function* () {
        yield continued;
      });
    const importHistory = vi.fn();
    const resumeRun = vi.fn();
    renderHook(() =>
      useConversationResume({
        runtime: {
          thread: {
            getState: () => ({ isRunning: false }),
            import: importHistory,
            resumeRun,
          },
        } as unknown as AssistantRuntime,
        activeConversationId: "13",
        activeThreadId: "local-13",
        ready: true,
        isThreadRunning: false,
        selectedAgent: null,
        chatMode: "execution",
        resumedConversationIdsRef: { current: new Set<number>() },
        handleGenerationStopped: vi.fn(),
      })
    );
    await waitFor(() => expect(resumeRun).toHaveBeenCalledOnce());
    expect(service.getById).toHaveBeenCalledExactlyOnceWith("13");
    expect(importHistory).toHaveBeenCalledOnce();
    const repository = importHistory.mock.calls[0][0];
    expect(
      repository.messages.map(
        (entry: { message: { id: string }; parentId: string | null }) => [
          entry.message.id,
          entry.parentId,
        ]
      )
    ).toEqual([
      ["1", null],
      ["2", "1"],
      ["3", "2"],
      ...Array.from({ length: retries }, (_, i) => [String(4 + i), "3"]),
    ]);
    expect(repository.headId).toBe(retries ? "5" : "3");
    expect(repository.messages[1].message.content).toMatchObject([
      { type: "text", text: "earlier answer" },
    ]);
    for (let i = 0; i < retries; i++) {
      expect(repository.messages[3 + i].message.content).toMatchObject([
        { type: "text", text: `retry ${i + 1}` },
      ]);
    }
    const request = resumeRun.mock.calls[0][0];
    expect(request).toMatchObject({
      parentId: "3",
      sourceId: null,
      runConfig: { custom: { threadId: "13", resume: true } },
    });
    expect(remoteChatModelAdapter.run).not.toHaveBeenCalled();
    const options: ChatModelRunOptions = {
      messages: [],
      abortSignal: new AbortController().signal,
      context: {},
      runConfig: {},
      unstable_getMessage: () => repository.messages[2].message,
    };
    const stream = request.stream(options);
    expect((await stream.next()).value).toMatchObject({
      content: partial ? [{ type: "text", text: "saved partial" }] : [],
    });
    expect((await stream.next()).value).toEqual(continued);
    expect((await stream.next()).done).toBe(true);
    expect(remoteChatModelAdapter.run).toHaveBeenCalledExactlyOnceWith(options);
    expect(JSON.stringify(detail)).toBe(originalDetail);
  }
);
