// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { fetchSkills } from "@/services/agentConfigService";
import { fetchSkillsList } from "@/services/skillService";
const request = vi.hoisted(() => vi.fn());

vi.mock("@/lib/auth", () => ({
  fetchWithAuth: vi.fn(),
  getAuthHeaders: () => ({}),
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("fetch", request);
  request.mockImplementation(
    async () =>
      new Response(
        JSON.stringify({
          skills: [
            {
              skill_id: 7,
              name: "Configured skill",
              description: "Summary",
              tags: [],
              source: "local",
              config_schemas: [
                { name: "region", type: "string", required: true },
              ],
              config_values: { region: "west" },
            },
          ],
        }),
        { status: 200 }
      )
  );
});

it("preserves the default list URL and opts into mount summaries explicitly", async () => {
  await fetchSkills();
  expect(String(request.mock.calls[0][0])).toMatch(/\/skills$/);
  const skills = await fetchSkillsList("tenant with space", "mount");
  const url = String(request.mock.calls[1][0]);
  expect(url).toContain("view=mount");
  expect(new URL(url, "http://localhost").searchParams.get("tenant_id")).toBe(
    "tenant with space"
  );
  expect(skills[0].config_values).toEqual({ region: "west" });
  expect(skills[0].config_schemas).toEqual([
    { name: "region", type: "string", required: true },
  ]);
  expect(skills[0].tool_ids).toEqual([]);
  expect(skills[0].content).toBe("");
});

it("retains explicit list errors instead of accepting an empty failed summary", async () => {
  request.mockResolvedValue(new Response("unavailable", { status: 503 }));
  await expect(fetchSkillsList(undefined, "mount")).rejects.toThrow();
});

afterEach(() => vi.unstubAllGlobals());
