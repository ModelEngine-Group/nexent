// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { beforeEach, expect, it, vi } from "vitest";
import type { ChatModelRunOptions } from "@assistant-ui/react";
import { remoteChatModelAdapter } from "@/app/newchat/adapter/remote-chat-model-adapter";

import {
  patchModelDraft,
  snapshotModelDrafts,
} from "@/lib/conversationModelDrafts";

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
  { enable_thinking: false, temperature: 0, top_p: 0.8 },
  {
    enable_thinking: true,
    reasoning_effort: "low",
    temperature: 0.4,
    top_p: 1,
  },
  { enable_thinking: true, reasoning_budget_tokens: 4096 },
])(
  "sends debug parameters through the canonical draft map %j",
  async (values) => {
    const scope = `debug-${JSON.stringify(values)}`;
    patchModelDraft(scope, 12, values, []);
    const input = debugOptions({});
    Object.assign(input.runConfig!.custom!, { modelPreferenceScope: scope });
    const body = await consume(input);
    expect(body.model_parameter_preferences).toEqual({ "12": values });
    expect(body).toMatchObject({
      model_id: 12,
      agent_id: 7,
      version_no: 3,
      is_debug: true,
    });
    expect(body.conversation_id).toBeUndefined();
    expect(body.generation_config).toBeUndefined();
    expect(body.reasoning_effort).toBeUndefined();
    expect(snapshotModelDrafts(scope)).toEqual({ "12": values });
  }
);

it("ignores obsolete ModelContext parameter snapshots", async () => {
  const body = await consume(
    debugOptions({
      deepThinking: true,
      reasoningEffort: "high",
      temperature: 0.4,
      top_p: 0.8,
    })
  );
  expect(body.generation_config).toBeUndefined();
  expect(body.reasoning_effort).toBeUndefined();
});

it("preserves canonical debug drafts when the backend rejects the run", async () => {
  const scope = "debug-failed-run";
  patchModelDraft(scope, 12, { enable_thinking: false }, []);
  const input = debugOptions({});
  Object.assign(input.runConfig!.custom!, { modelPreferenceScope: scope });
  service.runAgent.mockRejectedValueOnce(new Error("offline"));
  await expect(consume(input)).rejects.toThrow("offline");
  expect(snapshotModelDrafts(scope)).toEqual({
    "12": { enable_thinking: false },
  });
});
