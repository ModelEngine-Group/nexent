// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { beforeEach, expect, it, vi } from "vitest";
import type { ChatModelRunOptions } from "@assistant-ui/react";
import { remoteChatModelAdapter } from "@/app/newchat/adapter/remote-chat-model-adapter";

const service = vi.hoisted(() => ({ runAgent: vi.fn() }));
vi.mock("@/services/conversationService", () => ({
  conversationService: service,
}));
vi.mock("@/lib/logger", () => ({
  default: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));

beforeEach(() => {
  service.runAgent.mockReset().mockResolvedValue({ type: "json", data: {} });
});

function debugOptions(config: Record<string, unknown>) {
  return {
    messages: [
      {
        id: "prior",
        role: "assistant",
        content: [{ type: "text", text: "old" }],
      },
      { id: "query", role: "user", content: [{ type: "text", text: "hello" }] },
    ],
    context: {
      config: {
        modelName: "11",
        reasoningCapability: {
          status: "supported",
          controls: [{ type: "toggle" }, { type: "effort" }],
          levels: ["low", "xhigh"],
        },
        ...config,
      },
    },
    abortSignal: new AbortController().signal,
    runConfig: {
      custom: {
        runtimeMode: "agent-debug",
        agentId: 7,
        modelId: "12",
        agentVersionNo: 3,
        threadId: "99",
      },
    },
    unstable_threadId: "debug-a",
  } as unknown as ChatModelRunOptions;
}

async function consume(input: ChatModelRunOptions) {
  const run = remoteChatModelAdapter.run(input);
  if (Symbol.asyncIterator in run) {
    for await (const result of run) {
      void result;
    }
  } else await run;
  return service.runAgent.mock.calls.at(-1)![0];
}

it.each([
  [{ deepThinking: false, reasoningEffort: "auto" }, { deep_thinking: false }],
  [
    { deepThinking: true, reasoningEffort: "auto" },
    { deep_thinking: true, thinking_effort: "auto" },
  ],
  [
    { deepThinking: true, reasoningEffort: "xhigh" },
    { deep_thinking: true, thinking_effort: "xhigh" },
  ],
  [
    {
      deepThinking: true,
      reasoningEffort: "xhigh",
      reasoningBudgetTokens: 4096,
    },
    { deep_thinking: true, reasoning_budget_tokens: 4096 },
  ],
  [
    { deepThinking: true, reasoningEffort: "auto", reasoningBudgetTokens: 0 },
    { deep_thinking: true, reasoning_budget_tokens: 0 },
  ],
])(
  "serializes explicit debug reasoning intent %j",
  async (config, expected) => {
    const input = debugOptions(config);
    const previous = structuredClone({
      messages: input.messages,
      context: input.context,
      runConfig: input.runConfig,
    });
    const body = await consume(input);
    expect(body.generation_config).toEqual(expected);
    expect(body).toMatchObject({
      model_id: 12,
      agent_id: 7,
      version_no: 3,
      is_debug: true,
      history: [{ role: "assistant", content: "old" }],
    });
    expect(body.conversation_id).toBeUndefined();
    expect({
      messages: input.messages,
      context: input.context,
      runConfig: input.runConfig,
    }).toEqual(previous);
  }
);

it("keeps omitted debug intent and existing sampling exclusion unchanged", async () => {
  const body = await consume(debugOptions({ temperature: 0.4, top_p: 0.8 }));
  expect(body.generation_config).toBeUndefined();
});

it("does not add sampling or stale effort to the disabled generation config", async () => {
  const body = await consume(
    debugOptions({
      deepThinking: false,
      reasoningEffort: "xhigh",
      temperature: 0,
      top_p: 0,
    })
  );
  expect(body.generation_config).toEqual({ deep_thinking: false });
  // The compatibility field is retained; canonical disabled intent wins downstream.
  expect(body.reasoning_effort).toBe("xhigh");
});

it("preserves the explicit disabled request when the backend rejects the run", async () => {
  service.runAgent.mockRejectedValueOnce(new Error("offline"));
  await expect(consume(debugOptions({ deepThinking: false }))).rejects.toThrow(
    "offline"
  );
  expect(service.runAgent.mock.calls[0][0].generation_config).toEqual({
    deep_thinking: false,
  });
});
