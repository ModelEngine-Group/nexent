// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { afterEach, expect, it, vi } from "vitest";
import { getMcpServerList } from "@/services/mcpService";

vi.mock("@/services/api", () => ({
  API_ENDPOINTS: { mcp: { list: "/api/mcp/list" } },
}));
vi.mock("@/lib/logger", () => ({ default: { error: vi.fn() } }));

afterEach(() => vi.unstubAllGlobals());

it.each(["pending_review", "rejected"])(
  "preserves first-time submission status %s without a marketplace record",
  async (status) => {
    const review = { review_id: "41", status };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => ({
          status: "success",
          remote_mcp_server_list: [{ mcp_id: 7, latest_review: review }],
        }),
      })),
    );
    const result = await getMcpServerList();
    expect(result.data[0].latest_review).toEqual(review);
    expect(result.data[0].market_id).toBeUndefined();
  },
);

it("keeps an absent review absent for a service never submitted", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({
        status: "success",
        remote_mcp_server_list: [{ mcp_id: 7 }],
      }),
    })),
  );
  expect((await getMcpServerList()).data[0].latest_review).toBeUndefined();
});
