// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { afterEach, expect, it, vi } from "vitest";
import knowledgeBaseService from "@/services/knowledgeBaseService";

vi.mock("@/lib/auth", () => ({
  getAuthHeaders: () => ({ Authorization: "Bearer fixture" }),
  fetchWithAuth: (...args: Parameters<typeof fetch>) =>
    globalThis.fetch(...args),
}));
vi.mock("@/lib/logger", () => ({
  default: { error: vi.fn() },
}));
afterEach(() => vi.unstubAllGlobals());

function stubSummaryResponse(events: object[]) {
  const body = events
    .map((event) => `data: ${JSON.stringify(event)}\r\n\r\n`)
    .join("");
  const bytes = new TextEncoder().encode(body);
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (let offset = 0; offset < bytes.length; offset += 7) {
        controller.enqueue(bytes.slice(offset, offset + 7));
      }
      controller.close();
    },
  });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(stream)));
}

it("reassembles split summary events and retains quotes, line breaks and non-ASCII text", async () => {
  stubSummaryResponse([
    { status: "success", message: '第一段\n"quoted"' },
    { status: "completed", message: "\n第二段" },
  ]);
  const progress = vi.fn();
  await expect(
    knowledgeBaseService.summaryIndex("test-kb", 1000, progress, 4)
  ).resolves.toBe('第一段\n"quoted"\n第二段');
  expect(progress.mock.calls.flat()).toEqual(['第一段\n"quoted"', "\n第二段"]);
});

it("rejects an error frame even after receiving partial content", async () => {
  stubSummaryResponse([
    { status: "success", message: "Partial content" },
    { status: "error", message: "Runtime unavailable" },
  ]);
  await expect(knowledgeBaseService.summaryIndex("test-kb")).rejects.toThrow(
    "Runtime unavailable"
  );
});

it("rejects an interrupted stream that never sends a completion frame", async () => {
  stubSummaryResponse([{ status: "success", message: "Partial content" }]);
  await expect(knowledgeBaseService.summaryIndex("test-kb")).rejects.toThrow();
});
