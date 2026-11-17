// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { beforeEach, expect, it, vi } from "vitest";
import { ReadableStream } from "node:stream/web";
import type {
  ChatModelRunOptions,
  ChatModelRunResult,
} from "@assistant-ui/react";
import type { ApiConversationDetail } from "@/types/conversation";

const runAgent = vi.hoisted(() => vi.fn());
vi.mock("@/services/conversationService", () => ({
  conversationService: { runAgent },
}));
vi.mock("@/lib/logger", () => ({
  default: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));

import {
  remoteChatModelAdapter,
  searchSourcesRegistry,
  searchImagesRegistry,
  conversationSourcesRegistry,
} from "@/app/newchat/adapter/remote-chat-model-adapter";
import { RemoteConversationHistoryAdapter } from "@/app/newchat/adapter/conversation-thread-list-adapter";
import { getMessageSources } from "@/app/newchat/ui/message-sources";

const file_ref = { knowledge_id: 7, file_id: "a".repeat(32), file_version: 2 };
const image_ref = {
  space: "files",
  key: "kb/image.png",
  version: "v1",
  sha256: "b".repeat(64),
};
const source = {
  file_ref,
  url: "",
  title: "report.pdf",
  filename: "report.pdf",
  source_type: "file",
  cite_index: 1,
  tool_sign: "a",
  text: "report",
  location: { page: 2 },
};
const image = {
  ...source,
  image_ref,
  cite_index: 2,
  score_details: { chunk_type: "image" },
};
const rejectedImage = {
  ...image,
  cite_index: 3,
  image_ref: { ...image_ref, key: "kb/rejected.png" },
};
const pictures = {
  images_url: [],
  images_ref: [{ file_ref, image_ref, cite_index: 2, tool_sign: "a" }],
};

beforeEach(() => {
  vi.clearAllMocks();
  searchSourcesRegistry.clear();
  searchImagesRegistry.clear();
  conversationSourcesRegistry.clear();
});

it.each([
  { pictureFirst: false, tail: undefined },
  { pictureFirst: true, tail: undefined },
  { pictureFirst: false, tail: "search_content" },
  { pictureFirst: true, tail: "picture_web" },
])(
  "preserves fixed references when picture-first=$pictureFirst and unterminated tail=$tail",
  async ({ pictureFirst, tail }) => {
    const search = {
      type: "search_content",
      content: JSON.stringify([source, image, rejectedImage]),
    };
    const picture = { type: "picture_web", content: JSON.stringify(pictures) };
    let events = [
      ...(pictureFirst ? [picture, search] : [search, picture]),
      { type: "final_answer", content: "Report [a1]" },
      { type: "done" },
    ];
    if (tail)
      events = [
        ...events.filter((event) => event.type !== tail),
        tail === "search_content" ? search : picture,
      ];
    runAgent.mockResolvedValueOnce(
      new ReadableStream<Uint8Array>({
        start(controller) {
          for (const [index, event] of events.entries())
            controller.enqueue(
              new TextEncoder().encode(
                `data: ${JSON.stringify(event)}${tail && index === events.length - 1 ? "" : "\n\n"}`
              )
            );
          controller.close();
        },
      }).getReader()
    );
    const run = remoteChatModelAdapter.run({
      messages: [
        {
          id: "question",
          role: "user",
          content: [{ type: "text", text: "Search" }],
        },
      ],
      abortSignal: new AbortController().signal,
      context: {},
      runConfig: { custom: {} },
      unstable_threadId: "local",
    } as unknown as ChatModelRunOptions);
    let final: ChatModelRunResult | undefined;
    if (Symbol.asyncIterator in run)
      for await (const result of run) final = result;
    else final = await run;
    const all = [...searchSourcesRegistry.values()].flat();
    expect(all.find((item) => !item.isImage)).toMatchObject({
      fileRef: file_ref,
      sourceLocation: { page: 2 },
    });
    expect(all.filter((item) => item.isImage)).toEqual([
      expect.objectContaining({
        fileRef: file_ref,
        imageRef: image_ref,
        citeIndex: 2,
        toolSign: "a",
        title: "report.pdf",
      }),
    ]);
    expect(JSON.stringify(final?.content)).toContain("__knowledge_image__/a2");
    expect(JSON.stringify(final?.content)).not.toContain("rejected.png");
  }
);

it("restores history references and selected images into the source panel model", async () => {
  const detail = {
    conversation_id: "42",
    create_time: 0,
    message: [
      {
        role: "assistant",
        message_id: 10,
        status: "completed",
        search: [source, image, rejectedImage],
        message: [
          {
            type: "picture_web",
            content: JSON.stringify(pictures),
            unit_index: 0,
          },
          { type: "final_answer", content: "Report [a1]", unit_index: 1 },
        ],
      },
    ],
  } as unknown as ApiConversationDetail;
  const history = await new RemoteConversationHistoryAdapter(
    () => "42",
    async () => ({ remoteId: "42", externalId: "42" }),
    async () => detail
  ).load();
  const message = history.messages[0].message;
  const model = getMessageSources(
    message.id,
    message.content,
    conversationSourcesRegistry.get(message.id)
  );
  expect(model.sources).toEqual([
    expect.objectContaining({ fileRef: file_ref, sourceLocation: { page: 2 } }),
  ]);
  expect(model.images).toEqual([
    expect.objectContaining({
      fileRef: file_ref,
      imageRef: image_ref,
      citeIndex: 2,
    }),
  ]);
  expect(JSON.stringify(message.content)).toContain("__knowledge_image__/a2");
  const textParts = message.content.filter((part) => part.type === "text");
  expect(textParts[0]).toMatchObject({ text: "Report [a1]" });
  const markerIndex = message.content.findIndex(
    (part) => part.type === "text" && part.text.includes("__knowledge_image__")
  );
  expect(markerIndex).toBeLessThan(
    message.content.findIndex((part) => part.type === "source")
  );
  expect(JSON.stringify(model)).not.toContain("rejected.png");
});
