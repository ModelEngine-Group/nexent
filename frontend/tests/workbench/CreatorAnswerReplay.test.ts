// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { expect, it, vi } from "vitest";
import { ReadableStream } from "node:stream/web";
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

const body =
  "Naming paused. Choose another name. Then continue configuring the conversation.";
const control = {
  type: "model_attempt_control",
  phase: "begin",
  content: "",
  step_id: "third",
  attempt_id: "a",
};
const deltas = [
  "Naming paused. ",
  "Choose another name. ",
  "Then continue configuring the conversation.",
].map((content, unit_index) => ({
  type: "final_answer",
  content,
  answer_phase: "delta",
  step_id: "third",
  attempt_id: "a",
  unit_index: unit_index + 1,
}));

async function render(events: object[], mode: "nl2agent" | "nl2skill") {
  api.runAgent.mockResolvedValueOnce(
    new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(
            events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("")
          )
        );
        controller.close();
      },
    }).getReader()
  );
  const generator = remoteChatModelAdapter.run({
    messages: [
      { id: "user", role: "user", content: [{ type: "text", text: "create" }] },
    ],
    abortSignal: new AbortController().signal,
    context: {},
    unstable_threadId: "creator-protocol",
    runConfig: {
      custom: { threadId: "91", runtimeMode: mode, agentId: 42, resume: true },
    },
  } as any);
  let last: any;
  if (Symbol.asyncIterator in generator)
    for await (const result of generator) last = result;
  return last;
}

it.each(["nl2agent", "nl2skill"] as const)(
  "%s recovery retains the full answer through an empty complete confirmation",
  async (mode) => {
    const result = await render(
      [
        control,
        ...deltas,
        {
          type: "final_answer",
          content: "",
          answer_phase: "complete",
          step_id: "third",
        },
      ],
      mode
    );
    expect(
      result.content
        .filter((p: any) => p.type === "text")
        .map((p: any) => p.text)
        .join("")
    ).toBe(body);
  }
);

it("legacy database recovery matches the historical loader's complete answer", async () => {
  const result = await render([control, ...deltas], "nl2agent");
  const adapter = new RemoteConversationHistoryAdapter(
    () => "91",
    async () => ({ remoteId: "91" }),
    async () =>
      ({
        conversation_id: 91,
        agent_system_key: "nl2agent_main",
        message: [
          {
            message_id: 1,
            message_index: 0,
            role: "user",
            message: "create",
            status: "completed",
          },
          {
            message_id: 2,
            message_index: 1,
            role: "assistant",
            status: "completed",
            message: deltas.map(({ answer_phase, ...event }) => event),
          },
        ],
      }) as any
  );
  const history = await adapter.load();
  const text = (value: any) =>
    value.content
      .filter((p: any) => p.type === "text")
      .map((p: any) => p.text)
      .join("");
  expect(text(result)).toBe(body);
  expect(text(history.messages.at(-1)!.message)).toBe(body);
});

it("rollback removes the rejected answer and complete confirmation replaces rather than duplicates", async () => {
  const result = await render(
    [
      control,
      deltas[0],
      { ...control, phase: "rollback" },
      { ...control, attempt_id: "b" },
      { ...deltas[0], attempt_id: "b", content: "preview" },
      {
        type: "final_answer",
        content: "Accepted answer",
        answer_phase: "complete",
        step_id: "third",
      },
    ],
    "nl2agent"
  );
  expect(
    result.content.filter((p: any) => p.type === "text").map((p: any) => p.text)
  ).toEqual(["Accepted answer"]);
});
