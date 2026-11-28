// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, it, vi } from "vitest";
import { ReadableStream } from "node:stream/web";
import type { ChatModelRunOptions } from "@assistant-ui/react";
import { remoteChatModelAdapter } from "@/app/newchat/adapter/remote-chat-model-adapter";
import { RemoteConversationHistoryAdapter } from "@/app/newchat/adapter/conversation-thread-list-adapter";

const api = vi.hoisted(() => ({ runAgent: vi.fn(), stop: vi.fn() }));
vi.mock("@/services/conversationService", () => ({
  CONVERSATION_PAGE_SIZE: 20,
  conversationService: api,
}));
vi.mock("@/lib/logger", () => ({
  default: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));

function options(
  id = "12",
  custom: Record<string, unknown> = {}
): ChatModelRunOptions {
  return {
    messages: [
      {
        id: "user",
        role: "user",
        content: [{ type: "text", text: "execute" }],
      },
    ],
    abortSignal: new AbortController().signal,
    context: {},
    runConfig: { custom: { threadId: id, ...custom } },
    unstable_threadId: `local-${id}`,
  } as unknown as ChatModelRunOptions;
}

async function snapshots(events: object[], runOptions = options()) {
  api.runAgent.mockResolvedValueOnce(
    new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(
          new TextEncoder().encode(
            events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("")
          )
        );
        c.close();
      },
    }).getReader()
  );
  const generator = remoteChatModelAdapter.run(runOptions);
  const results = [];
  if (Symbol.asyncIterator in generator)
    for await (const result of generator) results.push(result);
  return results;
}

async function run(events: object[], runOptions = options()) {
  return (await snapshots(events, runOptions)).at(-1)!;
}

const failedToolEvents = [
  {
    type: "tool",
    content: "{}",
    tool_name: "verify",
    tool_call_id: "verify-1",
  },
  {
    type: "execution_logs",
    content: "candidate assessments incomplete",
    tool_call_id: "verify-1",
    is_error: true,
  },
];

it("keeps the run active after a failed tool and completes when the run recovers", async () => {
  const results = await snapshots([
    ...failedToolEvents,
    { type: "warning", content: "Retrying the step" },
    { type: "final_answer", content: "done" },
    { status: "completed" },
  ]);
  expect(
    results.slice(0, -1).every((result) => result.status?.type === "running")
  ).toBe(true);
  expect(results.at(-1)?.status).toMatchObject({ type: "complete" });
  expect(
    results.at(-1)?.content?.find((part) => part.type === "tool-call")
  ).toMatchObject({ isError: true });
});

it("does not infer a run failure from a tool result in a legacy stream or history", async () => {
  expect((await run(failedToolEvents)).status).toMatchObject({
    type: "complete",
  });
  const adapter = new RemoteConversationHistoryAdapter(
    () => "12",
    async () => ({ remoteId: "12" }),
    async () =>
      ({
        conversation_id: 12,
        message: [
          {
            role: "assistant",
            message_id: 2,
            message: failedToolEvents,
          },
        ],
      }) as any
  );
  const repository = await adapter.load();
  const message = repository.messages.at(-1)?.message;
  expect(message?.status).toMatchObject({ type: "complete" });
  expect(
    message?.content.find((part) => part.type === "tool-call")
  ).toMatchObject({ isError: true });
});

it("acknowledges only admitted sends, never resume or HTTP rejection", async () => {
  const accepted = vi.fn();
  const request = options("12", { onMessageAccepted: accepted });
  await run([{ status: "completed" }], request);
  expect(accepted).toHaveBeenCalledExactlyOnceWith("execute");
  accepted.mockClear();
  await run(
    [{ status: "completed" }],
    options("12", { onMessageAccepted: accepted, resume: true })
  );
  expect(accepted).not.toHaveBeenCalled();
  api.runAgent.mockRejectedValueOnce(new Error("Admission rejected"));
  const generator = remoteChatModelAdapter.run(request);
  if (Symbol.asyncIterator in generator) {
    try {
      for await (const _result of generator) {
        /* Drain the request failure. */
      }
    } catch {
      /* The adapter may propagate admission failures. */
    }
  }
  expect(accepted).not.toHaveBeenCalled();
});

it.each(["failed", "stopped"])(
  "retains the real %s terminal outcome",
  async (outcome) => {
    const result = await run([
      { type: "error", content: "provider rejected" },
      { status: outcome },
    ]);
    expect(result.status).toMatchObject({
      type: "incomplete",
      reason: outcome === "failed" ? "error" : "cancelled",
    });
  }
);

it("does not convert a recoverable warning into failure", async () => {
  const result = await run([
    { type: "warning", content: "retrying" },
    { type: "final_answer", content: "done" },
    { status: "completed" },
  ]);
  expect(result.status).toMatchObject({ type: "complete" });
});

it.each(["failed", "stopped", "pending", "streaming"])(
  "hydrates historical %s with a reconnectable runtime status",
  async (outcome) => {
    const adapter = new RemoteConversationHistoryAdapter(
      () => "12",
      async () => ({ remoteId: "12" }),
      async () =>
        ({
          conversation_id: 12,
          message: [
            { role: "user", message_id: 1, message: "question" },
            {
              role: "assistant",
              message_id: 2,
              status: outcome,
              message: [{ type: "error", content: "old failure" }],
            },
          ],
        }) as any
    );
    const repository = await adapter.load();
    expect(repository.messages.at(-1)?.message.status).toMatchObject(
      outcome === "pending" || outcome === "streaming"
        ? { type: "complete" }
        : {
            type: "incomplete",
            reason: outcome === "failed" ? "error" : "cancelled",
          }
    );
  }
);

it("deduplicates replayed step durations using their persisted unit identity", async () => {
  const metric = {
    type: "token_count",
    unit_index: 1,
    content: JSON.stringify({
      step_number: 1,
      duration: 2,
      total_output_tokens: 20,
    }),
  };
  const result = await run([
    metric,
    metric,
    {
      type: "token_count",
      unit_index: 2,
      content: JSON.stringify({
        step_number: 2,
        duration: 3,
        total_output_tokens: 50,
      }),
    },
    { status: "completed" },
  ]);
  expect((result.metadata as any).timing.totalStreamTime).toBe(5000);
});

it("keeps concurrent conversation timing counters independent", async () => {
  const controllers = new Map<
    number,
    ReadableStreamDefaultController<Uint8Array>
  >();
  api.runAgent.mockImplementation(async (body) =>
    new ReadableStream<Uint8Array>({
      start(controller) {
        controllers.set(Number(body.conversation_id), controller as any);
      },
    }).getReader()
  );
  const collect = async (id: string) => {
    const iterator = remoteChatModelAdapter.run(options(id));
    let last: any;
    if (Symbol.asyncIterator in iterator)
      for await (const result of iterator) last = result;
    return last;
  };
  const a = collect("12"),
    b = collect("13");
  await vi.waitFor(() => expect(controllers.size).toBe(2));
  const emit = (id: number, step: number, duration: number) =>
    controllers
      .get(id)!
      .enqueue(
        new TextEncoder().encode(
          `data: ${JSON.stringify({ type: "token_count", unit_index: step, content: JSON.stringify({ step_number: step, duration }) })}\n\n`
        )
      );
  emit(12, 1, 2);
  emit(13, 1, 7);
  emit(12, 2, 3);
  controllers.forEach((controller) => controller.close());
  const [first, second] = await Promise.all([a, b]);
  expect(first.metadata.timing.totalStreamTime).toBe(5000);
  expect(second.metadata.timing.totalStreamTime).toBe(7000);
});
