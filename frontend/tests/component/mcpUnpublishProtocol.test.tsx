// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { beforeEach, expect, it, vi } from "vitest";
import { unpublishCommunityMcpTool } from "@/services/mcpToolsService";

const request = vi.hoisted(() => vi.fn());
vi.mock("@/lib/auth", () => ({ fetchWithAuth: request }));
vi.mock("@/services/resourceReviewService", () => ({
  submitResourceReview: vi.fn(),
}));
vi.mock("@/services/api", () => ({
  ApiError: class extends Error {},
  API_ENDPOINTS: {
    mcpTools: {
      communityStatus: (id: number) => `/api/mcp-tools/community/${id}/status`,
    },
  },
}));

beforeEach(() => request.mockReset());

it("unpublishes by status change and preserves the warehouse record", async () => {
  request.mockResolvedValue({
    ok: true,
    json: async () => ({ status: "success" }),
  });
  await unpublishCommunityMcpTool(41);
  expect(request).toHaveBeenCalledWith("/api/mcp-tools/community/41/status", {
    method: "PATCH",
    body: JSON.stringify({ status: "not_shared" }),
  });
});

it("does not report a failed unpublish as success", async () => {
  request.mockResolvedValue({
    ok: false,
    json: async () => ({ status: "error" }),
  });
  await expect(unpublishCommunityMcpTool(41)).rejects.toThrow(
    "Failed to unpublish"
  );
});
