// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { afterEach, expect, it, vi } from "vitest";
import { API_ENDPOINTS } from "@/services/api";
import { evolutionService } from "@/services/evolutionService";

vi.mock("@/lib/auth", () => ({ getAuthHeaders: () => ({}) }));
afterEach(() => vi.restoreAllMocks());

it("offers only published agents editable under the current draft permissions", async () => {
  const editable = { agent_id: 1, name: "Editable", permission: "EDIT", current_version_no: 4 };
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json([
    editable,
    { agent_id: 2, name: "Shared read-only", permission: "READ_ONLY", current_version_no: 1 },
    { agent_id: 3, name: "Unpublished", permission: "EDIT", current_version_no: null },
    { agent_id: 4, name: "Unknown permission", current_version_no: 2 },
  ]));

  expect(await evolutionService.agents()).toEqual([editable]);
  expect(fetch).toHaveBeenCalledWith(API_ENDPOINTS.agent.list, expect.objectContaining({ method: "GET" }));
});
