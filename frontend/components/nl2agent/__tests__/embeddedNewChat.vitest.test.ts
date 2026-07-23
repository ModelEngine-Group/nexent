import type { ChatModelRunResult } from "@assistant-ui/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  envelopeFromMessageMetadata,
  parseStructuredNl2AgentEnvelope,
} from "@/lib/chat/nl2agentCardEvent";
import { remoteChatModelAdapter } from "../../../app/[locale]/newchat/adapter/remote-chat-model-adapter";

const envelope = {
  schema_version: 1,
  draft_agent_id: 202,
  workflow_revision: 9,
  cards: [
    {
      card_type: "model_selection",
      card_key: "model_selection",
      payload: { agent_id: 202 },
    },
  ],
};

describe("embedded newchat structured NL2AGENT events", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("accepts only a scoped structured envelope from nl2agent_card metadata", () => {
    expect(parseStructuredNl2AgentEnvelope(envelope)).toEqual(envelope);
    expect(
      envelopeFromMessageMetadata("nl2agent_card", {
        nl2agent_card: envelope,
      })
    ).toEqual(envelope);
    expect(
      envelopeFromMessageMetadata("chat", { nl2agent_card: envelope })
    ).toBe(undefined);
    expect(
      parseStructuredNl2AgentEnvelope({ ...envelope, schema_version: 2 })
    ).toBe(undefined);
  });

  it("consumes one persisted nl2agent_message event without fence parsing", async () => {
    const event = {
      type: "nl2agent_message",
      content: {
        message_id: 4242,
        conversation_id: 5,
        message_index: 3,
        message_content: "Choose the models for this agent.",
        message_type: "nl2agent_card",
        message_metadata: { nl2agent_card: envelope },
        status: "completed",
      },
    };
    const stream = `data: ${JSON.stringify(event)}\n\n`;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(stream, {
            status: 200,
            headers: { "content-type": "text/event-stream" },
          })
      )
    );

    const result = remoteChatModelAdapter.run({
      messages: [
        {
          id: "user-1",
          role: "user",
          content: [{ type: "text", text: "Build an agent" }],
          attachments: [],
          metadata: { custom: {} },
          createdAt: new Date(0),
        },
      ],
      abortSignal: new AbortController().signal,
      context: { config: {} },
      runConfig: {
        custom: { agentId: 1, draftAgentId: 202, threadId: "5" },
      },
      unstable_getMessage: () => {
        throw new Error("not used");
      },
    } as never);
    const updates: ChatModelRunResult[] = [];
    for await (const update of result as AsyncGenerator<ChatModelRunResult>) {
      updates.push(update);
    }

    const finalUpdate = updates.at(-1);
    expect(finalUpdate?.metadata?.custom).toMatchObject({
      persistedMessageId: 4242,
      nl2agentCardEnvelope: envelope,
    });
    expect(finalUpdate?.content).toEqual([
      expect.objectContaining({
        type: "text",
        text: "Choose the models for this agent.",
        nl2agentCardEnvelope: envelope,
      }),
    ]);
  });
});
