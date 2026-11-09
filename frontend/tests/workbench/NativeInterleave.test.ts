// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { beforeEach, expect, it, vi } from "vitest";
import type { ChatModelRunOptions } from "@assistant-ui/react";
import { remoteChatModelAdapter } from "@/app/newchat/adapter/remote-chat-model-adapter";
import { RemoteConversationHistoryAdapter } from "@/app/newchat/adapter/conversation-thread-list-adapter";
import type { ApiConversationDetail } from "@/types/conversation";

const service = vi.hoisted(() => ({ runAgent: vi.fn(), stop: vi.fn() }));
vi.mock("@/services/conversationService", () => ({
  CONVERSATION_PAGE_SIZE: 20,
  conversationService: service,
}));
vi.mock("@/lib/logger", () => ({
  default: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));
beforeEach(() => {
  service.runAgent.mockReset();
  service.stop.mockReset().mockResolvedValue(undefined);
});

async function run(events: object[], trailingNewline = true) {
  const wire =
    events.map((event) => `data: ${JSON.stringify(event)}`).join("\n\n") +
    (trailingNewline ? "\n\n" : "");
  service.runAgent.mockResolvedValueOnce(
    new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(wire));
        controller.close();
      },
    }).getReader()
  );
  const options = {
    messages: [
      {
        id: "question",
        role: "user",
        content: [{ type: "text", text: "Task" }],
      },
    ],
    abortSignal: new AbortController().signal,
    context: {},
    runConfig: { custom: { threadId: "12", agentId: 7 } },
    unstable_threadId: "native-test",
  } as unknown as ChatModelRunOptions;
  const iterator = remoteChatModelAdapter.run(options);
  let last: any;
  if (Symbol.asyncIterator in iterator)
    for await (const item of iterator) last = item;
  else last = await iterator;
  return last.content as any[];
}

it.each([true, false])(
  "keeps native commentary before tools and promotes only the accepted final step (%s)",
  async (tail) => {
    const parts = await run(
      [
        { type: "model_output", content: "Checking files.", step_id: "1" },
        {
          type: "tool",
          content: "list_directory",
          tool_name: "list_directory",
          tool_call_id: "call-1",
          step_id: "1",
        },
        { type: "model_output", content: "Observed result.", step_id: "2" },
        {
          type: "final_answer",
          content: "",
          step_id: "2",
          answer_phase: "complete",
          reclassify_step: true,
        },
      ],
      tail
    );
    const text = parts.filter((part) => part.type === "text");
    expect(text.map((part) => part.text)).toEqual([
      "Checking files.",
      "Observed result.",
    ]);
    expect(text[0].isIntermediateMessage).toBe(true);
    expect(text[1].isFinalAnswer).toBe(true);
    expect(parts.indexOf(text[0])).toBeLessThan(
      parts.findIndex((part) => part.type === "tool-call")
    );
    expect(parts.filter((part) => part.type === "reasoning")).toEqual([]);
  }
);

it("rolls back failed native text without erasing earlier progress", async () => {
  const parts = await run([
    { type: "model_output", content: "Earlier progress", step_id: "1" },
    {
      type: "model_attempt_control",
      content: "",
      step_id: "2",
      attempt_id: "failed",
      phase: "begin",
    },
    {
      type: "model_output",
      content: "Partial failed answer",
      step_id: "2",
      attempt_id: "failed",
    },
    {
      type: "model_attempt_control",
      content: "",
      step_id: "2",
      attempt_id: "failed",
      phase: "rollback",
    },
    { type: "model_output", content: "Successful answer", step_id: "2" },
    {
      type: "final_answer",
      content: "",
      step_id: "2",
      answer_phase: "complete",
      reclassify_step: true,
    },
  ]);
  expect(
    parts.filter((part) => part.type === "text").map((part) => part.text)
  ).toEqual(["Earlier progress", "Successful answer"]);
});

it("restores separate persisted native messages around tools without merging their positions", async () => {
  const detail = {
    conversation_id: "42",
    create_time: 0,
    message: [
      {
        role: "assistant",
        message_id: 5,
        message: [
          { type: "model_output", content: "Before tool", unit_index: 0 },
          {
            type: "tool",
            content: "list_directory",
            tool_call_id: "call-1",
            unit_index: 1,
          },
          { type: "model_output", content: "After tool", unit_index: 2 },
          { type: "final_answer", content: "Final answer", unit_index: 3 },
        ],
      },
    ],
  } as unknown as ApiConversationDetail;
  const adapter = new RemoteConversationHistoryAdapter(
    () => "42",
    async () => ({ remoteId: "42", externalId: "42" }),
    async () => detail
  );
  const result = await adapter.load();
  const parts = result.messages[0].message.content as any[];
  const text = parts.filter((part) => part.type === "text");
  expect(text.map((part) => part.text)).toEqual([
    "Before tool",
    "After tool",
    "Final answer",
  ]);
  const tool = parts.findIndex((part) => part.type === "tool-call");
  expect(parts.indexOf(text[0])).toBeLessThan(tool);
  expect(parts.indexOf(text[1])).toBeGreaterThan(tool);
});

it.each([true, false])(
  "keeps native provider reasoning separate from the final answer (%s)",
  async (tail) => {
    const parts = await run(
      [
        {
          type: "model_attempt_control",
          content: "",
          phase: "begin",
          attempt_id: "native",
          step_id: "1",
        },
        {
          type: "model_output_deep_thinking",
          content: "Provider reasoning",
          attempt_id: "native",
          step_id: "1",
        },
        {
          type: "model_output",
          content: "Actual answer",
          attempt_id: "native",
          step_id: "1",
        },
        {
          type: "model_attempt_control",
          content: "",
          phase: "commit",
          attempt_id: "native",
          step_id: "1",
        },
        {
          type: "final_answer",
          content: "",
          answer_phase: "complete",
          reclassify_step: true,
          step_id: "1",
        },
      ],
      tail
    );
    const reasoning = parts.filter((part) => part.type === "reasoning");
    expect(reasoning).toHaveLength(1);
    expect(reasoning[0].text).toContain("Provider reasoning");
    expect(reasoning[0].status.type).toBe("done");
    expect(
      parts.filter((part) => part.type === "text").map((part) => part.text)
    ).toEqual(["Actual answer"]);
  }
);

it("restores native reasoning separately from persisted final text", async () => {
  const detail = {
    conversation_id: "42",
    create_time: 0,
    message: [
      {
        role: "assistant",
        message_id: 8,
        message: [
          {
            type: "model_output_deep_thinking",
            content: "Saved provider reasoning",
            unit_index: 0,
            step_id: "1",
          },
          {
            type: "model_output",
            content: "Saved answer",
            unit_index: 1,
            step_id: "1",
          },
          {
            type: "final_answer",
            content: "",
            unit_index: 2,
            step_id: "1",
            answer_phase: "complete",
            reclassify_step: true,
          },
        ],
      },
    ],
  } as unknown as ApiConversationDetail;
  const adapter = new RemoteConversationHistoryAdapter(
    () => "42",
    async () => ({ remoteId: "42", externalId: "42" }),
    async () => detail
  );
  const result = await adapter.load();
  const parts = result.messages[0].message.content as any[];
  expect(
    parts
      .filter((part) => part.type === "reasoning")
      .map((part) => part.text)
      .join("")
  ).toContain("Saved provider reasoning");
  expect(
    parts.filter((part) => part.type === "text").map((part) => part.text)
  ).toEqual(["Saved answer"]);
});
