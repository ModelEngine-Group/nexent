// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, it, vi } from "vitest";
import type {
  ChatModelRunOptions,
  ChatModelRunResult,
} from "@assistant-ui/react";
import { ReadableStream } from "node:stream/web";
import { remoteChatModelAdapter } from "@/app/newchat/adapter/remote-chat-model-adapter";

const runAgent = vi.hoisted(() => vi.fn());
vi.mock("@/services/conversationService", () => ({
  conversationService: { runAgent },
}));
vi.mock("@/lib/logger", () => ({
  default: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));

const completion = (agentId = 42) => ({
  type: "nl2a_state",
  content: JSON.stringify({
    event: "agent_generation_completed",
    agent_id: agentId,
  }),
});
const finish = (core: string, text = "") =>
  core === "jiuwen"
    ? {
        type: "run_terminal",
        content: "",
        schema_version: 1,
        runtime_mode: "native_agent",
        agent_core: "jiuwen",
        turn_id: "creator-turn",
        sequence: 1,
        status: "completed",
        end_reason: "awaiting_input",
        final_content: text,
        final_block_ids: [],
        error: null,
      }
    : { type: "final_answer", content: text };

async function render(events: unknown[]) {
  runAgent.mockResolvedValueOnce(
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const event of events)
          controller.enqueue(
            new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`)
          );
        controller.close();
      },
    }).getReader()
  );
  const input = {
    messages: [
      {
        id: "question",
        role: "user",
        content: [{ type: "text", text: "创建智能体" }],
      },
    ],
    abortSignal: new AbortController().signal,
    context: {},
    runConfig: {
      custom: {
        runtimeMode: "nl2agent",
        agentId: 42,
        modelId: "11",
        persistCreationHistory: true,
      },
    },
    unstable_threadId: "creator-results",
  } as unknown as ChatModelRunOptions;
  const result = remoteChatModelAdapter.run(input);
  const frames: ChatModelRunResult[] = [];
  if (Symbol.asyncIterator in result)
    for await (const frame of result) frames.push(frame);
  else frames.push(await result);
  return (frames.at(-1)?.content ?? []).filter((part: any) => part.type === "data" && part.name === "nl2agent-created");
}

it.each(["smolagents", "jiuwen"])(
  "%s does not infer a result from waiting or answers",
  async (core) => {
    expect(await render([finish(core)])).toEqual([]);
    expect(
      await render([
        {
          type: "nl2a_state",
          content: JSON.stringify({
            event: "agent_draft_fields_saved",
            agent_id: 42,
            updated_fields: ["name"],
          }),
        },
        finish(core, "草稿已保存"),
      ])
    ).toEqual([]);
  }
);
it.each(["smolagents", "jiuwen"])(
  "%s creates one result only from matching completion",
  async (core) => {
    expect(
      await render([completion(), completion(), finish(core, "生成完成")])
    ).toEqual([
      {
        type: "data",
        name: "nl2agent-created",
        data: { agentId: 42, completed: true },
      },
    ]);
  }
);
it.each(["smolagents", "jiuwen"])(
  "%s ignores another Agent or malformed completion",
  async (core) => {
    expect(
      await render([
        completion(99),
        {
          type: "nl2a_state",
          content: '{"event":"agent_generation_completed"}',
        },
        finish(core, "完成"),
      ])
    ).toEqual([]);
  }
);
