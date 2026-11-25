// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { beforeEach, expect, it, vi } from "vitest";
import { conversationService } from "@/services/conversationService";

const request = vi.hoisted(() => vi.fn());
vi.mock("@/services/api", () => ({
  API_ENDPOINTS: {
    conversation: { creatorHistories: "/api/conversation/creator_histories" },
  },
  fetchWithErrorHandling: request,
  ApiError: class extends Error {},
}));
vi.mock("@/lib/auth", () => ({
  getAuthHeaders: () => ({ Authorization: "Bearer fixture" }),
  fetchWithAuth: vi.fn(),
}));
beforeEach(() => {
  request.mockReset();
});

it.each(["agent", "skill"] as const)(
  "sends only kind and target_id for %s histories",
  async (kind) => {
    const data = { items: [], total: 0 };
    request.mockResolvedValue({ json: async () => ({ code: 0, data }) });
    expect(await conversationService.getCreatorHistories(kind, 42)).toEqual(
      data
    );
    const [url, options] = request.mock.calls[0];
    expect(url).toBe(
      `/api/conversation/creator_histories?kind=${kind}&target_id=42`
    );
    expect(options.headers.Authorization).toBe("Bearer fixture");
  }
);

it("propagates request failures", async () => {
  request.mockRejectedValue(new Error("offline"));
  await expect(
    conversationService.getCreatorHistories("skill", 42)
  ).rejects.toThrow("offline");
});
