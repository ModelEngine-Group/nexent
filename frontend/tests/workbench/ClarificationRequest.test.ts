// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { afterEach, expect, it, vi } from "vitest";
import { conversationService } from "@/services/conversationService";
import type { ClarificationResponse } from "@/types/clarification";

vi.mock("@/lib/auth", () => ({
  getAuthHeaders: () => ({ "Content-Type": "application/json" }),
  fetchWithAuth: (...args: Parameters<typeof fetch>) =>
    globalThis.fetch(...args),
}));
afterEach(() => vi.unstubAllGlobals());

const response: ClarificationResponse = {
  schema_version: 1,
  form: {
    schema_version: 1,
    questions: [
      {
        id: "goal",
        type: "text",
        title: "Goal?",
        required: true,
        options: [],
        allow_other: false,
        placeholder: "",
      },
    ],
  },
  unit_index: 7,
  answers: [{ questionId: "goal", value: "Saved goal", otherText: null }],
};

it("serializes structured answers alongside readable text through the normal agent API", async () => {
  const fetch = vi.fn().mockResolvedValue(
    new Response("data: {}\n\n", {
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
    })
  );
  vi.stubGlobal("fetch", fetch);
  await conversationService.runAgent({
    query: "Readable answers",
    history: [],
    conversation_id: 42,
    clarification_response: response,
  });
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toMatchObject({
    query: "Readable answers",
    conversation_id: 42,
    clarification_response: response,
  });
});

it.each(["ordinary", "resume", "nl2agent", "nl2skill"] as const)(
  "keeps %s requests free of unrelated clarification response fields",
  async (mode) => {
    const fetch = vi.fn().mockResolvedValue(
      new Response("data: {}\n\n", {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      })
    );
    vi.stubGlobal("fetch", fetch);
    await conversationService.runAgent({
      query: "Ordinary",
      history: [],
      conversation_id: 42,
      ...(mode === "resume"
        ? { is_resume: true, clarification_response: response }
        : mode === "ordinary"
          ? {}
          : { runtime_mode: mode, clarification_response: response }),
    });
    expect(JSON.parse(fetch.mock.calls[0][1].body)).not.toHaveProperty(
      "clarification_response"
    );
  }
);
