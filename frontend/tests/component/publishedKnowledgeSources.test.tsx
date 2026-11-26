// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { afterEach, expect, it, vi } from "vitest";
import { fetchPublishedAgentList } from "@/services/agentConfigService";

vi.mock("@/lib/auth", () => ({ getAuthHeaders: () => ({}) }));
vi.mock("@/services/api", () => ({
  API_ENDPOINTS: { agent: { publishedList: "/agent/published_list" } },
}));
afterEach(() => vi.unstubAllGlobals());

it.each([
  undefined,
  { local: false, aidp: false },
  { local: true, aidp: false },
  { local: false, aidp: true },
])(
  "preserves published configuration flags without loading knowledge: %j",
  async (sources) => {
    const fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [
        {
          agent_id: 41,
          name: "agent",
          current_version_no: 3,
          knowledge_sources: sources,
        },
      ],
    });
    vi.stubGlobal("fetch", fetch);
    const result = await fetchPublishedAgentList();
    expect(result.success).toBe(true);
    expect(result.data[0]).toMatchObject({ id: "41", current_version_no: 3 });
    expect(result.data[0].knowledge_sources).toEqual(sources);
    expect(fetch).toHaveBeenCalledExactlyOnceWith("/agent/published_list", {
      headers: {},
    });
  }
);
