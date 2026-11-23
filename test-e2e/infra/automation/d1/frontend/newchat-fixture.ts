import { ReadableStream } from "node:stream/web";
import { vi } from "vitest";
import type { ChatModelRunOptions } from "@assistant-ui/react";

vi.mock("@/services/conversationService", () => ({
  CONVERSATION_PAGE_SIZE: 20,
  conversationService: { runAgent: vi.fn(), stop: vi.fn() },
}));
vi.mock("@/lib/logger", () => ({
  default: {
    log: vi.fn(),
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  },
}));

import { conversationService } from "@/services/conversationService";
import { remoteChatModelAdapter } from "@/app/newchat/adapter/remote-chat-model-adapter";
import { RemoteConversationHistoryAdapter } from "@/app/newchat/adapter/conversation-thread-list-adapter";

export type Event = { type: string; content: string; [key: string]: unknown };

// Only the external transport is substituted; production adapters parse every event.
export async function collectStream(events: Event[]) {
  vi.mocked(conversationService.runAgent).mockResolvedValueOnce(
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const event of events) {
          controller.enqueue(
            new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`),
          );
        }
        controller.close();
      },
    }).getReader() as never,
  );
  const snapshots: any[] = [];
  const run = remoteChatModelAdapter.run({
    messages: [
      {
        id: "question",
        role: "user",
        content: [{ type: "text", text: "hello" }],
      },
    ],
    abortSignal: new AbortController().signal,
    context: {},
    runConfig: { custom: { threadId: "901", agentId: 1 } },
  } as unknown as ChatModelRunOptions);
  if (!(Symbol.asyncIterator in run))
    throw new Error("Expected streaming adapter");
  for await (const result of run) snapshots.push(structuredClone(result));
  return snapshots;
}

export function summaryEvent(payload: unknown): Event {
  return { type: "history_summary", content: JSON.stringify(payload) };
}

export function summaryParts(result: any): any[] {
  return result.content.filter(
    (part: any) => part.type === "data" && part.name === "history-summary",
  );
}

export async function restoreHistory(messages: unknown[]) {
  const adapter = new RemoteConversationHistoryAdapter(
    () => "901",
    async () => ({ remoteId: "901" }),
    async () => ({ conversation_id: 901, message: messages }) as never,
  );
  return adapter.load();
}
