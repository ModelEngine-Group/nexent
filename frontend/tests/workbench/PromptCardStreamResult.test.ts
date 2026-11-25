// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { expect, it, vi } from "vitest";
import { ReadableStream } from "node:stream/web";
import type { ChatModelRunOptions } from "@assistant-ui/react";
import { remoteChatModelAdapter } from "@/app/newchat/adapter/remote-chat-model-adapter";

const runAgent = vi.hoisted(() => vi.fn());
vi.mock("@/services/conversationService", () => ({ conversationService: { runAgent } }));
vi.mock("@/lib/logger", () => ({ default: { log: vi.fn(), warn: vi.fn(), error: vi.fn() } }));

it.each(["applied", "cancelled", "error", "closed", "other-card"])(
  "uses server card results after HTTP acceptance: %s", async (scenario) => {
    const card = { subtype: "prompt_generation", agent_id: 42, conversation_id: "601",
      run_id: "run", card_id: scenario === "other-card" ? "other" : "card",
      prompt_revision: "revision", proposed_prompt: "Approved prompt", status: scenario };
    const events = scenario === "closed" ? [] : scenario === "error"
      ? [{ type: "error", content: "Save failed" }]
      : [{ type: "nl2a", content: JSON.stringify({ ...card, status: scenario === "other-card" ? "applied" : scenario }) }];
    runAgent.mockResolvedValueOnce(new ReadableStream<Uint8Array>({ start(controller) {
      for (const event of events) controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`));
      controller.close();
    } }).getReader());
    const onRunStarted = vi.fn();
    const onNl2AgentCardResult = vi.fn();
    const input = { messages: [{ id: "reply", role: "user", content: [{ type: "text", text: "Apply" }],
      metadata: { custom: { nl2agentCardAction: { type: "nl2agent_card_action", subtype: "prompt_generation",
        agent_id: 42, action: "apply", result: { card_id: "card", prompt_revision: "revision", prompt: "Approved prompt" } } } } }],
      abortSignal: new AbortController().signal, context: {}, unstable_threadId: "prompt-result",
      runConfig: { custom: { runtimeMode: "nl2agent", agentId: 42, modelId: "11", onRunStarted, onNl2AgentCardResult } },
    } as unknown as ChatModelRunOptions;
    const result = remoteChatModelAdapter.run(input);
    if (Symbol.asyncIterator in result) for await (const _ of result) { /* Consume the actual SSE projection. */ }
    else await result;
    expect(onRunStarted).toHaveBeenCalledOnce();
    expect(onNl2AgentCardResult).toHaveBeenCalledOnce();
    if (scenario === "applied" || scenario === "cancelled")
      expect(onNl2AgentCardResult.mock.calls[0][0].content.status).toBe(scenario);
    else expect(onNl2AgentCardResult).toHaveBeenCalledWith(null);
  }
);
