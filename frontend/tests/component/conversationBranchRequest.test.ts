// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { beforeEach, expect, test, vi } from "vitest";
import { conversationService } from "@/services/conversationService";

const mocks = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/lib/auth", () => ({
  getAuthHeaders: () => ({ Authorization: "Bearer test" }),
  fetchWithAuth: mocks.fetch,
}));
vi.mock("@/services/api", () => ({
  API_ENDPOINTS: { conversation: { branch: "/conversation/branch" } },
  ApiError: class extends Error {},
  fetchWithErrorHandling: vi.fn(),
}));
vi.mock("i18next", () => ({ t: (key: string) => key }));

beforeEach(() => {
  mocks.fetch.mockReset();
  mocks.fetch.mockResolvedValue({
    json: async () => ({ code: 0, data: { conversation_id: 42 } }),
  });
});

test("restored replies send their exact persisted ID and selected version", async () => {
  await expect(conversationService.branch(7, 2, "123", 1)).resolves.toEqual({
    conversation_id: 42,
  });
  expect(JSON.parse(mocks.fetch.mock.calls[0][1].body)).toEqual({
    conversation_id: 7,
    turn_index: 2,
    source_message_id: 123,
    answer_index: 1,
  });
});

test.each(["runtime-uuid", "msg_123", "9007199254740993"])(
  "live or unsafe ID %s uses the runtime answer version",
  async (id) => {
    await conversationService.branch(7, 2, id, 2);
    expect(JSON.parse(mocks.fetch.mock.calls[0][1].body)).toEqual({
      conversation_id: 7,
      turn_index: 2,
      answer_index: 2,
    });
  }
);

test("legacy callers retain the original request body", async () => {
  await conversationService.branch(7, 2);
  expect(JSON.parse(mocks.fetch.mock.calls[0][1].body)).toEqual({
    conversation_id: 7,
    turn_index: 2,
  });
});

test("failed branch requests do not return a new conversation", async () => {
  mocks.fetch.mockRejectedValue(new Error("Network failed"));
  await expect(conversationService.branch(7, 2, "123", 2)).rejects.toThrow(
    "Network failed"
  );
});
