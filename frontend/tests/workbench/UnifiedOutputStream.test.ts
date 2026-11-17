// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, it, vi } from "vitest";
import type {
  ChatModelRunOptions,
  ChatModelRunResult,
} from "@assistant-ui/react";
import { ReadableStream } from "node:stream/web";

const runAgent = vi.hoisted(() => vi.fn());
vi.mock("@/services/conversationService", () => ({
  conversationService: { runAgent },
}));
vi.mock("@/lib/logger", () => ({
  default: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));
import {
  remoteChatModelAdapter,
  attachExecutionLogsToTool,
  buildToolCallPart,
  parseStepTokenCount,
} from "@/app/newchat/adapter/remote-chat-model-adapter";

async function consume(
  events: Record<string, unknown>[],
  bufferedTail = false
) {
  runAgent.mockImplementationOnce(async () =>
    new ReadableStream<Uint8Array>({
      start(c) {
        for (const [index, e] of events.entries())
          c.enqueue(
            new TextEncoder().encode(
              `data: ${JSON.stringify(e)}${bufferedTail && index === events.length - 1 ? "" : "\n\n"}`
            )
          );
        c.close();
      },
    }).getReader()
  );
  const options = {
    messages: [
      {
        id: "q",
        role: "user",
        content: [{ type: "text", text: "Current task" }],
      },
    ],
    abortSignal: new AbortController().signal,
    context: {},
    runConfig: {},
    unstable_threadId: "local",
  } as unknown as ChatModelRunOptions;
  const run = remoteChatModelAdapter.run(options);
  const results: ChatModelRunResult[] = [];
  if (Symbol.asyncIterator in run)
    for await (const result of run) results.push(structuredClone(result));
  else results.push(await run);
  return results;
}

it.each([false, true])(
  "replaces complete-mode previews once while retaining real reasoning (tail=%s)",
  async (bufferedTail) => {
    const results = await consume(
      [
        {
          type: "model_output_thinking",
          content: "Real thought",
          step_id: "s",
        },
        {
          type: "model_output_deep_thinking",
          content: "Deep thought",
          step_id: "s",
        },
        {
          type: "model_output_thinking",
          content: "Draft ",
          step_id: "s",
          answer_phase: "delta",
          answer_preview: true,
        },
        {
          type: "model_output_thinking",
          content: "answer",
          step_id: "s",
          answer_phase: "delta",
          answer_preview: true,
        },
        {
          type: "final_answer",
          content: "Corrected answer",
          step_id: "s",
          answer_phase: "complete",
        },
      ],
      bufferedTail
    );
    const partial = results.find((result) =>
      result.content?.some(
        (part) => part.type === "text" && part.text === "Draft "
      )
    );
    expect(partial).toBeDefined();
    expect(
      partial!.content?.some(
        (part) => "isFinalAnswer" in part && part.isFinalAnswer
      )
    ).toBe(false);
    const final = results.at(-1)!;
    expect(final.content?.filter((part) => part.type === "text")).toEqual([
      expect.objectContaining({
        text: "Corrected answer",
        isFinalAnswer: true,
      }),
    ]);
    expect(
      final.content
        ?.filter((part) => part.type === "reasoning")
        .map((part) => part.text)
        .join("")
    ).toBe("Real thoughtDeep thought");
    expect(JSON.stringify(final.content)).not.toContain("Draft");
  }
);

it("renders a buffered preview without treating it as a confirmed final answer", async () => {
  const results = await consume(
    [
      {
        type: "model_output_thinking",
        content: "Partial",
        step_id: "s",
        answer_phase: "delta",
        answer_preview: true,
      },
    ],
    true
  );
  expect(results.at(-1)!.content).toEqual([
    expect.objectContaining({
      type: "text",
      text: "Partial",
      isFinalAnswer: false,
    }),
  ]);
});

it("rolls back a rejected preview before displaying the accepted answer", async () => {
  const results = await consume([
    {
      type: "model_attempt_control",
      content: "",
      phase: "begin",
      attempt_id: "bad",
    },
    {
      type: "model_output_thinking",
      content: "Rejected",
      step_id: "s",
      answer_phase: "delta",
      answer_preview: true,
      attempt_id: "bad",
    },
    {
      type: "model_attempt_control",
      content: "",
      phase: "rollback",
      attempt_id: "bad",
    },
    {
      type: "model_output_thinking",
      content: "Accepted",
      step_id: "s",
      answer_phase: "delta",
      answer_preview: true,
    },
    {
      type: "final_answer",
      content: "Accepted",
      step_id: "s",
      answer_phase: "complete",
    },
  ]);
  expect(
    results.some((result) =>
      result.content?.some(
        (part) => part.type === "text" && part.text === "Rejected"
      )
    )
  ).toBe(true);
  expect(results.at(-1)!.content).toEqual([
    expect.objectContaining({
      type: "text",
      text: "Accepted",
      isFinalAnswer: true,
    }),
  ]);
});

it("keeps a failed partial preview unconfirmed", async () => {
  const result = (
    await consume([
      {
        type: "model_output_thinking",
        content: "Partial",
        step_id: "s",
        answer_phase: "delta",
        answer_preview: true,
      },
      { type: "error", content: "Persistence failed" },
    ])
  ).at(-1)!;
  expect(result.status).toMatchObject({ type: "incomplete", reason: "error" });
  expect(
    result.content?.some(
      (part) => part.type === "text" && part.text === "Partial"
    )
  ).toBe(true);
  expect(
    result.content?.some(
      (part) => "isFinalAnswer" in part && part.isFinalAnswer
    )
  ).toBe(false);
});
it("uses the original reasoning, tool and final parts for both Core event formats", async () => {
  const legacy = [
    { type: "step_count", content: "Step 1", step_id: "s1" },
    { type: "model_output_thinking", content: "Before", step_id: "s1" },
    { type: "model_output_deep_thinking", content: "Thought", step_id: "s1" },
    {
      type: "tool",
      content: "",
      tool_name: "mcp",
      tool_arguments: { a: 1 },
      tool_call_id: "call",
    },
    { type: "execution_logs", content: "Result", tool_call_id: "call" },
    { type: "step_count", content: "Step 2", step_id: "s2" },
    { type: "model_output_thinking", content: "Final", step_id: "s2" },
    {
      type: "final_answer",
      content: "Final",
      step_id: "s2",
      answer_phase: "complete",
      reclassify_step: true,
    },
  ];
  const normalized = legacy.map((event) => ({
    ...event,
    turn_id: "server-turn",
  }));
  const summarize = (parts: any[]) =>
    parts.map((p) => ({
      type: p.type,
      text: p.text,
      toolName: p.toolName,
      argsText: p.argsText,
      result: p.result,
    }));
  const code = (await consume(legacy)).at(-1)!,
    jiuwen = (await consume(normalized)).at(-1)!;
  expect(summarize(jiuwen.content as any[])).toEqual(
    summarize(code.content as any[])
  );
  expect(jiuwen.content?.map((p) => p.type)).toEqual([
    "reasoning",
    "tool-call",
    "text",
  ]);
  expect(JSON.stringify(jiuwen)).not.toContain('"runtime-output"');
  expect(jiuwen.status).toMatchObject({ type: "complete" });
});

it("retains a failed tool status in the original ToolFallback input", () => {
  const part = buildToolCallPart({
    type: "tool",
    content: "",
    tool_name: "mcp",
    tool_call_id: "a",
  });
  expect(
    attachExecutionLogsToTool([part], {
      type: "execution_logs",
      content: "Tool failed",
      tool_call_id: "a",
      is_error: true,
    })
  ).toBe(true);
  expect(part.status).toMatchObject({ type: "incomplete", reason: "error" });
  expect(part.result).toBe("Tool failed");
});

it("preserves unknown and explicit zero in the shared usage data", () => {
  expect(
    parseStepTokenCount('{"step_input_tokens":null,"step_output_tokens":0}')
  ).toMatchObject({
    inputKnown: false,
    outputKnown: true,
    stepOutputTokens: 0,
  });
});

it.each(["failed", "stopped"])(
  "keeps %s partial in the existing process parts with no final",
  async (status) => {
    const results = await consume([
      { type: "model_output_thinking", step_id: "partial", content: "Partial" },
      ...(status === "failed" ? [{ type: "error", content: "fault" }] : []),
    ]);
    const last = results.at(-1)!;
    if (status === "failed")
      expect(last.status).toMatchObject({
        type: "incomplete",
        reason: "error",
      });
    expect(
      last.content?.some(
        (p) => p.type === "reasoning" && p.text.includes("Partial")
      )
    ).toBe(true);
    expect(last.content?.some((p) => (p as any).isFinalAnswer)).toBe(false);
  }
);

it("restores an empty usage bucket for a saved simple native answer", async () => {
  const { RemoteConversationHistoryAdapter } =
    await import("@/app/newchat/adapter/conversation-thread-list-adapter");
  const detail = {
    conversation_id: "42",
    conversation_title: "Output",
    message: [
      {
        role: "assistant",
        message_id: 10,
        status: "completed",
        message: [{ type: "final_answer", content: "Final" }],
      },
    ],
  } as unknown as import("@/types/conversation").ApiConversationDetail;
  const history = await new RemoteConversationHistoryAdapter(
    () => "42",
    async () => ({ remoteId: "42", externalId: "42" }),
    async () => detail
  ).load();
  expect(history.messages[0].message.metadata?.custom?.stepTokenCounts).toEqual(
    []
  );
});

it("owns live usage per message and clears it for the next turn", async () => {
  const used = (
    await consume([
      {
        type: "token_count",
        content: JSON.stringify({
          step_input_tokens: 12,
          step_output_tokens: 3,
          duration: 2,
        }),
      },
      { type: "final_answer", content: "Done" },
    ])
  ).at(-1)!;
  expect(used.metadata?.custom?.stepTokenCounts).toEqual([
    expect.objectContaining({ stepInputTokens: 12, stepOutputTokens: 3 }),
  ]);
  const fresh = (await consume([{ type: "final_answer", content: "Next" }])).at(
    -1
  )!;
  expect(fresh.metadata?.custom?.stepTokenCounts).toEqual([]);
});
