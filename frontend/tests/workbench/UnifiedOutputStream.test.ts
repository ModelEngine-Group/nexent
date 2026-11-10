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

async function consume(events: Record<string, unknown>[]) {
  runAgent.mockImplementationOnce(async () =>
    new ReadableStream<Uint8Array>({
      start(c) {
        for (const e of events)
          c.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(e)}\n\n`));
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
    for await (const result of run) results.push(result);
  else results.push(await run);
  return results;
}
const native = (
  type: string,
  sequence: number,
  extra: Record<string, unknown> = {}
) => ({
  type,
  content: "",
  schema_version: 1,
  runtime_mode: "native_agent",
  agent_core: "jiuwen",
  turn_id: "root",
  sequence,
  ...extra,
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
  const normalized = [
    native("step_count", 1, { content: "Step 1", step_id: "s1" }),
    native("model_output", 2, {
      content: "Before",
      block_id: "one",
      step_id: "s1",
    }),
    native("model_output_deep_thinking", 3, {
      content: "Thought",
      block_id: "one",
      step_id: "s1",
    }),
    native("tool", 4, {
      local_call_id: "call",
      tool_name: "mcp",
      tool_arguments: { a: 1 },
    }),
    native("tool_result", 5, { local_call_id: "call", result: "Result" }),
    native("step_count", 6, { content: "Step 2", step_id: "s2" }),
    native("model_output", 7, {
      content: "Final",
      block_id: "final",
      step_id: "s2",
    }),
    { type: "final_answer", content: "Final" },
    native("run_terminal", 8, {
      status: "completed",
      final_content: "Final",
      final_block_ids: ["final"],
    }),
  ];
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
      native("model_output", 1, { block_id: "part", content: "Partial" }),
      native("run_terminal", 2, {
        status,
        final_content: "",
        final_block_ids: [],
        end_reason: "fault",
      }),
    ]);
    const last = results.at(-1)!;
    expect(last.status).toMatchObject({
      type: "incomplete",
      reason: status === "stopped" ? "cancelled" : "error",
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
        message: [
          {
            type: "model_output",
            content: JSON.stringify(
              native("model_output", 1, { block_id: "final", content: "Final" })
            ),
          },
          {
            type: "run_terminal",
            content: JSON.stringify(
              native("run_terminal", 2, {
                status: "completed",
                final_content: "Final",
                final_block_ids: ["final"],
              })
            ),
          },
        ],
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
