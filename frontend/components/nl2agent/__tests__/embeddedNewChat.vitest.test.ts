import type { ChatModelRunResult } from "@assistant-ui/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  nl2AgentComponentsByLanguage,
  preprocessNl2AgentFences,
  resolveNl2AgentPersistedMessageId,
} from "../Nl2AgentFenceRenderer";
import { remoteChatModelAdapter } from "../../../app/[locale]/newchat/adapter/remote-chat-model-adapter";

describe("embedded newchat NL2AGENT fence integration", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("routes every hyphenated card fence through a word-only language alias", () => {
    const canonicalLanguages = [
      "nl2agent-agent-identity",
      "nl2agent-finalize",
      "nl2agent-local-resources",
      "nl2agent-model-selection",
      "nl2agent-requirements-summary",
      "nl2agent-web-mcp",
      "nl2agent-web-mcps",
      "nl2agent-web-skill",
      "nl2agent-web-skills",
    ];

    for (const language of canonicalLanguages) {
      const processed = preprocessNl2AgentFences(
        `Before\n\`\`\`${language}\n{}\n\`\`\`\nAfter`
      );
      const alias = language.replaceAll("-", "");

      expect(processed).toContain(`\`\`\`${alias}\n`);
      expect(nl2AgentComponentsByLanguage[alias]).toBeDefined();
    }
  });

  it("does not rewrite unknown or inline NL2AGENT text", () => {
    const content =
      "Use `nl2agent-finalize` here.\n```nl2agent-unknown\n{}\n```";

    expect(preprocessNl2AgentFences(content)).toBe(content);
  });

  it("prefers persisted metadata over the assistant-ui runtime message ID", () => {
    expect(resolveNl2AgentPersistedMessageId(4242, "aui-generated-id")).toBe(
      4242
    );
    expect(resolveNl2AgentPersistedMessageId(undefined, "73")).toBe(73);
    expect(
      resolveNl2AgentPersistedMessageId(undefined, "aui-generated-id")
    ).toBeUndefined();
  });

  it("carries the persisted assistant message ID in supported result metadata", async () => {
    const stream = [
      'data: {"type":"assistant_message_created","content":{"message_id":4242}}',
      "",
      'data: {"type":"final_answer","content":"Agent card ready"}',
      "",
    ].join("\n");
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
    });
    expect(finalUpdate?.metadata?.timing).toBeDefined();
    expect(finalUpdate).not.toHaveProperty("messageId");
  });
});
