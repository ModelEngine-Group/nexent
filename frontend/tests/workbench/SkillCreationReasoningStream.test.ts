import { expect, it, vi } from "vitest";
import type { ChatModelRunOptions, ChatModelRunResult } from "@assistant-ui/react";
import { ReadableStream } from "node:stream/web";

const runAgent = vi.hoisted(() => vi.fn());
vi.mock("@/services/conversationService", () => ({
  conversationService: { runAgent },
}));
vi.mock("@/lib/logger", () => ({
  default: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));

import { remoteChatModelAdapter } from "@/app/newchat/adapter/remote-chat-model-adapter";

async function renderSkillStream(events: Array<{ type: string; content: string }>) {
  runAgent.mockImplementationOnce(async () =>
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const event of events) {
          controller.enqueue(
            new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`)
          );
        }
        controller.close();
      },
    }).getReader()
  );
  const input = {
    messages: [
      {
        id: "question",
        role: "user",
        content: [{ type: "text", text: "创建合同审查技能" }],
      },
    ],
    abortSignal: new AbortController().signal,
    context: {},
    runConfig: { custom: { runtimeMode: "nl2skill" } },
    unstable_threadId: "local-skill",
  } as unknown as ChatModelRunOptions;
  const run = remoteChatModelAdapter.run(input);
  const results: ChatModelRunResult[] = [];
  if (Symbol.asyncIterator in run) {
    for await (const result of run) results.push(result);
  } else {
    results.push(await run);
  }
  return results.at(-1)?.content ?? [];
}

it("does not create an empty Reasoning block for a Skill step marker", async () => {
  const content = await renderSkillStream([
    { type: "summary", content: "技能草稿已生成。" },
    { type: "step_count", content: "**步骤 1**" },
    { type: "done", content: "" },
  ]);
  expect(content.some((part) => part.type === "reasoning")).toBe(false);
});

it("keeps real model thinking in a Skill creation stream", async () => {
  const content = await renderSkillStream([
    { type: "step_count", content: "**步骤 1**" },
    { type: "model_output_thinking", content: "先整理合同条款。" },
    { type: "summary", content: "技能草稿已生成。" },
    { type: "done", content: "" },
  ]);
  expect(content).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        type: "reasoning",
        text: "先整理合同条款。",
      }),
    ])
  );
});
