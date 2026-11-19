// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, it, vi } from "vitest";
import { restoreKnowledgeDisplay } from "@/features/workbench/knowledgeDisplay";
import knowledgeBaseService from "@/services/knowledgeBaseService";
vi.mock("@/services/knowledgeBaseService", () => ({
  default: {
    getKnowledgeBasesInfo: vi.fn(),
    getAidpKnowledgeBasesAll: vi.fn(),
    mapAidpKnowledgeBasesToKnowledgeBases: () => [],
  },
}));
it("restores names by business ID rather than list position after conversation creation", async () => {
  vi.mocked(knowledgeBaseService.getKnowledgeBasesInfo).mockResolvedValue({
    knowledgeBases: [
      { knowledge_id: 2, name: "Second" },
      { knowledge_id: 1, name: "First" },
    ],
  } as never);
  const result = await restoreKnowledgeDisplay({
    schema_version: 1,
    local: { mode: "override", knowledge_ids: ["1", "2", "3"] },
    aidp: { mode: "disabled", kds_ids: [] },
  });
  expect(result?.local.display_names).toEqual(["First", "Second", "#3"]);
  expect(knowledgeBaseService.getAidpKnowledgeBasesAll).not.toHaveBeenCalled();
});

it("restores saved IDs without querying unopened catalogs", async () => {
  vi.clearAllMocks();
  const result = await restoreKnowledgeDisplay(
    {
      schema_version: 1,
      local: { mode: "override", knowledge_ids: ["2", "1"] },
      aidp: { mode: "override", kds_ids: ["kds-a"] },
    },
    false
  );
  expect(result?.local.display_names).toEqual(["#2", "#1"]);
  expect(result?.aidp.kds_ids).toEqual(["kds-a"]);
  expect(knowledgeBaseService.getKnowledgeBasesInfo).not.toHaveBeenCalled();
  expect(knowledgeBaseService.getAidpKnowledgeBasesAll).not.toHaveBeenCalled();
});
