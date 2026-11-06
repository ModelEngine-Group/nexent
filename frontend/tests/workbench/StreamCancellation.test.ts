// Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import { beforeEach, expect, it, vi } from "vitest";
import type { ChatModelRunOptions } from "@assistant-ui/react";
import {
  planRegistry,
  remoteChatModelAdapter,
} from "@/app/newchat/adapter/remote-chat-model-adapter";
import { ReadableStream } from "node:stream/web";
import {
  RemoteConversationHistoryAdapter,
  restoreHistoricalPlan,
} from "@/app/newchat/adapter/conversation-thread-list-adapter";
import type { ApiConversationDetail } from "@/types/conversation";
import type { SourceAttributes } from "@/types/source";

const service = vi.hoisted(() => ({ runAgent: vi.fn(), stop: vi.fn() }));
vi.mock("@/services/conversationService", () => ({
  CONVERSATION_PAGE_SIZE: 20,
  conversationService: service,
}));
vi.mock("@/lib/logger", () => ({
  default: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));
beforeEach(() => {
  planRegistry.set(null);
  service.runAgent.mockReset();
  service.stop.mockReset().mockResolvedValue(undefined);
});

it("preserves a restored stopped plan through an Execution follow-up", async () => {
  const plan = {
    title: "Release checks",
    steps: [
      { id: "check", title: "Verify deployment", status: "completed" as const },
    ],
  };
  planRegistry.set(plan);
  service.runAgent.mockImplementationOnce(async () =>
    new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(
            'data: {"type":"final_answer","content":"EXEC-follow-up"}\n\n'
          )
        );
        controller.close();
      },
    }).getReader()
  );
  const result = await consume(
    options(new AbortController(), {
      threadId: "12",
      agentId: 7,
      enablePlan: false,
    })
  );
  expect(JSON.stringify(result)).toContain("EXEC-follow-up");
  expect(planRegistry.data).toEqual(plan);
});

it("clears the prior plan when navigating to a new or unrelated conversation", () => {
  const plan = {
    title: "Old plan",
    steps: [{ id: "old", title: "Old step", status: "completed" }],
  };
  planRegistry.set(plan);
  restoreHistoricalPlan();
  expect(planRegistry.data).toBeNull();
  planRegistry.set(plan);
  restoreHistoricalPlan("unrelated-thread");
  expect(planRegistry.data).toBeNull();
});

it("replaces a stopped plan when the next planning turn emits a new plan", async () => {
  planRegistry.set({
    title: "Old plan",
    steps: [{ id: "old", title: "Old step", status: "completed" }],
  });
  service.runAgent.mockImplementationOnce(async () =>
    new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(
            `data: ${JSON.stringify({
              type: "plan",
              content: JSON.stringify({
                title: "New plan",
                steps: [{ id: "new", title: "New step", status: "pending" }],
              }),
            })}\n\n`
          )
        );
        controller.close();
      },
    }).getReader()
  );
  await consume(
    options(new AbortController(), {
      threadId: "12",
      agentId: 7,
      enablePlan: true,
    })
  );
  expect(planRegistry.data?.title).toBe("New plan");
  expect(planRegistry.data?.steps.map((step) => step.id)).toEqual(["new"]);
});

