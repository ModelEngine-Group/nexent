// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, it, vi } from "vitest";
import type { ChatModelRunOptions } from "@assistant-ui/react";
import { ReadableStream } from "node:stream/web";
import {
  remoteChatModelAdapter,
  parseNl2AgentState,
} from "@/app/newchat/adapter/remote-chat-model-adapter";

const service = vi.hoisted(() => ({ runAgent: vi.fn() }));
vi.mock("@/services/conversationService", () => ({
  conversationService: service,
}));
vi.mock("@/lib/logger", () => ({
  default: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));

const saved = (fields: string[]) =>
  JSON.stringify({
    event: "agent_draft_fields_saved",
    agent_id: 42,
    updated_fields: fields,
  });

it("accepts a policy-only saved event without promoting it to generation completion", () => {
  expect(parseNl2AgentState(saved(["enable_protocol_repair_retry"]))).toEqual({
    event: "agent_draft_fields_saved",
    agent_id: 42,
    updated_fields: ["enable_protocol_repair_retry"],
  });
});

it("accepts policy with existing prompt and name fields", () => {
  const fields = [
    "name",
    "display_name",
    "description",
    "enable_protocol_repair_retry",
    "prompt",
  ];
  expect(parseNl2AgentState(saved(fields))?.event).toBe(
    "agent_draft_fields_saved"
  );
});

it.each([
  ["enable_protocol_repair_retry", "unknown"],
  ["enable_protocol_repair_retry", "enable_protocol_repair_retry"],
  [],
])("rejects invalid saved fields %j", (...fields) => {
  expect(parseNl2AgentState(saved(fields))).toBeNull();
});

it("does not accept policy as a prompt failure field", () => {
  expect(
    parseNl2AgentState(
      JSON.stringify({
        event: "prompt_generation_failed",
        agent_id: 42,
        failed_fields: ["enable_protocol_repair_retry"],
      })
    )
  ).toBeNull();
});

it.each([false, true])(
  "delivers policy save events through the shared creator adapter (persist=%s)",
  async (persist) => {
    const event = {
      event: "agent_draft_fields_saved",
      agent_id: 42,
      updated_fields: ["enable_protocol_repair_retry"],
    };
    service.runAgent.mockResolvedValueOnce(
      new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(
            new TextEncoder().encode(
              `data: ${JSON.stringify({ type: "nl2a_state", content: JSON.stringify(event) })}\n\n`
            )
          );
          controller.close();
        },
      }).getReader()
    );
    const receive = vi.fn();
    const options = {
      messages: [
        {
          id: "query",
          role: "user",
          content: [{ type: "text", text: "开启严格协议与重试" }],
        },
      ],
      abortSignal: new AbortController().signal,
      context: {},
      runConfig: {
        custom: {
          runtimeMode: "nl2agent",
          agentId: 42,
          modelId: "11",
          persistCreationHistory: persist,
          onNl2AgentState: receive,
        },
      },
      unstable_threadId: "creator-policy",
    } as unknown as ChatModelRunOptions;
    const result = remoteChatModelAdapter.run(options);
    if (Symbol.asyncIterator in result) {
      for await (const chunk of result) void chunk;
    } else await result;
    expect(receive).toHaveBeenCalledExactlyOnceWith(event);
    expect(service.runAgent.mock.calls.at(-1)![0]).toMatchObject({
      runtime_mode: "nl2agent",
      persist_history: persist,
      agent_id: 42,
    });
  }
);
