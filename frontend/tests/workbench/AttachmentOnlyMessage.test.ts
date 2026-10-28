// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { beforeEach, expect, it, vi } from "vitest";
import type { ChatModelRunOptions } from "@assistant-ui/react";
import { remoteChatModelAdapter } from "@/app/newchat/adapter/remote-chat-model-adapter";

const service = vi.hoisted(() => ({ runAgent: vi.fn() }));
vi.mock("@/services/conversationService", () => ({
  conversationService: service,
}));
vi.mock("@/lib/logger", () => ({
  default: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));

beforeEach(() => {
  service.runAgent.mockReset().mockResolvedValue({ type: "json", data: {} });
});

function chatOptions(messages: unknown[]): ChatModelRunOptions {
  return {
    messages,
    context: { config: {} },
    abortSignal: new AbortController().signal,
    runConfig: { custom: {} },
    unstable_threadId: "thread-a",
  } as unknown as ChatModelRunOptions;
}

async function consume(input: ChatModelRunOptions) {
  const run = remoteChatModelAdapter.run(input);
  if (Symbol.asyncIterator in run) {
    for await (const result of run) {
      void result;
    }
  } else await run;
}

function attachmentOnlyUserMessage() {
  return {
    id: "file-only",
    role: "user",
    content: [],
    attachments: [
      {
        id: "att-1",
        status: { type: "complete" },
        type: "text/plain",
        name: "zhishiku.txt",
        contentType: "text/plain",
        content: [
          {
            type: "file",
            filename: "zhishiku.txt",
            data: "http://minio/attachments/zhishiku.txt",
            mimeType: "text/plain",
          },
        ],
        object_name: "attachments/zhishiku.txt",
        url: "http://minio/attachments/zhishiku.txt",
        presigned_url: "http://minio/attachments/zhishiku.txt?token=1",
        size: 4812,
      },
    ],
  };
}

it("sends attachment-only messages instead of dropping them silently", async () => {
  await consume(chatOptions([attachmentOnlyUserMessage()]));

  expect(service.runAgent).toHaveBeenCalledTimes(1);
  const body = service.runAgent.mock.calls.at(-1)![0];
  expect(body.query).toBe("");
  expect(body.minio_files).toEqual([
    expect.objectContaining({
      name: "zhishiku.txt",
      object_name: "attachments/zhishiku.txt",
    }),
  ]);
});

it("still drops messages with neither text nor attachments", async () => {
  await consume(chatOptions([{ id: "empty", role: "user", content: [] }]));

  expect(service.runAgent).not.toHaveBeenCalled();
});