function options(
  controller: AbortController,
  custom: Record<string, unknown> = {}
) {
  return {
    messages: [
      {
        id: "question",
        role: "user",
        content: [{ type: "text", text: "hello" }],
      },
    ],
    abortSignal: controller.signal,
    context: {},
    runConfig: { custom },
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

it("UT-FE-WB-003 interleaved conversation streams retain only their own messages", async () => {
  const streams = new Map<
    number,
    ReadableStreamDefaultController<Uint8Array>
  >();
  service.runAgent.mockImplementation(async (body) =>
    new ReadableStream<Uint8Array>({
      start(controller) {
        streams.set(body.conversation_id, controller);
      },
    }).getReader()
  );
  const a = consume(
    options(new AbortController(), { threadId: "12", resume: true })
  );
  const b = consume(
    options(new AbortController(), { threadId: "13", resume: true })
  );
  const emit = (id: number, content: string) =>
    streams
      .get(id)!
      .enqueue(
        new TextEncoder().encode(
          `data: ${JSON.stringify({ type: "model_output", content })}\n\n`
        )
      );
  emit(12, "alpha-only");
  emit(13, "beta-only");
  streams.get(13)!.close();
  emit(12, "alpha-final");
  streams.get(12)!.close();
  const [resultA, resultB] = await Promise.all([a, b]);
  expect(JSON.stringify(resultA)).toContain("alpha-only");
  expect(JSON.stringify(resultA)).toContain("alpha-final");
  expect(JSON.stringify(resultA)).not.toContain("beta-only");
  expect(JSON.stringify(resultB)).toContain("beta-only");
  expect(JSON.stringify(resultB)).not.toContain("alpha-only");
  expect(service.runAgent).toHaveBeenCalledTimes(2);
});

it("UT-FE-WB-003 detaching before response headers never stops the background run", async () => {
  const controller = new AbortController();
  const stopped = vi.fn();
  service.runAgent.mockImplementation(
    async (_body, _signal, conversationId, _version, runId) => {
      controller.abort({ detach: true });
      conversationId("12");
      runId("run-a");
      return { type: "json", data: {} };
    }
  );
  await consume(options(controller, { onGenerationStopped: stopped }));
  expect(service.stop).not.toHaveBeenCalled();
  expect(stopped).not.toHaveBeenCalled();
});

it("UT-FE-WB-004 stopping before response headers stops only the assigned run once", async () => {
  const controller = new AbortController();
  const stopped = vi.fn();
  service.runAgent.mockImplementation(
    async (_body, _signal, conversationId, _version, runId) => {
      controller.abort();
      conversationId("12");
      runId("run-a");
      throw Object.assign(new Error("cancelled"), { name: "AbortError" });
    }
  );
  await consume(options(controller, { onGenerationStopped: stopped }));
  expect(service.stop).toHaveBeenCalledExactlyOnceWith(12);
  expect(stopped).toHaveBeenCalledExactlyOnceWith(12);
});

it("UT-FE-WB-003 returning to a running conversation uses resume instead of starting a new run", async () => {
  service.runAgent.mockResolvedValue({
    type: "json",
    data: { status: "completed" },
  });
  await consume(
    options(new AbortController(), { threadId: "12", resume: true })
  );
  expect(service.runAgent).toHaveBeenCalledOnce();
  expect(service.runAgent.mock.calls[0][0]).toMatchObject({
    conversation_id: 12,
    is_resume: true,
  });
  expect(service.stop).not.toHaveBeenCalled();
});

it("SU-AC-07 does not revive removed controls from a stale ModelContext", async () => {
  service.runAgent.mockResolvedValue({
    type: "json",
    data: { status: "completed" },
  });
  const runOptions = {
    ...options(new AbortController(), { agentId: 7 }),
    context: {
      config: {
        modelName: "12",
        deepThinking: true,
        reasoningEffort: "medium",
      },
    },
  } as unknown as ChatModelRunOptions;

  await consume(runOptions);

  expect(service.runAgent.mock.calls[0][0]).toMatchObject({
    model_id: 12,
  });
  expect(service.runAgent.mock.calls[0][0]).not.toHaveProperty(
    "generation_config"
  );
});

const sourceHits = [
  {
    title: "same.pdf",
    filename: "same.pdf",
    text: "First hit",
    url: "",
    source_type: "file",
    search_type: "aidp_search",
    tool_sign: "j",
    cite_index: 1,
    published_date: "2026-10-14",
    score_details: {
      metadata: {
        count: 0,
        enabled: false,
        nested: { values: [0, false, "中文"] },
      },
      chunk_id: "first-hit",
    },
  },
  {
    title: "same.pdf",
    filename: "same.pdf",
    text: "Second hit",
    url: "",
    source_type: "file",
    search_type: "aidp_search",
    tool_sign: "j",
    cite_index: 2,
    published_date: "2026-10-13",
    score_details: {
      metadata: { count: 1, source: "business source" },
      chunk_id: "second-hit",
    },
  },
];
type SourceTestPart = SourceAttributes & {
  type: string;
  url?: string;
  imageKey?: string;
  publishedDate?: string;
  searchContent?: SourceAttributes[];
};

it.each([true, false])(
  "retains per-hit source snapshots in streamed tool and answer projections (terminated=%s)",
  async (terminated) => {
    const events = [
      { type: "tool", content: "aidp_search", tool_call_id: "call-search" },
      {
        type: "search_content",
        content: JSON.stringify(sourceHits),
        tool_call_id: "call-search",
      },
    ];
    service.runAgent.mockImplementationOnce(async () =>
      new ReadableStream<Uint8Array>({
        start(controller) {
          const data =
            events
              .map((event) => `data: ${JSON.stringify(event)}`)
              .join("\n\n") + (terminated ? "\n\n" : "");
          controller.enqueue(new TextEncoder().encode(data));
          controller.close();
        },
      }).getReader()
    );
    const output = await consume(
      options(new AbortController(), { threadId: "12", agentId: 7 })
    );
    const parts = output.at(-1)?.content as unknown as SourceTestPart[];
    const sources = parts.filter((part) => part.type === "source");
    expect(sources.map((part) => part.sourceMetadata)).toEqual(
      sourceHits.map((hit) => hit.score_details.metadata)
    );
    expect(sources.map((part) => part.sourceReference?.chunk_id)).toEqual([
      "first-hit",
      "second-hit",
    ]);
    expect(sources.every((part) => part.searchType === "aidp_search")).toBe(
      true
    );
    expect(sources.map((part) => part.publishedDate)).toEqual([
      "2026-10-14",
      "2026-10-13",
    ]);
    const tool = parts.find((part) => part.type === "tool-call")!;
    expect(tool.searchContent?.map((part) => part.sourceMetadata)).toEqual(
      sourceHits.map((hit) => hit.score_details.metadata)
    );
  }
);

it("restores per-hit snapshots into historical tool content and final source parts", async () => {
  const detail = {
    conversation_id: "42",
    create_time: 0,
    message: [
      {
        role: "assistant",
        message_id: 5,
        message: [
          { type: "tool", content: "aidp_search", tool_call_id: "call-search" },
          {
            type: "search_content_placeholder",
            content: JSON.stringify({ unit_id: 77 }),
            tool_call_id: "call-search",
          },
          { type: "final_answer", content: "Answer [[j1]][[j2]]" },
        ],
        search: sourceHits,
        searchByUnitId: { "77": sourceHits },
      },
    ],
  } as ApiConversationDetail;
  const adapter = new RemoteConversationHistoryAdapter(
    () => "42",
    async () => ({ remoteId: "42", externalId: "42" }),
    async () => detail
  );
  const history = await adapter.load();
  const parts = history.messages[0].message
    .content as unknown as SourceTestPart[];
  const sources = parts.filter((part) => part.type === "source");
  expect(sources.map((part) => part.sourceMetadata)).toEqual(
    sourceHits.map((hit) => hit.score_details.metadata)
  );
  expect(sources.map((part) => part.sourceReference?.chunk_id)).toEqual([
    "first-hit",
    "second-hit",
  ]);
  expect(sources.every((part) => part.searchType === "aidp_search")).toBe(true);
  expect(sources.map((part) => part.publishedDate)).toEqual([
    "2026-10-14",
    "2026-10-13",
  ]);
  expect(
    parts
      .find((part) => part.type === "tool-call")
      ?.searchContent?.map((part) => part.sourceMetadata)
  ).toEqual(sourceHits.map((hit) => hit.score_details.metadata));
});

it("keeps image metadata attached to its URL when picture events arrive out of order", async () => {
  const images = sourceHits.map((hit, index) => ({
    ...hit,
    url: `https://aidp.example/images/${index}.png`,
    image_key: `j${index + 1}`,
    score_details: { ...hit.score_details, chunk_type: "image" },
  }));
  const events = [
    { type: "search_content", content: JSON.stringify(images) },
    {
      type: "picture_web",
      content: JSON.stringify({
        images_url: images.map((hit) => hit.url).reverse(),
      }),
    },
  ];
  service.runAgent.mockImplementationOnce(async () =>
    new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(
            events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("")
          )
        );
        controller.close();
      },
    }).getReader()
  );
  const output = await consume(
    options(new AbortController(), { threadId: "12", agentId: 7 })
  );
  const parts = output.at(-1)?.content as unknown as SourceTestPart[];
  const sources = parts.filter((part) => part.type === "source");
  expect(
    sources.map((part) => [part.url, part.imageKey, part.sourceMetadata])
  ).toEqual(
    [...images]
      .reverse()
      .map((hit) => [hit.url, hit.image_key, hit.score_details.metadata])
  );
});

it("restores separate image hits with the same URL and different metadata", async () => {
  const imageUrl = "https://aidp.example/images/shared.png";
  const images = sourceHits.map((hit, index) => ({
    ...hit,
    url: imageUrl,
    image_key: `j${index + 1}`,
    score_details: { ...hit.score_details, chunk_type: "image" },
  }));
  const detail = {
    conversation_id: "42",
    create_time: 0,
    message: [
      {
        role: "assistant",
        message_id: 5,
        message: [
          {
            type: "picture_web",
            content: JSON.stringify({ images_url: [imageUrl] }),
          },
        ],
        search: images,
        picture: [imageUrl],
      },
    ],
  } as ApiConversationDetail;
  const adapter = new RemoteConversationHistoryAdapter(
    () => "42",
    async () => ({ remoteId: "42", externalId: "42" }),
    async () => detail
  );
  const history = await adapter.load();
  const parts = history.messages[0].message
    .content as unknown as SourceTestPart[];
  expect(
    parts
      .filter((part) => part.type === "source")
      .map((part) => [part.imageKey, part.sourceMetadata])
  ).toEqual(images.map((hit) => [hit.image_key, hit.score_details.metadata]));
});
