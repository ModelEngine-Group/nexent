// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { beforeEach, expect, it, vi } from "vitest";
import type { ChatModelRunOptions } from "@assistant-ui/react";
import {
  clearStepTokenCounts,
  remoteChatModelAdapter,
} from "@/app/newchat/adapter/remote-chat-model-adapter";
import { ReadableStream } from "node:stream/web";

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
  clearStepTokenCounts();
});

function sseStream(events: object[]) {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      const encoder = new TextEncoder();
      for (const event of events) {
        controller.enqueue(
          encoder.encode(`data: ${JSON.stringify(event)}\n\n`)
        );
      }
      controller.close();
    },
  }).getReader();
}

const tokenCountEvent = (
  step: number,
  inputTokens: number,
  outputTokens: number
) => ({
  type: "token_count",
  content: JSON.stringify({
    step_number: step,
    duration: 800 * step,
    step_input_tokens: inputTokens,
    step_output_tokens: outputTokens,
    total_output_tokens: outputTokens,
    estimated_context_tokens: inputTokens + outputTokens,
    token_threshold: null,
    context_window_tokens: 32768,
  }),
});

const textEvent = (content: string) => ({
  type: "model_output",
  content,
});

function options() {
  return {
    messages: [
      {
        id: "question",
        role: "user",
        content: [{ type: "text", text: "hello" }],
      },
    ],
    abortSignal: new AbortController().signal,
    context: {},
    runConfig: { custom: { threadId: "12", agentId: 7 } },
    unstable_threadId: "local-a",
  } as unknown as ChatModelRunOptions;
}

async function consume(input: ChatModelRunOptions) {
  const result = remoteChatModelAdapter.run(input);
  if (Symbol.asyncIterator in result) {
    const chunks = [];
    for await (const chunk of result) chunks.push(chunk);
    return chunks;
  }
  return [await result];
}

interface RecordedStep {
  stepNumber: number;
  stepInputTokens: number;
}

function stepTokenCountsOf(chunk: unknown): RecordedStep[] | undefined {
  return (
    chunk as { metadata?: { custom?: { stepTokenCounts?: RecordedStep[] } } }
  )?.metadata?.custom?.stepTokenCounts;
}

it("snapshots each run's own step token counts onto its message metadata", async () => {
  service.runAgent
    .mockImplementationOnce(async () =>
      sseStream([
        tokenCountEvent(1, 1000, 200),
        textEvent("turn-one-answer"),
        tokenCountEvent(2, 1500, 300),
        textEvent("turn-one-end"),
      ])
    )
    .mockImplementationOnce(async () =>
      sseStream([tokenCountEvent(1, 20, 5), textEvent("turn-two-answer")])
    );

  const first = await consume(options());
  // The follow-up run clears and refills the shared global registry, exactly
  // like sending a second message while the first reply stays on screen.
  const second = await consume(options());

  const firstSteps = stepTokenCountsOf(first.at(-1));
  expect(firstSteps?.map((step) => step.stepNumber)).toEqual([1, 2]);
  expect(firstSteps?.map((step) => step.stepInputTokens)).toEqual([1000, 1500]);

  const secondSteps = stepTokenCountsOf(second.at(-1));
  expect(secondSteps?.map((step) => step.stepNumber)).toEqual([1]);
  expect(secondSteps?.map((step) => step.stepInputTokens)).toEqual([20]);

  // The first message must never inherit the follow-up run's data.
  expect(firstSteps?.some((step) => step.stepInputTokens === 20)).toBe(false);

  // Mid-run yields already carry the accumulated snapshot after each
  // token_count chunk, not only the final yield after the stream closes.
  const midChunk = first.find((chunk) =>
    JSON.stringify(chunk).includes("turn-one-answer")
  );
  const midSteps = stepTokenCountsOf(midChunk);
  expect(midSteps?.map((step) => step.stepNumber)).toEqual([1]);
});

it("omits stepTokenCounts when the run reports no token_count chunks", async () => {
  service.runAgent.mockImplementationOnce(async () =>
    sseStream([textEvent("no-token-usage")])
  );
  const chunks = await consume(options());
  expect(stepTokenCountsOf(chunks.at(-1))).toBeUndefined();
});

it("skips malformed token_count payloads without breaking the stream", async () => {
  service.runAgent.mockImplementationOnce(async () =>
    sseStream([
      { type: "token_count", content: "not-json" },
      textEvent("survives-bad-chunk"),
    ])
  );
  const chunks = await consume(options());
  expect(JSON.stringify(chunks)).toContain("survives-bad-chunk");
  expect(stepTokenCountsOf(chunks.at(-1))).toBeUndefined();
});
