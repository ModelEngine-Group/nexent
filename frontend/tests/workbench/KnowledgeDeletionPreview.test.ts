// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { afterEach, expect, it, vi } from "vitest";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";

vi.mock("@/lib/auth", () => ({
  getAuthHeaders: () => ({ Authorization: "Bearer fixture" }),
  fetchWithAuth: (...args: Parameters<typeof fetch>) =>
    globalThis.fetch(...args),
}));
vi.mock("@/lib/logger", () => ({
  default: { log: vi.fn(), error: vi.fn(), warn: vi.fn(), info: vi.fn() },
}));
vi.mock("@/lib/session", () => ({ handleSessionExpired: vi.fn() }));
afterEach(() => vi.unstubAllGlobals());

it.each([
  [knowledgeBaseService, "/api/indices/"],
  [aidpKnowledgeService, "/api/aidp-mgmt/knowledge-bases/"],
] as const)(
  "uses the provider's existing service and route",
  async (service, prefix) => {
    const preview = {
      agents: [{ agent_id: 7, display_name: "Bound agent" }],
      hidden_agent_count: 1,
      total_agent_count: 2,
    };
    const request = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(preview)));
    vi.stubGlobal("fetch", request);
    await expect(service.previewBoundAgents("123 a")).resolves.toEqual(preview);
    expect(request).toHaveBeenCalledExactlyOnceWith(
      `${prefix}123%20a/bound_agents`,
      {
        method: "GET",
        headers: { Authorization: "Bearer fixture" },
      }
    );
  }
);

it.each([knowledgeBaseService, aidpKnowledgeService])(
  "returns an empty binding result unchanged",
  async (service) => {
    const empty = { agents: [], hidden_agent_count: 0, total_agent_count: 0 };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(empty)))
    );
    await expect(service.previewBoundAgents("missing")).resolves.toEqual(empty);
  }
);

it.each([knowledgeBaseService, aidpKnowledgeService])(
  "retains the existing null fallback when preview fails",
  async (service) => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("{}", { status: 500 }))
    );
    await expect(service.previewBoundAgents("idx")).resolves.toBeNull();
  }
);
